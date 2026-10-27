"""Recorded traversals use fake hardware and temporary permission files."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from recorded_return import RecordedReturn
from researcher_teaching import TeachingError
from autonomy import check_path, TransferError
from test_transfer import FakeService, PARAMS
from test_researcher_workflow import FakeRunner
from robot_service import RobotService


class RecordedTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.svc, self.run = FakeService(), FakeRunner()
        self.run.name = ''
        self.initial = self.svc.pose.copy()
        self.q = self.svc.q.copy()
        target = {**self.initial,'Y':5}
        endq = check_path(self.initial,target,self.q,PARAMS,None)
        self.data = dict(trajectory=[dict(valid=True,elapsed_s=0,pose_mm=self.initial,joints=self.q),
            dict(valid=True,elapsed_s=.2,pose_mm=target,joints=endq)],
            validation={'kinematics_passed':True},source={'sha256':hashlib.sha256(b'raw').hexdigest()})
        (self.folder/'samples.jsonl').write_bytes(b'raw')
        self.save()
        self.svc.status = lambda:dict(ok=True,connected=True,errors=[],pose_mm=self.svc.pose,joints=self.svc.q)
        self.calls = []
        def move(x,y,z,rz,**options):
            self.calls.append(options)
            end=dict(X=x,Y=y,Z=z,Rz=rz)
            self.svc.q=check_path(self.svc.pose,end,self.svc.q,PARAMS,None)
            self.svc.pose=end
            return dict(ok=True)
        self.svc.move_cartesian=move
        self.prepare,self.invalidate=Mock(),Mock()
        self.replay=RecordedReturn(self.folder,lambda:self.svc,lambda:self.run,lambda:PARAMS,self.prepare,self.invalidate)

    def save(self):
        raw=json.dumps(self.data).encode()
        (self.folder/'return_path.json').write_bytes(raw)
        self.ident=hashlib.sha256(raw).hexdigest()
        (self.folder/'replay_permission.json').write_text(json.dumps(dict(path_sha256=self.ident,
            workspace_box_exception=True,attempt_available=True,allow_explicit_repeats=True)))

    def start(self,direction='toward_home'):
        return self.replay.start(dict(ready=True,path_id=self.ident,direction=direction))

    def test_forward_reverse_and_box_settings_unchanged(self):
        before=(self.svc.envelope.copy(),self.svc.envelope_enabled)
        self.start()
        self.assertTrue(self.run.finish()['ok'])
        self.assertTrue(all(c['_recorded_box_exception'] and c['speed']==10 and c['interpolation']=='linear' for c in self.calls))
        self.start('to_hamilton')
        self.assertTrue(self.run.finish()['ok'])
        self.assertEqual(self.svc.pose,self.initial)
        self.assertEqual(before,(self.svc.envelope,self.svc.envelope_enabled))
        self.assertEqual(self.svc.grips,[])

    def test_displaced_start_no_preparation_or_move(self):
        self.svc.pose={**self.initial,'Z':self.initial['Z']+4}
        with self.assertRaises(TeachingError):self.start()
        self.prepare.assert_not_called()
        self.assertEqual(self.calls,[])

    def test_speed_40_is_used_and_reported_without_clipping(self):
        path=self.folder/'replay_permission.json'
        grant=json.loads(path.read_text())
        grant['speed']=40
        path.write_text(json.dumps(grant))
        self.start()
        result=self.run.finish()
        self.assertEqual(result['speed'],40)
        self.assertTrue(all(c['speed']==40 for c in self.calls))

    def test_queued_replay_routes_through_lua_and_rearms_only_on_success(self):
        from test_trajectory_queue import Controller
        self.svc.robot=Controller(self.svc)
        self.svc._locked=lambda fn:fn()
        self.svc.program=Mock(return_value=dict(ok=True))
        self.replay.start(dict(ready=True,path_id=self.ident,direction='toward_home',executor='lua_queue'))
        result=self.run.finish()
        self.assertEqual(result['executor'],'lua_queue')
        self.assertEqual(self.calls,[]) # stepwise API never used
        self.assertEqual(self.svc.robot.barriers,1)
        self.assertTrue(json.loads((self.folder/'replay_permission.json').read_text())['attempt_available'])

    def test_queue_unavailable_rejects_before_preparation(self):
        with self.assertRaises(TeachingError):
            self.replay.start(dict(ready=True,path_id=self.ident,direction='toward_home',executor='lua_queue'))
        self.prepare.assert_not_called()
        self.assertEqual(self.calls,[])

    def test_invalid_speed_cannot_start(self):
        path=self.folder/'replay_permission.json'
        grant=json.loads(path.read_text())
        for speed in (0,-1,41,float('nan'),True,'40'):
            grant['speed']=speed
            path.write_text(json.dumps(grant))
            with self.assertRaises(TeachingError):self.start()
        self.prepare.assert_not_called()
        self.assertEqual(self.calls,[])

    def test_changed_recording_or_permission_refused(self):
        (self.folder/'samples.jsonl').write_bytes(b'changed')
        with self.assertRaises(TeachingError):self.start()
        self.assertEqual(self.calls,[])

    def test_stop_before_prepare_consumes_attempt(self):
        self.start()
        self.replay.stop()
        with self.assertRaises(TransferError):self.run.finish()
        self.prepare.assert_not_called()
        self.assertFalse(json.loads((self.folder/'replay_permission.json').read_text())['attempt_available'])

    def test_failed_or_recovered_move_stops_without_retry(self):
        self.svc.move_cartesian=Mock(return_value=dict(ok=True,recovered='uncertain'))
        self.start()
        with self.assertRaises(TransferError):self.run.finish()
        self.svc.move_cartesian.assert_called_once()
        self.assertFalse(json.loads((self.folder/'replay_permission.json').read_text())['attempt_available'])

    def test_joint_limit_rejection_even_when_recorded_review_claims_pass(self):
        self.data['trajectory'][1]['pose_mm']={**self.initial,'X':526}
        self.save()
        with self.assertRaises(TeachingError):self.start()
        self.assertEqual(self.calls,[])

    def test_displacement_during_preparation_blocks(self):
        self.prepare.side_effect=lambda *_:self.svc.pose.update(Z=self.svc.pose['Z']+5)
        self.start()
        with self.assertRaises(TeachingError):self.run.finish()
        self.assertEqual(self.calls,[])

    def test_bad_joint_arrival_stops(self):
        original=self.svc.move_cartesian
        def wrong(*args,**kwargs):
            result=original(*args,**kwargs)
            self.svc.q['J4']+=2
            return result
        self.svc.move_cartesian=wrong
        self.start()
        with self.assertRaises(TransferError):self.run.finish()
        self.assertEqual(len(self.calls),1)

    def test_service_exception_skips_only_box_and_retains_reach(self):
        service=object.__new__(RobotService)
        service.envelope_enabled=True
        service.envelope={'X':(200,450),'Y':(-250,100),'Z':(70,400)}
        self.assertIsNotNone(service._check_envelope(195,-360,48))
        self.assertIsNone(service._check_envelope(195,-360,48,recorded_box_exception=True))
        self.assertIsNotNone(service._check_envelope(526,0,100,recorded_box_exception=True))
        self.assertTrue(service.envelope_enabled)

    def mark_stopped(self):
        path=self.folder/'replay_permission.json'
        grant=json.loads(path.read_text())
        grant.update(attempt_available=False,status='stopped_or_failed',direction='to_hamilton')
        path.write_text(json.dumps(grant))

    def test_recovery_reverses_prefix_without_changing_original(self):
        self.mark_stopped()
        raw=(self.folder/'return_path.json').read_bytes()
        data,ident,grant,legs,cfg,review=self.replay.recovery_plan(self.svc.pose,self.svc.q)
        self.assertEqual(review['matched_waypoint'],1)
        self.assertEqual(legs[-1],self.data['trajectory'][-1]['pose_mm'])
        self.assertEqual(data['trajectory'][0]['pose_mm'],self.svc.pose)
        self.assertEqual(raw,(self.folder/'return_path.json').read_bytes())
        self.assertFalse(grant['attempt_available'])
        with self.assertRaises(TeachingError):self.start()

    def test_recovery_refuses_displaced_pose_or_wrong_branch(self):
        self.mark_stopped()
        for pose,q in (({**self.svc.pose,'Z':self.svc.pose['Z']+1},self.svc.q),
                       (self.svc.pose,{**self.svc.q,'J4':self.svc.q['J4']+1})):
            with self.assertRaises(TeachingError):self.replay.recovery_plan(pose,q)
        self.prepare.assert_not_called()

    def test_recovery_requires_failed_forward_and_reviewed_index(self):
        with self.assertRaises(TeachingError):self.replay.recovery_plan(self.svc.pose,self.svc.q)
        self.mark_stopped()
        with self.assertRaises(TeachingError):
            self.replay.start_recovery(dict(ready=True,path_id=self.ident,matched_waypoint=99))
        self.prepare.assert_not_called()

    def test_recovery_queue_success_rearms_and_failed_prepare_does_not(self):
        from test_trajectory_queue import Controller
        self.mark_stopped()
        self.svc.robot=Controller(self.svc)
        self.svc._locked=lambda fn:fn()
        self.svc.program=Mock(return_value=dict(ok=True))
        body=dict(ready=True,path_id=self.ident,matched_waypoint=1)
        self.replay.start_recovery(body)
        result=self.run.finish()
        self.assertEqual(result['direction'],'recover_start')
        self.assertEqual(self.svc.pose,self.data['trajectory'][-1]['pose_mm'])
        self.assertTrue(json.loads((self.folder/'replay_permission.json').read_text())['attempt_available'])
        self.svc.pose,self.svc.q=self.initial.copy(),self.q.copy()
        self.mark_stopped()
        self.prepare.side_effect=TransferError('test preparation failure')
        self.replay.start_recovery(body)
        with self.assertRaises(TransferError):self.run.finish()
        self.assertFalse(json.loads((self.folder/'replay_permission.json').read_text())['attempt_available'])


if __name__=='__main__': unittest.main()
