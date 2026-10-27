"""Toolkit discovery uses a fake instrument; no network or physical commands."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_hamilton_prep
from hamilton_toolkit import discover
from lacry_agent import LacryAgent, TOOLS
from researcher_teaching import TeachingError


class ToolkitTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_hamilton_prep.PrepTests('test_decoding_nested_json')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.adapter = self.fixture.adapter
        self.device = self.fixture.device

    def test_catalog_and_definition_are_read_only_and_not_execution_approval(self):
        result = discover(self.adapter, 1002)
        self.assertEqual(result['protocols'], [{'id': 1002, 'name': 'Water'}])
        self.assertEqual(result['selected_protocol']['definition'], self.device.definition)
        recipe = result['recipes'][0]
        self.assertEqual(recipe['name'], 'Water')
        self.assertEqual(recipe['remaining_cycles'], 3)
        self.assertTrue(recipe['inspected_definition_matches'])
        self.assertTrue(recipe['execution_requires_fresh_plan'])
        self.assertFalse(result['motion_started'])
        self.assertTrue(all(method == 'GET' for method, _, _ in self.device.calls))

    def test_saved_method_without_recipe_is_not_claimed_ready(self):
        self.fixture.settings['recipes'] = {}
        self.fixture.config.write_text(json.dumps(self.fixture.settings))
        result = discover(self.adapter)
        self.assertEqual(len(result['protocols']), 1)
        self.assertEqual(result['recipes'], [])
        self.assertIn('no liquid-handling recipe', result['message'])

    def test_changed_protocol_and_exhausted_inventory(self):
        self.device.definition['steps'] = ['different experiment']
        with patch.object(self.adapter, 'inventory_used', return_value=3):
            recipe = discover(self.adapter, 1002)['recipes'][0]
        self.assertFalse(recipe['inspected_definition_matches'])
        self.assertEqual(recipe['remaining_cycles'], 0)
        self.assertEqual(len(recipe['blockers']), 2)

    def test_cannot_supply_http_path_or_unknown_id(self):
        for invalid in ('../instruments/initialize', True, -1, 0):
            with self.assertRaises(TeachingError):
                discover(self.adapter, invalid)
        with self.assertRaises(TeachingError):
            discover(self.adapter, 99999)
        self.assertFalse(any(path == 'protocols/99999' for _, path, _ in self.device.calls))

    def test_disconnected_and_calibrating_skip_protocol_inspection(self):
        with patch.object(self.adapter, 'status', return_value={'connected': False}):
            self.assertFalse(discover(self.adapter, 1002)['catalog_available'])
        self.adapter.polling_trial = {'mode': 'reduced'}
        with patch.object(self.adapter, 'status', return_value={'connected': True}):
            self.assertFalse(discover(self.adapter, 1002)['catalog_available'])
        self.assertEqual(self.device.calls, [])

    def test_agent_dispatch_uses_toolkit_without_creating_plan(self):
        agent = LacryAgent(Mock(), Mock(), Mock(), client=Mock())
        agent.backend.instrument = self.adapter
        agent.pending = None
        reply, error = agent._run_tool('get_hamilton_toolkit', {'protocol_id': 1002})
        self.assertFalse(error)
        self.assertFalse(json.loads(reply)['awaiting_confirmation'])
        self.assertIsNone(agent.pending)
        schema = next(t for t in TOOLS if t['name'] == 'get_hamilton_toolkit')['input_schema']
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(set(schema['properties']), {'protocol_id'})


if __name__ == '__main__':
    unittest.main()
