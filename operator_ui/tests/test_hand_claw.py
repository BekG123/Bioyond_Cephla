"""Fake-controller checks for reusing Developer move_gripper from Researcher."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hand_claw import HandClaw
from researcher_teaching import TeachingError
from test_researcher_workflow import FakeRunner


class ClawTests(unittest.TestCase):
    def setUp(self):
        self.state=dict(ok=True,connected=True,errors=[],enabled=True,
                        control_mode={'mode':'manual'},program_state={'state':'stopped'})
        self.hand=dict(state='active',active=True,blocked=True)
        self.pose=dict(X=292.,Y=65.,Z=248.,Rz=-2.7)
        self.e1=12.
        self.moves=[]
        self.service=SimpleNamespace(status=lambda:self.state,pose_mm=lambda:self.pose.copy(),
            joints=lambda:dict(J1=209.,J2=85.,J3=53.,J4=-140.),external_axes=lambda:dict(E1=self.e1),
            _preflight=lambda:None,move_gripper=Mock(side_effect=self.move))
        self.drag=SimpleNamespace(public=lambda _:self.hand)
        self.runner=FakeRunner()
        self.runner.name=''
        self.prepare=Mock(side_effect=self.prep)
        self.claw=HandClaw(lambda:self.service,lambda:self.runner,lambda:self.drag,
                          lambda:dict(claw_gap_min_mm=60.,claw_gap_max_mm=88.),self.prepare)
        sleeper=patch('hand_claw.time.sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def prep(self,run,service):
        self.assertEqual(self.moves,[])
        self.hand.update(state='off',active=False,blocked=False)
        self.state.update(control_mode={'mode':'auto'},program_state={'state':'running'})
        self.e1=0.

    def move(self,target,speed):
        self.moves.append(target)
        self.e1=target
        return dict(ok=True)

    def start(self,action='open',empty=True):
        return self.claw.start(dict(action=action,ready=True,empty_gripper=empty))

    def test_draggo_prepared_then_exact_developer_service_called(self):
        self.start()
        self.assertTrue(self.runner.finish()['ok'])
        self.prepare.assert_called_once()
        self.service.move_gripper.assert_called_once_with(28.,speed=5)
        self.assertFalse(self.hand['active'])

    def test_auto_ready_does_not_restart_program_or_require_empty(self):
        self.prep(self.runner,self.service)
        self.e1=12.
        self.start(empty=False)
        self.runner.finish()
        self.prepare.assert_not_called()
        self.service.move_gripper.assert_called_once_with(28.,speed=5)

    def test_manual_requires_empty_confirmation_before_any_command(self):
        with self.assertRaises(TeachingError): self.start(empty=False)
        self.prepare.assert_not_called()
        self.service.move_gripper.assert_not_called()

    def test_small_step_uses_feedback_after_startup_reset(self):
        self.start('step')
        self.runner.finish()
        self.service.move_gripper.assert_called_once_with(.2,speed=5)

    def test_preparation_failure_never_opens(self):
        self.prepare.side_effect=RuntimeError('mode switch failed')
        self.start()
        with self.assertRaises(RuntimeError): self.runner.finish()
        self.service.move_gripper.assert_not_called()

    def test_arm_change_during_preparation_blocks_gripper(self):
        def changed(run,service):
            self.prep(run,service)
            self.pose['Z']+=1
        self.prepare.side_effect=changed
        self.start()
        with self.assertRaisesRegex(TeachingError,'changed position'): self.runner.finish()
        self.service.move_gripper.assert_not_called()

    def test_mode_change_after_request_requires_empty_confirmation(self):
        self.prep(self.runner,self.service)
        self.start(empty=False)
        self.state['control_mode']['mode']='manual'
        with self.assertRaisesRegex(TeachingError,'empty-gripper'): self.runner.finish()
        self.prepare.assert_not_called()
        self.service.move_gripper.assert_not_called()

    def test_faults_unknown_hand_and_busy_block(self):
        self.state['errors']=[{'code':3873}]
        with self.assertRaises(TeachingError): self.start()
        self.state['errors']=[]
        self.hand['state']='unknown'
        with self.assertRaises(TeachingError): self.start()
        self.hand['state']='active'
        self.runner.active=True
        with self.assertRaises(TeachingError): self.start()
        self.service.move_gripper.assert_not_called()

    def test_uncertain_reply_has_no_retry(self):
        self.service.move_gripper.side_effect=lambda *a,**kw:dict(ok=True,recovered='drop')
        self.start()
        with self.assertRaises(TeachingError): self.runner.finish()
        self.assertEqual(self.service.move_gripper.call_count,1)

    def test_ack_without_arrival_is_not_success(self):
        self.service.move_gripper.side_effect=lambda *a,**kw:dict(ok=True)
        self.start()
        with self.assertRaisesRegex(TeachingError,'did not reach'): self.runner.finish()

    def test_stop_before_preparation_and_other_sequence_ownership(self):
        self.start()
        self.claw.stop()
        with self.assertRaisesRegex(TeachingError,'Stopped'): self.runner.finish()
        self.prepare.assert_not_called()
        self.service.move_gripper.assert_not_called()
        self.runner.active,self.runner.name,self.runner.cancelled=True,'home',False
        self.claw.stop()
        self.assertFalse(self.runner.cancelled)


if __name__=='__main__':
    unittest.main()
