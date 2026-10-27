"""One confirmation, ordered instrument/arm execution, fake hardware only."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from command_batch import CommandBatch
from lacry_agent import TOOLS
from researcher_teaching import TeachingError
from test_home_then_calibration import CompoundTests


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = CompoundTests('test_complete_chain_one_yes_and_single_reservation')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        f.pose = deepcopy(f.home)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.failure = False
        self.on_hamilton = None
        self.ham = SimpleNamespace(session='one', settings=lambda:dict(timeout_s=3),
                                   preflight=Mock(return_value={}), run_action=self.hamilton)
        f.backend.instrument = self.ham
        self.engine = CommandBatch(f.agent, self.folder.name)
        f.agent.command_batch_workflow = lambda:self.engine

    def hamilton(self, action, stopped, progress):
        f = self.fixture
        f.calls.append('Hamilton '+action)
        progress({})
        if self.on_hamilton:
            self.on_hamilton()
        if self.failure:
            raise TeachingError('Hamilton completion uncertain')
        return dict(ok=not stopped())

    def finish(self, commands):
        plan = self.engine.propose(commands)
        self.assertTrue(plan['executable'], plan)
        self.assertFalse(self.fixture.calls)
        self.fixture.agent.confirm(dict(ready=True,plan_id=plan['id']))
        result = self.fixture.finish()
        self.assertIsNone(self.fixture.agent.pending)
        return result

    def test_hamilton_then_arm_one_confirmation(self):
        state = self.finish(['hamilton_self_calibration','arm_full_calibration'])
        self.assertTrue(state['ok'], state)
        self.assertEqual(self.fixture.calls,['Hamilton self_calibration','Calibrate','Align','Descend','Grip','Lift','Home'])
        self.assertEqual(self.fixture.agent.run_meta['total_steps'],7)
        record = json.loads(next(Path(self.folder.name).glob('*/workflow.json')).read_text())
        self.assertEqual(record['status'],'completed')
        with self.assertRaises(TeachingError):
            self.fixture.agent.confirm(dict(ready=True,plan_id=record['plan']['id']))

    def test_preserves_reverse_order_and_multiple_instrument_commands(self):
        state = self.finish(['arm_full_calibration','hamilton_initialize','hamilton_self_calibration'])
        self.assertTrue(state['ok'], state)
        self.assertEqual(self.fixture.calls,['Calibrate','Align','Descend','Grip','Lift','Home','Hamilton initialize','Hamilton self_calibration'])

    def test_hamilton_only_batch(self):
        state = self.finish(['hamilton_initialize','hamilton_self_calibration'])
        self.assertTrue(state['ok'],state)
        self.assertEqual(self.fixture.calls,['Hamilton initialize','Hamilton self_calibration'])

    def test_self_calibration_batch_does_not_require_channel_supplies(self):
        plan=self.engine.propose(['hamilton_self_calibration','arm_full_calibration'])
        requirements=' '.join(plan['requirements'])
        self.assertIn('Self-calibration does not require a tip rack',requirements)
        self.assertNotIn('load a full compatible tip rack',requirements)

    def test_full_calibration_batch_loads_rack_after_self_calibration(self):
        plan=self.engine.propose(['hamilton_full_calibration'])
        self.assertIn('wait until self-calibration finishes',' '.join(plan['requirements']))

    def test_failed_hamilton_never_starts_arm(self):
        self.failure = True
        state = self.finish(['hamilton_self_calibration','arm_full_calibration'])
        self.assertFalse(state['ok'])
        self.assertEqual(self.fixture.calls,['Hamilton self_calibration'])

    def test_arm_failure_never_starts_following_hamilton(self):
        self.fixture.fail = 'Descend'
        state = self.finish(['arm_full_calibration','hamilton_self_calibration'])
        self.assertFalse(state['ok'])
        self.assertEqual(self.fixture.calls,['Calibrate','Align','Descend'])

    def test_stop_and_reservation_cover_entire_batch(self):
        def stop():
            self.assertFalse(self.fixture.run.start('intruder',lambda run:dict(ok=True))['ok'])
            self.fixture.agent.stop()
        self.on_hamilton = stop
        state = self.finish(['hamilton_self_calibration','arm_full_calibration'])
        self.assertFalse(state['ok'])
        self.assertEqual(self.fixture.calls,['Hamilton self_calibration'])

    def test_session_change_blocks_before_hardware(self):
        plan = self.engine.propose(['hamilton_self_calibration','arm_full_calibration'])
        self.ham.session = 'changed'
        with self.assertRaisesRegex(TeachingError,'session'):
            self.fixture.agent.confirm(dict(ready=True,plan_id=plan['id']))
        self.assertFalse(self.fixture.calls)

    def test_unavailable_hamilton_does_not_start_partial_batch(self):
        self.ham.preflight.side_effect = TeachingError('Hamilton disconnected')
        plan = self.engine.propose(['hamilton_self_calibration','arm_full_calibration'])
        self.assertFalse(plan['executable'])
        with self.assertRaises(TeachingError):
            self.fixture.agent.confirm(dict(ready=True,plan_id=plan['id']))
        self.assertFalse(self.fixture.calls)

    def test_tool_returns_single_complete_pending_plan(self):
        self.assertIn('plan_command_batch',{tool['name'] for tool in TOOLS})
        result, error = self.fixture.agent._run_tool('plan_command_batch',dict(commands=['hamilton_self_calibration','arm_full_calibration']))
        self.assertFalse(error, result)
        self.assertEqual(len(self.fixture.agent.pending['steps']),7)
        self.assertFalse(self.fixture.calls)

    def test_repeated_arm_pickup_and_unknown_action_rejected(self):
        for commands in (['arm_full_calibration']*2, ['hamilton_reset'], 'hamilton_initialize'):
            with self.assertRaises(TeachingError):
                self.engine.propose(commands)
        self.assertFalse(self.fixture.calls)


if __name__ == '__main__':
    unittest.main()
