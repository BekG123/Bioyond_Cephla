"""Home motion tests use only a fake controller; no hardware calls."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from researcher_home import HomeReturn
from researcher_teaching import TeachingError
from test_transfer import FakeService, PARAMS
from test_researcher_workflow import FakeRunner
from autonomy import check_path
from test_trajectory_queue import Controller


class HomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'points.json'
        self.path.write_text(json.dumps(dict(points={'Home':dict(x=289.97,y=62.63,z_grip=248.02,rz=-3.88)},roles={'home':'Home'})))
        self.service = FakeService()
        self.service.pose = dict(X=292.872,Y=-68.723,Z=300.,Rz=84.637)
        self.service.q = dict(J1=261.401,J2=40.79778,J3=53.63798,J4=-9.79890)
        self.service.robot=Controller(self.service)
        self.service._locked=lambda fn:fn()
        def stop_program(action):
            self.service.robot.program_state='stopped'
            self.service.robot.released.set()
            return dict(ok=True)
        self.service.program=stop_program
        self.state = dict(ok=True,connected=True,errors=[],control_mode={'mode':'auto'},enabled=True,program_state={'state':'running'})
        self.service.status = lambda: self.state.copy()
        self.rotations = []
        def rotate(rz, speed, force_delta):
            self.rotations.append(rz)
            end = {**self.service.pose, 'Rz': rz}
            self.service.q = check_path(self.service.pose,end,self.service.q,PARAMS,self.service.envelope)
            self.service.pose = end
            return {'ok':True}
        self.service.rotate_to_rz = rotate
        self.runner = FakeRunner()
        self.runner.name = ''
        self.hand = {'state':'off'}
        self.invalidated = Mock()
        self.home = HomeReturn(self.path,lambda:self.service,lambda:self.runner,
            lambda:SimpleNamespace(public=lambda _:self.hand),lambda:PARAMS,self.invalidated)
        self.body = dict(ready=True,target_id=self.home.target()[1])

    def test_return_verifies_home_and_never_grips_or_changes_saved_point(self):
        original = self.path.read_bytes()
        self.home.start(self.body)
        result = self.runner.finish()
        self.assertTrue(result['ok'])
        for k,v in self.home.target()[0].items():self.assertAlmostEqual(self.service.pose[k],v,places=3)
        self.assertEqual(len(self.service.robot.calls),2)
        self.assertTrue(all(c[1]==137 for c in self.service.robot.calls))
        self.assertEqual(self.service.grips,[])
        self.assertEqual(original,self.path.read_bytes())
        self.assertTrue(self.rotations)
        self.invalidated.assert_called_once()

    def test_no_confirmation_no_move(self):
        with self.assertRaises(TeachingError): self.home.start({**self.body,'ready':False})
        self.assertEqual(self.service.moves,[])

    def test_home_completion_message_is_not_reused_after_hand_guiding(self):
        self.home.message='At saved Home. Your teaching records are unchanged.'
        current={**self.state,'pose_mm':dict(self.service.pose),'joints':dict(self.service.q)}
        result=self.home.public(current,self.hand)
        self.assertFalse(result['at_home'])
        self.assertNotIn('At saved Home',result['message'])
        current['pose_mm']=self.home.target()[0]
        result=self.home.public(current,self.hand)
        self.assertTrue(result['at_home'])
        self.assertIn('At saved Home',result['message'])
        self.assertEqual(self.service.moves,[])

    def test_stale_target_no_move(self):
        with self.assertRaises(TeachingError): self.home.start({**self.body,'target_id':'old'})
        self.assertFalse(self.runner.active)

    def test_home_prepares_from_draggo_before_first_motion(self):
        self.hand.update(state='active',active=True,blocked=True)
        self.state.update(control_mode={'mode':'manual'},program_state={'state':'stopped'},enabled=True)
        self.service.refusal = 'End hand-guiding first'
        def prepare(run, service):
            self.assertEqual(service.moves,[])
            self.assertEqual(self.rotations,[])
            self.hand.update(state='off',active=False,blocked=False)
            self.state.update(control_mode={'mode':'auto'},program_state={'state':'running'})
            service.refusal = None
        self.home.prepare = Mock(side_effect=prepare)
        self.assertTrue(self.home.public(self.state,self.hand)['can_start'])
        self.home.start(self.body)
        self.assertTrue(self.runner.finish()['ok'])
        self.home.prepare.assert_called_once()

    def test_failed_preparation_never_moves_home(self):
        self.home.prepare = Mock(side_effect=RuntimeError('Auto enable failed'))
        self.home.start(self.body)
        with self.assertRaises(RuntimeError): self.runner.finish()
        self.assertEqual(self.service.moves,[])
        self.assertEqual(self.rotations,[])

    def test_arm_displacement_during_preparation_prevents_home_motion(self):
        self.home.prepare = lambda run,service:service.pose.update(X=service.pose['X']+5)
        self.home.start(self.body)
        with self.assertRaises(Exception): self.runner.finish()
        self.assertEqual(self.service.moves,[])

    def test_draggo_fault_disconnection_and_busy_block(self):
        for key,value in [('connected',False),('errors',[{'code':3873}]),('enabled',False)]:
            prior = self.state[key]
            self.state[key] = value
            with self.assertRaises(TeachingError): self.home.start(self.body)
            self.state[key] = prior
        self.hand['state'] = 'active'
        with self.assertRaises(TeachingError): self.home.start(self.body)
        self.hand['state'] = 'off'
        self.runner.active = True
        with self.assertRaises(TeachingError): self.home.start(self.body)

    def test_whole_path_rejected_before_lift(self):
        self.service.envelope['Y'] = (-250,20)
        with self.assertRaises(Exception): self.home.start(self.body)
        self.assertEqual(self.service.moves,[])
        self.invalidated.assert_not_called()

    def test_hamilton_rejection_explains_reach_and_workspace_without_preparing(self):
        # Historical rejection: keep its old reach policy independent of
        # today's deployment settings.
        self.home.params = lambda: {**PARAMS, 'extension_margin_mm':15.0}
        self.service.pose = dict(X=175.628,Y=-386.510,Z=36.224,Rz=-5.32)
        self.service.q = dict(J1=-2.375,J2=-69.642,J3=153.917,J4=-89.595)
        self.service.envelope = {'X':(200,450),'Y':(-250,100),'Z':(70,400)}
        self.home.prepare = Mock()
        with self.assertRaisesRegex(TeachingError, '389.7 mm.*383.0 mm') as caught:
            self.home.start(self.body)
        for expected in ('X=175.6','Y=-386.5','Z=36.2','No Home movement'):
            self.assertIn(expected, str(caught.exception))
        self.home.prepare.assert_not_called()
        self.invalidated.assert_not_called()
        self.assertFalse(self.runner.active)
        self.assertEqual(self.service.moves,[])

    def test_readiness_uses_snapshot_and_clears_when_pose_is_valid(self):
        self.home.params = lambda: {**PARAMS, 'extension_margin_mm':15.0}
        current = {**self.state,'pose_mm':dict(X=175.628,Y=-386.510,Z=36.224,Rz=-5.32),
                   'joints':dict(J1=-2.375,J2=-69.642,J3=153.917,J4=-89.595)}
        self.service.pose_mm = Mock(side_effect=AssertionError('No controller polling'))
        self.service.joints = Mock(side_effect=AssertionError('No controller polling'))
        result = self.home.public(current,self.hand)
        self.assertFalse(result['can_start'])
        self.assertIn('389.7 mm',result['blocker'])
        current.update(pose_mm=self.service.pose,joints=self.service.q)
        self.assertTrue(self.home.public(current,self.hand)['can_start'])
        self.assertEqual(self.service.moves,[])

    def test_stop_before_first_step(self):
        self.home.start(self.body)
        self.runner.name = 'researcher_home'
        self.home.stop()
        with self.assertRaises(Exception): self.runner.finish()
        self.assertEqual(self.service.moves,[])

    def test_stop_does_not_cancel_other_sequence(self):
        self.runner.active,self.runner.name = True,'calibration'
        self.home.stop()
        self.assertFalse(self.runner.cancelled)

    def test_uncertain_motion_stops_without_retry(self):
        self.home.start(self.body)
        self.service.robot.set_sys_var_i=Mock(side_effect=TimeoutError('Unconfirmed queue handshake'))
        with self.assertRaises(Exception): self.runner.finish()
        self.assertEqual(self.service.robot.set_sys_var_i.call_count,1)
        self.assertEqual(self.service.robot.calls,[])
        self.assertEqual(self.service.robot.program_state,'stopped')

    def test_lower_start_queues_lift_then_rotates_then_crosses_and_lowers(self):
        self.service.pose['Z']=150.
        self.home.start(self.body)
        self.assertTrue(self.runner.finish()['ok'])
        calls=self.service.robot.calls
        self.assertEqual(len(calls),3)
        self.assertEqual([c[1] for c in calls],[137]*3)
        self.assertAlmostEqual(calls[0][0][2],300.)
        self.assertAlmostEqual(calls[0][0][5],84.64,places=2)
        self.assertAlmostEqual(calls[1][0][5],-3.88,places=2)
        self.assertTrue(self.rotations)

    def test_older_lua_rejected_before_preparation(self):
        self.service.robot=Controller(self.service,legacy=130)
        self.home.prepare=Mock()
        with self.assertRaises(TeachingError):self.home.start(self.body)
        self.home.prepare.assert_not_called()
        self.assertEqual(self.service.robot.jobs,[])

    def test_stopped_published_program_is_verified_after_preparation(self):
        self.service.robot.program_state='stopped'
        self.state.update(control_mode={'mode':'manual'},enabled=False,program_state={'state':'stopped'})
        def prepare(run,service):
            self.assertEqual(service.moves,[])
            self.assertEqual(self.rotations,[])
            service.robot.program_state='running'
            self.state.update(control_mode={'mode':'auto'},enabled=True,program_state={'state':'running'})
        self.home.prepare=Mock(side_effect=prepare)
        self.home.start(self.body)
        self.assertTrue(self.runner.finish()['ok'])
        self.home.prepare.assert_called_once()

    def test_wrong_program_after_initialization_blocks_every_home_leg(self):
        self.service.robot=Controller(self.service,legacy=130)
        self.service.robot.program_state='stopped'
        self.home.prepare=Mock(side_effect=lambda run,service:setattr(service.robot,'program_state','running'))
        self.home.start(self.body)
        with self.assertRaisesRegex(TeachingError,'Home requires'):
            self.runner.finish()
        self.assertEqual(self.rotations,[])
        self.assertEqual(self.service.moves,[])
        self.assertEqual(self.service.robot.jobs,[])

    def test_failed_initialization_does_not_claim_republication_needed(self):
        self.service.robot.program_state='stopped'
        self.home.prepare=Mock()
        self.home.start(self.body)
        with self.assertRaisesRegex(TeachingError,'not initialized'):
            self.runner.finish()
        self.assertEqual(self.rotations,[])
        self.assertEqual(self.service.moves,[])


if __name__ == '__main__':
    unittest.main()
