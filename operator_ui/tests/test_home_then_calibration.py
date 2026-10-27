"""Home + pickup uses one confirmation/reservation. Fake controller only."""
from copy import deepcopy
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_lacry_pickup as pickup_tests
from lacry_agent import LacryAgent
from researcher_teaching import TeachingError


class CompoundTests(unittest.TestCase):
    enable_transport = pickup_tests.PickupTests.enable_transport
    finish = pickup_tests.PickupTests.finish

    def setUp(self):
        pickup_tests.PickupTests.setUp(self)
        self.enable_transport()
        self.backend = Mock()
        self.home = dict(X=289.97, Y=62.63, Z=248.02, Rz=-3.88)
        self.pose = dict(self.home, Z=200)
        self.backend.home.target.return_value = (self.home, 'saved-home')
        self.backend.healthy.side_effect = lambda **kw: dict(pose_mm=deepcopy(self.pose))
        self.backend.compile.return_value = dict(actions=['move_home'],
            steps=[dict(kind='travel', label='Return Home')], requirements=['Home route clear'])
        self.backend.execute_step.side_effect = self.home_motion
        self.agent = LacryAgent(self.backend, Mock(), lambda: self.run,
                               client=Mock(), classic_pickup=self.pickup)
        self.agent._needs_prepare = lambda plan: False

    def home_motion(self, run, step, plan):
        self.calls.append('Initial Home')
        self.pose = deepcopy(self.home)
        return dict(ok=True)

    def propose(self):
        return self.agent.propose(['move_home', 'full_calibration'])

    def confirm(self, plan):
        self.agent.confirm(dict(ready=True, plan_id=plan['id']))
        self.pickup.thread.join(5)
        self.assertFalse(self.pickup.thread.is_alive())
        return self.pickup.public()

    def test_complete_chain_one_yes_and_single_reservation(self):
        plan = self.propose()
        self.assertEqual(len(plan['steps']), 7)
        self.assertEqual(self.calls, [])
        state = self.confirm(plan)
        self.assertTrue(state['ok'], state)
        self.assertEqual(self.calls, ['Initial Home', 'Calibrate', 'Align', 'Descend', 'Grip', 'Lift', 'Home'])
        self.assertEqual(len(state['done']), 7)
        self.assertEqual(self.agent.run_meta['total_steps'], 7)
        self.assertFalse(self.run.reserved)
        self.assertIsNone(self.agent.pending)
        with self.assertRaises(TeachingError):
            self.agent.confirm(dict(ready=True, plan_id=plan['id']))

    def test_uncertain_initial_home_never_starts_calibration(self):
        self.backend.execute_step.side_effect = lambda *args: dict(ok=False, error='No completion')
        state = self.confirm(self.propose())
        self.assertFalse(state['ok'])
        self.assertEqual(state['step'], 'Return Home')
        self.assertEqual(self.calls, [])

    def test_success_flag_at_wrong_pose_does_not_start_calibration(self):
        self.backend.execute_step.side_effect = lambda *args: dict(ok=True)
        state = self.confirm(self.propose())
        self.assertFalse(state['ok'])
        self.assertIn('did not reach saved Home', state['error'])
        self.assertEqual(self.calls, [])

    def test_stale_home_confirmation_never_moves(self):
        plan = self.propose()
        self.backend.verify_confirmation.side_effect = TeachingError('Arm moved since preview')
        state = self.confirm(plan)
        self.assertFalse(state['ok'])
        self.assertEqual(self.calls, [])
        self.backend.execute_step.assert_not_called()

    def test_stop_and_competing_command_in_gap(self):
        entered, release = threading.Event(), threading.Event()
        def verify(**kw):
            if self.run.reserved:
                entered.set()
                self.assertTrue(release.wait(3))
            return dict(pose_mm=deepcopy(self.pose))
        self.backend.healthy.side_effect = verify
        plan = self.propose()
        self.agent.confirm(dict(ready=True, plan_id=plan['id']))
        self.assertTrue(entered.wait(3))
        self.assertFalse(self.run.start('intruder', lambda run: dict(ok=True))['ok'])
        self.run.request_stop()
        release.set()
        state = self.finish()
        self.assertFalse(state['ok'])
        self.assertEqual(self.calls, ['Initial Home'])

    def test_already_home_verifies_and_runs_without_redundant_move(self):
        self.pose = deepcopy(self.home)
        state = self.confirm(self.propose())
        self.assertTrue(state['ok'], state)
        self.backend.compile.assert_not_called()
        self.backend.execute_step.assert_not_called()
        self.assertEqual(self.calls, ['Calibrate', 'Align', 'Descend', 'Grip', 'Lift', 'Home'])
        self.assertFalse(state['results'][0]['motion_started'])

    def test_home_changed_after_proposal_blocks_calibration(self):
        self.pose = deepcopy(self.home)
        plan = self.propose()
        self.backend.home.target.return_value = (dict(self.home, X=300), 'changed')
        self.assertFalse(self.confirm(plan)['ok'])
        self.assertEqual(self.calls, [])

    def test_ik_fallback_finishes_record_before_calibration(self):
        self.backend.compile.side_effect = TeachingError('No station connection')
        connection = Mock()
        connection.propose.return_value = dict(dispatch='ik_home_return', requirements=['IK sweep clear'])
        def start(plan):
            self.run.start('researcher_home', lambda run: self.home_motion(run, {}, plan))
            return dict(ok=True, message='Returning Home'), 'attempt.json'
        connection.start.side_effect = start
        self.agent.reviewed_home = connection
        original = self.pickup._dispatch
        def dispatch(action):
            self.assertEqual(connection.finish.call_count, 1)
            return original(action)
        self.pickup._dispatch = dispatch
        state = self.confirm(self.propose())
        self.assertTrue(state['ok'], state)
        connection.finish.assert_called_once()

    def test_failed_record_write_stops_before_calibration(self):
        self.backend.compile.side_effect = TeachingError('No station connection')
        connection = Mock()
        connection.propose.return_value = dict(dispatch='ik_home_return', requirements=[])
        connection.start.side_effect = lambda plan: (
            self.run.start('researcher_home', lambda run: self.home_motion(run, {}, plan)), 'attempt')
        connection.finish.side_effect = OSError('disk full')
        self.agent.reviewed_home = connection
        self.assertFalse(self.confirm(self.propose())['ok'])
        self.assertEqual(self.calls, ['Initial Home'])

    def test_actual_ik_home_and_lua_wrapper_complete_before_pickup(self):
        import json
        import test_ik_home as ik_fixtures
        fixture = ik_fixtures.IKHomeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.runner = self.run
        self.agent.reviewed_home = fixture.connection
        self.backend.home = fixture.home
        self.backend.healthy.side_effect = lambda **kw: fixture.service.status()
        self.backend.compile.side_effect = TeachingError('No station connection')
        original = self.pickup._dispatch
        def dispatch(action):
            if action == 'Calibrate':
                records = list(fixture.connection.folder.glob('*.json'))
                self.assertEqual(len(records), 1)
                record = json.loads(records[0].read_text())
                self.assertEqual(record['status'], 'completed')
                self.assertTrue(record['sequence']['result']['ok'])
                self.assertTrue(fixture.service.robot.calls)
                for axis, value in fixture.home.target()[0].items():
                    self.assertAlmostEqual(fixture.service.pose_mm()[axis], value, places=3)
            return original(action)
        self.pickup._dispatch = dispatch
        state = self.confirm(self.propose())
        self.assertTrue(state['ok'], state)
        self.assertEqual(self.calls, ['Calibrate', 'Align', 'Descend', 'Grip', 'Lift', 'Home'])

    def test_model_summary_cannot_add_unqueued_steps(self):
        plan = self.agent.propose(['move_home'], summary='Home then full calibration')
        self.assertNotIn('calibration', plan['summary'])
        reply = self.agent._ground_plan_reply('Both moves are ready. Reply Yes.')
        self.assertNotIn('calibration', reply)
        self.assertIn('Return Home', reply)

    def test_chat_builds_whole_compound_then_yes_runs_it(self):
        self.agent.credentials.model = 'fixture'
        self.agent.client.complete.side_effect = [
            dict(stop_reason='tool_use', content=[dict(type='tool_use', id='combined',
                name='propose_actions', input=dict(actions=['move_home', 'full_calibration']))]),
            dict(content=[dict(type='text', text='I will do both.')])]
        self.agent.send('Return Home, then run full calibration')
        self.assertEqual(self.calls, [])
        self.assertIn('Descent', self.agent.transcript[-1]['text'])
        self.agent.send('Yes')
        self.assertTrue(self.finish()['ok'])
        self.assertEqual(self.calls[0:2], ['Initial Home', 'Calibrate'])


if __name__ == '__main__':
    unittest.main()
