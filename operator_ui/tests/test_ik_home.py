"""Current-position Home planning and gripper-preserving execution; fake robot."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ik_home import IKHomeConnection
import test_researcher_home as home_fixtures
from researcher_teaching import TeachingError
from autonomy import check_path
from test_transfer import PARAMS
from sequences import Runner
from home_attempts import ProgramStartRefused, known_startup_refusal, known_preflight_refusal


class IKHomeTests(unittest.TestCase):
    def setUp(self):
        home_fixtures.HomeTests.setUp(self)
        self.service.e1=3.8
        self.service.external_axes=lambda:dict(E1=self.service.e1)
        self.service.status=lambda:{**self.state,'pose_mm':self.service.pose_mm(),
            'joints':self.service.joints(),'external_axes':self.service.external_axes()}
        self.connection=IKHomeConnection(self.home,Path(self.tmp.name)/'ik_attempts')

    def plan(self):return {**self.connection.propose(),'id':'confirmed-'+str(len(list(self.connection.folder.glob('*.json'))))}

    def test_new_pickup_and_intermediate_positions_do_not_need_registered_start(self):
        for end in (dict(X=319.105,Y=-66.328,Z=70.461,Rz=91.935),
                    dict(X=315.936,Y=-66.974,Z=253.72,Rz=7.899)):
            self.service.q=check_path(self.service.pose,end,self.service.q,PARAMS,self.service.envelope)
            self.service.q['J1']=end['Z']-38.599
            self.service.pose=end
            plan=self.plan()
            self.assertEqual(plan['dispatch'],'ik_home_return')
            self.assertEqual(plan['start'],end)
            self.assertTrue(plan['preserve_gripper'])
            self.assertEqual(plan['checked'][-1]['pose'],self.home.target()[0])
        self.assertEqual(self.service.moves,[]);self.assertEqual(self.service.grips,[])

    def test_loaded_return_keeps_claw_and_skips_auto_preparation(self):
        self.home.prepare=Mock(side_effect=AssertionError('No loaded Auto restart'))
        plan=self.plan();result,attempt=self.connection.start(plan)
        self.assertTrue(result['ok'])
        result=self.runner.finish()
        self.assertTrue(result['ok'])
        self.assertEqual(self.service.e1,3.8);self.assertEqual(self.service.grips,[])
        self.home.prepare.assert_not_called()
        self.connection.finish(attempt,dict(state='done',result=result))
        self.assertEqual(json.loads(attempt.read_text())['status'],'completed')

    def test_changed_claw_pose_or_config_invalidates_confirmation(self):
        plan=self.plan()
        for mutate,undo in ((lambda:setattr(self.service,'e1',4),lambda:setattr(self.service,'e1',3.8)),
                (lambda:self.service.pose.update(Z=301),lambda:self.service.pose.update(Z=300))):
            mutate()
            with self.assertRaises(TeachingError):self.connection.start(plan)
            undo()
        self.assertEqual(self.service.moves,[])
        self.assertFalse(self.connection.folder.exists())

    def test_limits_are_not_removed(self):
        self.service.pose['X']=700
        with self.assertRaisesRegex(TeachingError,'Home route blocked'):self.plan()
        self.assertEqual(self.service.moves,[])

    def test_fault_or_hand_guiding_blocks_planning(self):
        self.state['errors']=[10]
        with self.assertRaises(TeachingError):self.plan()
        self.state['errors']=[];self.hand['state']='active'
        with self.assertRaises(TeachingError):self.plan()

    def test_stopped_controller_requires_empty_gripper_confirmation(self):
        self.state.update(control_mode=dict(mode='manual'),enabled=False,program_state=dict(state='stopped'))
        self.home.prepare=Mock()
        plan=self.plan()
        self.assertFalse(plan['preserve_gripper'])
        self.assertIn('gripper is empty',' '.join(plan['requirements']))
        self.home.prepare.assert_not_called()

    def test_controller_state_change_prevents_loaded_start(self):
        plan=self.plan()
        self.state.update(enabled=False,program_state=dict(state='stopped'))
        with self.assertRaisesRegex(TeachingError,'readiness changed'):self.connection.start(plan)
        self.assertEqual(self.service.moves,[])

    def test_gripper_change_between_confirmation_and_execution_prevents_travel(self):
        _,attempt=self.connection.start(self.plan())
        self.service.e1=4.0
        with self.assertRaisesRegex(Exception,'Gripper feedback changed'):self.runner.finish()
        self.assertEqual(self.service.moves,[]);self.assertEqual(self.rotations,[])

    def test_completed_run_allows_new_plan_but_failed_run_does_not(self):
        original_pose=deepcopy(self.service.pose);original_q=deepcopy(self.service.q)
        _,attempt=self.connection.start(self.plan())
        result=self.runner.finish();self.connection.finish(attempt,dict(state='done',result=result))
        self.service.pose=original_pose;self.service.q=original_q
        second=self.plan()
        self.assertEqual(second['dispatch'],'ik_home_return')
        self.connection.finish(attempt,dict(state='error',result=dict(ok=False)))
        with self.assertRaisesRegex(TeachingError,'previous IK Home return'):self.plan()

    def test_workflow_owner_can_start_home_but_other_thread_cannot_plan(self):
        self.runner=Runner()
        token=object()
        self.assertTrue(self.runner.reserve(token,threading.Event()))
        self.runner.claim(token)
        failures=[]
        def outsider():
            try:self.connection.propose()
            except TeachingError:failures.append('blocked')
        thread=threading.Thread(target=outsider);thread.start();thread.join()
        self.assertEqual(failures,['blocked'])
        result,attempt=self.connection.start(self.plan())
        self.assertTrue(result['ok'])
        self.runner._thread.join(5)
        self.assertFalse(self.runner.active)
        self.assertTrue(self.runner.result['ok'],self.runner.result)
        self.assertEqual(self.service.e1,3.8)
        self.assertEqual(self.service.grips,[])
        self.connection.finish(attempt,self.runner.snapshot())
        self.runner.release(token)

    def run_failed_home(self, error, *, preparing=True):
        self.runner = Runner()
        if preparing:
            self.state.update(control_mode=dict(mode='manual'), enabled=False,
                              program_state=dict(state='stopped'))
            self.home.prepare = Mock(side_effect=error)
        else:
            self.service.rotate_to_rz = Mock(side_effect=error)
        plan = self.plan()
        _, attempt = self.connection.start(plan)
        self.runner._thread.join(5)
        self.assertFalse(self.runner.active)
        self.connection.finish(attempt, self.runner.snapshot())
        return plan, attempt

    def test_explicit_startup_refusal_is_audited_and_allows_fresh_plan(self):
        plan, attempt = self.run_failed_home(ProgramStartRefused('fixture held-object refusal'))
        record = json.loads(attempt.read_text())
        self.assertTrue(known_startup_refusal(record))
        self.assertFalse(record['sequence']['result']['ok'])
        self.assertEqual(record['sequence']['state'], 'error')
        self.assertEqual(self.service.moves, [])
        self.assertEqual(self.rotations, [])
        home_record = next((self.path.parent/'home_route_runs').glob('*.json'))
        self.assertTrue(known_startup_refusal(json.loads(home_record.read_text())))
        self.assertEqual(self.plan()['dispatch'], 'ik_home_return')
        with self.assertRaisesRegex(TeachingError, 'already used'):
            self.connection.start(plan)
        self.state['errors'] = [10]
        with self.assertRaisesRegex(TeachingError, 'robot alert'):
            self.plan()

    def test_startup_timeout_remains_uncertain(self):
        _, attempt = self.run_failed_home(RuntimeError('program start timed out'))
        self.assertFalse(known_startup_refusal(json.loads(attempt.read_text())))
        with self.assertRaisesRegex(TeachingError, 'previous IK Home return'):
            self.plan()

    def test_refusal_exception_after_travel_dispatch_does_not_unlock(self):
        _, attempt = self.run_failed_home(ProgramStartRefused('unexpected after dispatch'),
                                         preparing=False)
        self.service.rotate_to_rz.assert_called()
        self.assertFalse(known_startup_refusal(json.loads(attempt.read_text())))
        with self.assertRaisesRegex(TeachingError, 'previous IK Home return'):
            self.plan()

    def test_missing_or_corrupt_evidence_never_unlocks(self):
        self.connection.folder.mkdir()
        attempt = self.connection.folder/'test.json'
        for text in ('{', '[]', json.dumps(dict(status='failed_to_start')),
                     json.dumps(dict(status='failed_or_stopped',
                       home_startup_refusal=dict(schema=1,reason='gripper_held_start_refused',
                         program_start_sent=False,home_travel_dispatched=True)))):
            attempt.write_text(text)
            with self.assertRaisesRegex(TeachingError, 'previous IK Home return'):
                self.plan()

    def test_hand_status_preflight_failure_does_not_poison_home_history(self):
        plan = self.plan()
        with patch.object(self.home, 'public', return_value=dict(can_start=False,
                           blocker='Hand-guiding status needs attention.')):
            with self.assertRaisesRegex(TeachingError, 'Hand-guiding'):
                self.connection.start(plan)
        record = json.loads(next(self.connection.folder.glob('*.json')).read_text())
        self.assertTrue(known_preflight_refusal(record))
        self.assertFalse(record.get('dispatch_requested', False))
        self.assertFalse(self.runner.active)
        self.assertEqual(self.service.moves, [])
        self.assertEqual(self.plan()['dispatch'], 'ik_home_return')
        with self.assertRaisesRegex(TeachingError, 'already used'):
            self.connection.start(plan)

    def test_exception_after_dispatch_boundary_stays_uncertain(self):
        plan = self.plan()
        with patch.object(self.runner, 'start', side_effect=RuntimeError('dispatch result lost')):
            with self.assertRaisesRegex(RuntimeError, 'dispatch result lost'):
                self.connection.start(plan)
        record = json.loads(next(self.connection.folder.glob('*.json')).read_text())
        self.assertTrue(record['dispatch_requested'])
        self.assertFalse(known_preflight_refusal(record))
        with self.assertRaisesRegex(TeachingError, 'no verified completion'):
            self.plan()


if __name__=='__main__':unittest.main()
