"""No physical hardware: verify exact-job gating and stage/robot separation."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import squid_stage
from squid_stage import SquidStage, digest, validate_loading_target
from lacry_agent import LacryAgent, TOOLS, SYSTEM
from sequences import Runner
from researcher_teaching import TeachingError


class StageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patch = patch.object(squid_stage,'ROOT',self.root);self.patch.start();self.addCleanup(self.patch.stop)
        self.target = dict(x_mm=.05,y_mm=.05,z_mm=1.05)
        self.pose = dict(x_mm=10.,y_mm=10.,z_mm=1.05)
        self.state = dict(connected=True,status='idle',session='one',stage_simulated=False,
                          controller_serial='12769210',completion_confirmed=False)
        self.calls = []
        self.audit_events=[]
        self.runner = Runner(event_sink=lambda event,**fields:self.audit_events.append((event,deepcopy(fields))))
        self.backend = Mock()
        self.backend.squid.poll.side_effect = lambda: deepcopy(self.state)
        home = dict(X=290,Y=63,Z=248,Rz=-3.88)
        self.backend.home.target.return_value = (home,'home')
        self.backend.healthy.return_value = dict(pose_mm=deepcopy(home))
        self.agent = LacryAgent(self.backend,Mock(),lambda:self.runner,client=Mock())
        ref = self.root/'reference.json'
        ref.write_text(json.dumps(dict(dropoff=self.target,operator_confirmed=True,
            controller_serial='12769210',source='operator confirmed')))
        self.engine = SquidStage(self.agent,ref,self.command,sleep=lambda _:None)
        self.agent.squid_stage = lambda:self.engine

    def command(self,name,params):
        self.calls.append((name,deepcopy(params)))
        if name=='get_position':return deepcopy(self.pose)
        if name=='get_stage_reference':return dict(reference_hash=digest(self.engine.saved()),controller_serial='12769210')
        if name=='return_to_recorded_dropoff':
            self.pose=deepcopy(self.target)
            return dict(at_dropoff=True,position=deepcopy(self.pose))
        if name=='move_to':
            self.pose.update({k:v for k,v in params.items() if k!='blocking'})
            return dict(moved_to=deepcopy(self.pose))
        if name=='home':
            self.pose=dict(x_mm=50.,y_mm=0.,z_mm=0.)
            return dict(homed=True,position=deepcopy(self.pose))
        raise AssertionError(name)

    def finish(self,plan):
        self.agent.confirm(dict(ready=True,plan_id=plan['id']))
        self.runner._thread.join(3)
        self.assertFalse(self.runner.active)
        return self.runner.result

    def scanning(self):
        self.state.update(status='running',job=dict(run_id='scan1',experiment_id='exp1'))

    def test_plan_is_readonly_then_confirmed_axes_return(self):
        plan=self.engine.propose('dropoff')
        self.assertEqual({n for n,p in self.calls},{'get_position','get_stage_reference'})
        self.assertTrue(self.finish(plan)['ok'])
        self.assertEqual(self.pose,self.target)
        self.assertEqual([p for n,p in self.calls if n=='return_to_recorded_dropoff'],[
            dict(reference_hash=plan['reference_hash'])])
        self.backend.execute_step.assert_not_called()
        self.backend.s.move_cartesian.assert_not_called()
        with self.assertRaises(TeachingError):self.agent.confirm(dict(ready=True,plan_id=plan['id']))

    def test_already_at_dropoff_is_noop(self):
        self.pose=deepcopy(self.target)
        self.assertTrue(self.finish(self.engine.propose('dropoff'))['ok'])
        self.assertFalse(any(n in ('home','move_to') for n,p in self.calls))

    def test_preserves_locations_before_stage_motion(self):
        def preserve():
            self.assertFalse(any(n=='return_to_recorded_dropoff' for n,p in self.calls))
            return dict(saved=True)
        self.engine.location_capture=Mock(side_effect=preserve)
        self.assertTrue(self.finish(self.engine.propose('dropoff'))['ok'])
        self.engine.location_capture.assert_called_once_with()
        self.assertTrue(any(event=='squid_stage_locations_preserved' for event,_ in self.audit_events))

    def test_location_save_failure_does_not_erase_sites_by_moving_stage(self):
        self.engine.location_capture=Mock(side_effect=TeachingError('Location archive unavailable'))
        self.assertFalse(self.finish(self.engine.propose('dropoff'))['ok'])
        self.assertFalse(any(n=='return_to_recorded_dropoff' for n,p in self.calls))

    def test_home_uses_native_homing_not_robot_or_dropoff(self):
        self.assertTrue(self.finish(self.engine.propose('home'))['ok'])
        self.assertEqual([n for n,p in self.calls if n not in ('get_position','get_stage_reference')],['home'])
        self.assertNotEqual(self.pose,self.target)

    def test_scan_cannot_be_interrupted(self):
        self.scanning()
        with self.assertRaisesRegex(TeachingError,'scanning'):self.engine.propose('dropoff')

    def test_waits_for_matching_scan_success(self):
        self.scanning();plan=self.engine.propose('dropoff',True)
        def finish_scan(_):
            self.assertFalse(any(n=='move_to' for n,p in self.calls))
            self.state.update(status='completed',completion_confirmed=True)
        self.engine.sleep=finish_scan
        # Subsequent stability wait should not simulate scan progress again.
        def once(_):
            finish_scan(_);self.engine.sleep=lambda _:None
        self.engine.sleep=once
        self.assertTrue(self.finish(plan)['ok'])
        self.assertEqual(len(self.agent.run_state['done']),2)

    def test_changed_scan_stops_without_stage_move(self):
        self.scanning();plan=self.engine.propose('dropoff',True)
        self.engine.sleep=lambda _:self.state['job'].update(run_id='scan2')
        self.assertFalse(self.finish(plan)['ok'])
        self.assertFalse(any(n=='move_to' for n,p in self.calls))

    def test_failed_scan_stops_without_stage_move(self):
        self.scanning();plan=self.engine.propose('dropoff',True)
        self.engine.sleep=lambda _:self.state.update(status='failed')
        self.assertFalse(self.finish(plan)['ok'])
        self.assertFalse(any(n=='move_to' for n,p in self.calls))

    def test_stop_during_wait_does_not_abort_scan(self):
        self.scanning();plan=self.engine.propose('dropoff',True)
        self.engine.sleep=lambda _:self.runner.request_stop()
        self.assertFalse(self.finish(plan)['ok'])
        self.assertEqual({n for n,p in self.calls},{'get_position','get_stage_reference'})

    def test_session_controller_reference_and_pose_changes_refuse(self):
        for change in ('session','controller','reference','pose'):
            with self.subTest(change=change):
                self.setUp()
                plan=self.engine.propose('dropoff')
                if change=='session':self.state['session']='two'
                if change=='controller':self.state['controller_serial']='other'
                if change=='reference':
                    ref=self.engine.saved();ref['dropoff']['x_mm']+=1
                    self.engine.reference.write_text(json.dumps(ref))
                if change=='pose':self.pose['y_mm']+=1
                with self.assertRaises(TeachingError):self.engine.start(plan)
                self.assertFalse(any(n=='move_to' for n,p in self.calls))

    def test_arm_away_from_home_refuses(self):
        self.backend.healthy.return_value['pose_mm']['Y']=373
        with self.assertRaises(Exception):self.engine.propose('dropoff')

    def test_new_scan_after_confirmation_refuses(self):
        plan=self.engine.propose('dropoff');self.scanning()
        with self.assertRaisesRegex(TeachingError,'scan started'):self.engine.start(plan)

    def test_persisted_motion_hold_keeps_readonly_position_available(self):
        ref=self.engine.saved();ref['motion_hold']='Review the failed X return.'
        self.engine.reference.write_text(json.dumps(ref))
        self.assertEqual(self.engine.status()['motion_hold'],ref['motion_hold'])
        with self.assertRaisesRegex(TeachingError,'failed X'):self.engine.propose('home')

    def test_negative_taught_readback_refused_without_clamping_or_movement(self):
        ref=self.engine.saved();ref['dropoff']['x_mm']=-.05000625
        self.engine.reference.write_text(json.dumps(ref))
        with self.assertRaisesRegex(TeachingError,'homed range'):self.engine.propose('dropoff')
        self.assertEqual(self.engine.saved()['dropoff']['x_mm'],-.05000625)
        self.assertFalse(any(n in ('home','return_to_recorded_dropoff') for n,p in self.calls))

    def test_prepared_positive_candidate_preserves_y_z(self):
        original=dict(x_mm=-.05000625,y_mm=.0508,z_mm=1.05)
        candidate=dict(original,x_mm=.05)
        self.assertEqual(validate_loading_target(dict(controller_serial='12769210',dropoff=candidate)),candidate)
        self.assertAlmostEqual(candidate['x_mm']-original['x_mm'],.10000625)
        self.assertEqual(candidate['y_mm'],original['y_mm'])
        self.assertEqual(candidate['z_mm'],original['z_mm'])

    def test_no_retry_on_native_failure(self):
        plan=self.engine.propose('dropoff')
        base=self.command
        def fail(name,params):
            if name=='return_to_recorded_dropoff':self.calls.append((name,params));raise TimeoutError('uncertain motion')
            return base(name,params)
        self.engine.command=fail
        self.assertFalse(self.finish(plan)['ok'])
        self.assertEqual(sum(n=='return_to_recorded_dropoff' for n,p in self.calls),1)

    def test_model_tools_and_readonly_status(self):
        self.assertIn('plan_squid_stage',{t['name'] for t in TOOLS})
        self.assertIn('NOT robot move_home',SYSTEM)
        data,error=self.agent._run_tool('get_squid_stage',{})
        self.assertFalse(error);self.assertTrue(json.loads(data)['ok'])
        self.assertEqual({n for n,p in self.calls},{'get_position'})


if __name__=='__main__':unittest.main()
