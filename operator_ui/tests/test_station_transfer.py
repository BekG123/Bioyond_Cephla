"""Complete Hamilton pickup -> Home -> Squid through real Lua, fake hardware."""
from copy import deepcopy
import json
import unittest
from unittest.mock import Mock

import test_squid_handling as fixture
import squid_handling
from lacry_agent import SYSTEM, TOOLS


class StationTransferTests(unittest.TestCase):
    setUp = fixture.SquidHandlingTests.setUp
    stop = fixture.SquidHandlingTests.stop
    jaw = fixture.SquidHandlingTests.jaw

    def propose(self, actions):
        self.e1 = 5.
        self.agent._wait_review = Mock()
        return self.agent.propose(actions)

    def test_pickup_continues_past_home_to_squid_without_release(self):
        plan = self.propose(['retrieve_hamilton_to_squid'])
        self.assertFalse(self.s.robot.calls)
        self.backend.verify_confirmation(plan)
        self.agent.confirm(dict(ready=True, plan_id=plan['id']))
        result = self.run.finish()
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.s.grips, [3.7])
        self.assertEqual(self.agent._wait_review.call_count, 2)
        self.assertEqual([c[1] for c in self.s.robot.calls], [137]*3+[5]+[137]*3+[137]*3+[10])
        for key in ('X','Y','Z','Rz'):
            self.assertAlmostEqual(self.s.pose[key], squid_handling.SEATED[key], delta=.01)
        self.assertEqual(self.e1, 3.7)
        self.assertIn('keep the plate held', plan['summary'])

    def test_explicit_dropoff_releases_at_squid_and_returns_home(self):
        plan = self.propose(['hamilton_retrieve', 'squid_dropoff'])
        self.backend.verify_confirmation(plan)
        self.agent.confirm(dict(ready=True, plan_id=plan['id']))
        result = self.run.finish()
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.s.grips, [3.7, 5.])
        self.assertEqual([c[1] for c in self.s.robot.calls],
                         [137]*3+[5]+[137]*3+[137]*3+[10]+[5]+[137]*4)
        for key in ('X','Y','Z','Rz'):
            self.assertAlmostEqual(self.s.pose[key], self.path[0][key], delta=.01)

    def test_inspection_failure_stops_before_home_and_squid(self):
        plan = self.propose(['hamilton_retrieve', 'move_scope'])
        self.agent._wait_review.side_effect = [None, RuntimeError('Plate slipped')]
        result = self.agent._execute(self.run, plan)
        self.assertFalse(result['ok'])
        self.assertEqual(len(self.s.robot.calls), 4)
        self.assertNotIn('Move to the microscope using the tested approach', result['done'])

    def test_gripper_change_at_home_stops_onward_travel(self):
        plan = self.propose(['retrieve_hamilton_to_squid'])
        execute = self.backend.execute_step
        def changed(run, step, proposed):
            if step.get('transfer_phase') == 1:
                self.e1 = 5.
            return execute(run, step, proposed)
        self.backend.execute_step = changed
        result = self.agent._execute(self.run, plan)
        self.assertFalse(result['ok'])
        self.assertIn('Gripper feedback changed', result['error'])
        self.assertEqual(len(self.s.robot.calls), 7)
        self.assertEqual(self.s.grips, [3.7])

    def test_modified_second_phase_or_order_cannot_be_confirmed(self):
        plan = self.propose(['deliver_hamilton_to_squid'])
        for change in ('release', 'order', 'evidence'):
            bad = deepcopy(plan)
            if change == 'release':
                step = next(s for s in bad['phases'][1]['steps'] if s['kind']=='squid_jaw')
                step['target_e1'] = 7
            elif change == 'order':
                bad['steps'].reverse()
            else:
                bad['phases'][0]['handling_evidence'] = {}
            with self.assertRaises(Exception):
                self.backend.verify_confirmation(bad)
        self.assertFalse(self.s.robot.calls)

    def test_unready_or_wrong_jaws_cannot_plan_loaded_restart(self):
        self.e1 = 3.7
        with self.assertRaisesRegex(Exception,'jaws at 5'):
            self.agent.propose(['retrieve_hamilton_to_squid'])
        self.e1 = 5.
        self.s.robot.program_state = 'stopped'
        with self.assertRaisesRegex(Exception,'not ready'):
            self.agent.propose(['retrieve_hamilton_to_squid'])
        self.assertFalse(self.s.robot.calls)

    def test_chat_can_request_whole_transfer_without_motion(self):
        self.e1 = 5.
        response, error = self.agent._run_tool('propose_actions',
            dict(actions=['retrieve_hamilton_to_squid']))
        result = json.loads(response)
        self.assertFalse(error, result)
        self.assertTrue(result['awaiting_confirmation'])
        self.assertIn('Move to the microscope using the tested approach', result['steps'])
        self.assertFalse(self.s.robot.calls)
        enums = next(t for t in TOOLS if t['name']=='propose_actions')['input_schema']['properties']['actions']['items']['enum']
        self.assertIn('retrieve_hamilton_to_squid', enums)
        self.assertIn('deliver_hamilton_to_squid', enums)
        self.assertIn('omit the destination', SYSTEM)


if __name__ == '__main__':
    unittest.main()
