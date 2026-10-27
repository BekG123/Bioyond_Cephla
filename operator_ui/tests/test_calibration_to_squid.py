"""One confirmed Home/pickup/Squid workflow. Fake hardware only."""
from copy import deepcopy
import unittest
from unittest.mock import Mock
import test_home_then_calibration as compound_fixture
import test_squid_handling as travel_fixture
from researcher_teaching import TeachingError


class PickupToSquidTests(unittest.TestCase):
    enable_transport = compound_fixture.CompoundTests.enable_transport
    finish = compound_fixture.CompoundTests.finish
    home_motion = compound_fixture.CompoundTests.home_motion
    confirm = compound_fixture.CompoundTests.confirm

    def setUp(self):
        compound_fixture.CompoundTests.setUp(self)
        self.backend.pickup_to_scope_plan.return_value = dict(actions=['move_scope'],
            steps=[dict(kind='travel', label='Move to Squid')], requirements=['Loaded Squid route clear'])
        def execute(run, step, plan):
            if plan['actions'] == ['move_home']:
                return self.home_motion(run, step, plan)
            self.calls.append('Squid')
            return dict(ok=True)
        self.backend.execute_step.side_effect = execute

    def propose(self):
        return self.agent.propose(['move_home','full_calibration','move_scope'])

    def test_entire_chain_after_one_confirmation(self):
        plan = self.propose()
        self.assertEqual(len(plan['steps']),8)
        self.assertEqual(self.calls,[])
        state = self.confirm(plan)
        self.assertTrue(state['ok'],state)
        self.assertEqual(self.calls,['Initial Home','Calibrate','Align','Descend','Grip','Lift','Home','Squid'])
        self.assertEqual(len(state['done']),8)
        self.assertEqual(self.agent.run_meta['total_steps'],8)
        self.assertIn('no release or imaging',state['message'])
        self.backend.verify_confirmation.assert_any_call(plan['scope_continuation'],prepared=True)
        self.assertFalse(self.run.reserved)

    def test_calibration_to_squid_without_initial_home(self):
        plan = self.agent.propose(['full_calibration','move_scope'])
        self.assertEqual(len(plan['steps']),7)
        self.assertTrue(self.confirm(plan)['ok'])
        self.assertEqual(self.calls,['Calibrate','Align','Descend','Grip','Lift','Home','Squid'])

    def test_pickup_failure_prevents_squid(self):
        self.fail='Grip'
        state=self.confirm(self.propose())
        self.assertFalse(state['ok'])
        self.assertEqual(self.calls,['Initial Home','Calibrate','Align','Descend','Grip'])

    def test_stop_after_loaded_home_prevents_squid(self):
        self.after=lambda action:self.pickup.stop() if action=='Home' else None
        self.assertFalse(self.confirm(self.propose())['ok'])
        self.assertNotIn('Squid',self.calls)

    def test_changed_route_before_confirmation_blocks_entire_chain(self):
        plan=self.propose()
        self.backend.verify_pickup_to_scope_plan.side_effect=TeachingError('Route changed')
        with self.assertRaisesRegex(TeachingError,'Route changed'):
            self.agent.confirm(dict(ready=True,plan_id=plan['id']))
        self.assertEqual(self.calls,[])

    def test_wrong_post_pickup_pose_or_grip_never_starts_squid(self):
        verify=self.backend.verify_confirmation
        def check(plan,prepared):
            if plan['actions']==['move_scope']:
                raise TeachingError('Post-pickup grip changed')
        verify.side_effect=check
        state=self.confirm(self.propose())
        self.assertFalse(state['ok'])
        self.assertEqual(state['step'],'Move to Squid')
        self.assertNotIn('Squid',self.calls)

    def test_squid_failure_reports_stage_and_never_retries(self):
        execute=self.backend.execute_step.side_effect
        self.backend.execute_step.side_effect=lambda run,step,plan: (
            dict(ok=False,error='Unconfirmed descent') if plan['actions']==['move_scope']
            else execute(run,step,plan))
        state=self.confirm(self.propose())
        self.assertFalse(state['ok'])
        self.assertEqual(state['step'],'Move to Squid')
        self.assertEqual(len(state['done']),7)
        self.assertEqual(state['results'][-1]['sequence'],'pickup_to_scope')


class ActualSquidContinuationTests(unittest.TestCase):
    setUp = travel_fixture.SquidHandlingTests.setUp
    stop = travel_fixture.SquidHandlingTests.stop
    jaw = travel_fixture.SquidHandlingTests.jaw

    def test_template_and_callback_use_real_planner_and_lua(self):
        plan=self.backend.pickup_to_scope_plan()
        self.assertFalse(self.s.robot.calls)
        self.backend.verify_pickup_to_scope_plan(plan)
        callback=self.agent._pickup_scope_callbacks(plan)
        self.assertTrue(callback['start']()['ok'])
        self.assertTrue(self.run.finish()['ok'])
        self.assertEqual([c[1] for c in self.s.robot.calls],[137,137,137,10])
        self.assertFalse(self.s.grips)

    def test_actual_changed_jaw_rejects_before_queue(self):
        plan=self.backend.pickup_to_scope_plan()
        self.e1=5.
        with self.assertRaisesRegex(TeachingError,'gripper changed'):
            self.agent._pickup_scope_callbacks(plan)['start']()
        self.assertFalse(self.s.robot.calls)

    def test_changed_evidence_does_not_dispatch(self):
        plan=self.backend.pickup_to_scope_plan()
        plan['steps'][0]['sources']['scope_speed_policy']='stale'
        with self.assertRaisesRegex(TeachingError,'route or settings changed'):
            self.agent._pickup_scope_callbacks(plan)['start']()
        self.assertFalse(self.s.robot.calls)


if __name__=='__main__':unittest.main()
