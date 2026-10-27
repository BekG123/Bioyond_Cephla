"""Position closing and single-use descent context. Fake hardware only."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sequences import Runner
from pick_and_hold.Grip.position import PositionGrip
from researcher_teaching import TeachingError


class Service:
    def __init__(self):
        self.pose=dict(X=307.,Y=-69.,Z=71.,Rz=89.)
        self.e1=28.;self.calls=[];self.mode='auto';self.enabled=True;self.program='running'
        self.result=None;self.enter=None;self.release=None
    def status(self):return dict(connected=True,ok=True,errors=[],pose_mm=self.pose.copy(),external_axes=self.external_axes(),control_mode={'mode':self.mode},enabled=self.enabled,program_state={'state':self.program})
    def pose_mm(self):return self.pose.copy()
    def external_axes(self):return {'E1':self.e1}
    def _preflight(self):return None if self.mode=='auto' and self.enabled and self.program=='running' else 'not ready'
    def move_gripper(self,target,speed):
        self.calls.append((target,speed))
        if self.enter:self.enter.set();self.release.wait(3)
        self.e1=target
        return self.result or dict(ok=True,gripper=dict(e1_position=target,e1_torque=25))


class PositionGripTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.s=Service();self.r=Runner();self.g=PositionGrip(self.temp.name,lambda:self.s,lambda:self.r)
        self.g.SETTLE_TIMEOUT=.05;self.g.SETTLE_INTERVAL=.001
        self.g.completed_descent(dict(ok=True,breach=False,executor='lua_descent'),self.s.pose)
    def body(self):return dict(ready=True,descent_id=self.g.receipt['id'])
    def wait(self):
        self.r._thread.join(4);self.assertFalse(self.r.active)
    def start(self):self.g.start(self.body());self.wait();return self.r.result
    def test_single_close_and_no_grasp_or_lift_claim(self):
        self.assertTrue(self.start()['ok']);self.assertEqual(self.s.calls,[(3.8,5)])
        self.assertFalse(self.r.result['gripped']);self.assertFalse(self.r.result['grasp_verified'])
        record=json.loads(Path(self.r.result['record']).read_text())
        self.assertEqual(record['measured_e1_mm'],3.8)
        with self.assertRaises(TeachingError):self.g.start(self.body())
    def test_poll_never_commands(self):
        self.assertTrue(self.g.public(self.s.status())['can_start']);self.assertEqual(self.s.calls,[])
    def test_requires_current_descent_and_explicit_ready(self):
        for body in ({},dict(ready=True,descent_id='stale'),dict(self.body(),target=3)):
            with self.assertRaises(TeachingError):self.g.start(body)
        self.g.invalidate()
        with self.assertRaises(TeachingError):self.g.start(self.body())
        self.assertEqual(self.s.calls,[])
    def test_no_auto_preparation_or_loaded_claw_baseline(self):
        for attribute,value in [('mode','manual'),('enabled',False),('program','stopped'),('e1',3.8)]:
            original=getattr(self.s,attribute);setattr(self.s,attribute,value)
            with self.assertRaises(TeachingError):self.g.start(self.body())
            setattr(self.s,attribute,original)
        self.assertEqual(self.s.calls,[])
    def test_changed_pose_and_expired_context(self):
        self.s.pose['Z']+=.2
        with self.assertRaises(TeachingError):self.g.start(self.body())
        self.s.pose['Z']-=.2;self.g.receipt['recorded_at']-=601
        with self.assertRaises(TeachingError):self.g.start(self.body())
    def test_uncertain_stalled_and_invalid_feedback_never_retry_or_open(self):
        for response in ({'ok':False},{'ok':True,'recovered':'uncertain'}, {'ok':True,'gripper_warning':'missing report'}, {'ok':True,'gripper':{'e1_position':float('nan')}}):
            self.g.completed_descent(dict(ok=True,executor='lua_descent'),self.s.pose)
            self.s.e1=28;self.s.result=response;self.s.calls=[]
            self.assertFalse(self.start()['ok']);self.assertEqual(self.s.calls,[(3.8,5)])

    def test_early_lua_report_uses_fresh_settled_feedback_without_retry(self):
        self.s.result=dict(ok=True,gripper=dict(e1_position=3.982))
        self.assertTrue(self.start()['ok'])
        self.assertEqual(self.s.calls,[(3.8,5)])
        record=json.loads(Path(self.r.result['record']).read_text())
        self.assertEqual(record['immediate_report_e1_mm'],3.982)
        self.assertEqual(len(record['settling_samples']),3)
        self.assertFalse(self.r.result['grasp_verified'])

    def test_real_stall_still_fails_without_retry(self):
        original=self.s.move_gripper
        def stalled(*args,**kwargs):
            result=original(*args,**kwargs);self.s.e1=3.982;return result
        self.s.move_gripper=stalled
        self.assertFalse(self.start()['ok'])
        self.assertIn('did not settle',self.r.result['error'])
        self.assertEqual(self.s.calls,[(3.8,5)])

    def test_one_in_range_sample_does_not_confirm_settling(self):
        original=self.s.move_gripper
        def oscillating(*args,**kwargs):
            result=original(*args,**kwargs)
            values=iter([3.8,4.0,3.8,4.0]*100)
            self.s.external_axes=lambda:{'E1':next(values)}
            return result
        self.s.move_gripper=oscillating
        self.assertFalse(self.start()['ok'])
        self.assertEqual(self.s.calls,[(3.8,5)])

    def test_stop_during_passive_settling_does_not_retry(self):
        original=self.s.move_gripper
        def stopped(*args,**kwargs):
            result=original(*args,**kwargs)
            def feedback():self.r.request_stop();return {'E1':3.8}
            self.s.external_axes=feedback
            return result
        self.s.move_gripper=stopped
        self.assertFalse(self.start()['ok'])
        self.assertEqual(self.s.calls,[(3.8,5)])
    def test_duplicate_click_and_stop_during_close(self):
        self.s.enter=threading.Event();self.s.release=threading.Event()
        body=self.body();self.g.start(body);self.assertTrue(self.s.enter.wait(2))
        with self.assertRaises(TeachingError):self.g.start(body)
        self.g.stop();self.s.release.set();self.wait()
        self.assertFalse(self.r.result['ok']);self.assertEqual(self.s.calls,[(3.8,5)])
    def test_receipt_survives_reload_but_consumed_one_cannot_resume(self):
        other=PositionGrip(self.temp.name,lambda:self.s,lambda:self.r)
        self.assertTrue(other.public(self.s.status())['can_start'])
        self.start()
        again=PositionGrip(self.temp.name,lambda:self.s,lambda:self.r)
        self.assertFalse(again.public(self.s.status())['can_start'])
    def test_logging_failure_prevents_command(self):
        with patch.object(Path,'write_text',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):self.g.start(self.body())
        self.assertEqual(self.s.calls,[])
    def test_api_routes_and_stop_bypass(self):
        from test_researcher import console
        with patch.object(console.position_grip,'start',return_value={'ok':True}) as start:
            for path in ('/seq/grip','/researcher/api/grip/start'):
                response=console.app.test_client().post(path,json=self.body())
                self.assertEqual(response.status_code,200)
            self.assertEqual(start.call_count,2)
        with patch.object(console.runner,'_thread',Mock(is_alive=lambda:True)),patch.object(console.position_grip,'stop',return_value={'ok':True}) as stop:
            self.assertEqual(console.app.test_client().post('/researcher/api/grip/stop',json={}).status_code,200)
            stop.assert_called_once()


if __name__=='__main__':unittest.main()
