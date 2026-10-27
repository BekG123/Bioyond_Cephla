"""Offline decision-audit coverage; no model or instrument connections."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_log import AuditLog
from lacry_decision_log import DecisionTrace, evidence
from lacry_agent import LacryAgent
from sequences import Runner


class DecisionLogTests(unittest.TestCase):
    def test_redaction_keeps_parameters_but_omits_secrets_images_and_thinking(self):
        source = dict(api_key='secret', message='sk-ant-example-secret',
            result=json.dumps(dict(password='nested-secret', tip_labware_id=273)),
            image=dict(type='base64', media_type='image/jpeg', data='image-bytes'),
            content=[dict(type='thinking', thinking='private-text'),
                     dict(type='tool_use', input=dict(tip_labware_id=1))])
        saved = evidence(source)
        text = json.dumps(saved)
        for value in ('nested-secret', 'sk-ant-example-secret', 'image-bytes', 'private-text'):
            self.assertNotIn(value, text)
        self.assertEqual(json.loads(saved['result'])['tip_labware_id'], 273)
        self.assertEqual(saved['content'][1]['input']['tip_labware_id'], 1)
        self.assertEqual(source['api_key'], 'secret')

    def test_missing_summary_is_not_invented_and_payload_is_not_mutated(self):
        sink = Mock(); client = Mock()
        client.complete.return_value = dict(content=[dict(type='tool_use', id='t', name='plan_hamilton', input={})])
        payload = dict(system='Original', messages=[], model='fixture')
        DecisionTrace(sink).complete(client, payload)
        self.assertEqual(payload['system'], 'Original')
        self.assertEqual(sink.call_args.kwargs['summary_status'], 'not_provided')

    def test_model_error_is_logged_without_retry(self):
        sink = Mock(); client = Mock()
        client.complete.side_effect = TimeoutError('offline timeout')
        with self.assertRaises(TimeoutError):
            DecisionTrace(sink).complete(client, dict(system='Original'))
        client.complete.assert_called_once()
        self.assertEqual(sink.call_args.args[0], 'lacry_decision_model_error')

    def test_bad_rack_decision_can_be_reconstructed_from_jsonl(self):
        with tempfile.TemporaryDirectory() as folder:
            audit = AuditLog(folder)
            runner = Runner(event_sink=audit.event)
            client = Mock()
            client.complete.return_value = dict(id='response-1', stop_reason='tool_use', content=[
                dict(type='text', text='I selected rack ID 1 for calibration.'),
                dict(type='tool_use', id='tool-1', name='plan_hamilton',
                     input=dict(action='full_calibration', tip_labware_id=1, tip_site=7))])
            agent = LacryAgent(Mock(), Mock(), lambda: runner, client=client)
            agent.public = Mock(return_value=dict(ok=True))
            agent.credentials.model = 'fixture'
            agent._conversation_state = Mock(return_value=dict(calibration_defaults=dict(tip_labware_id=273)))
            agent._run_tool = Mock(return_value=(json.dumps(dict(refused='Rack mismatch')), True))
            agent.send('Calibrate Hamilton with the 300 uL rack')
            rows = [json.loads(line) for line in audit.path.read_text().splitlines()]
            records = {row['event']: row for row in rows}
            request = records['lacry_decision_request']['payload']
            self.assertIn('273', request['system'])
            self.assertEqual(records['lacry_decision_tool_dispatch']['dispatched_arguments']['tip_labware_id'], 1)
            self.assertEqual(records['lacry_decision_tool_result']['tool_use_id'], 'tool-1')
            self.assertEqual(records['lacry_decision_response']['summary_status'], 'model_reported_not_verified')
            self.assertIn('Rack mismatch', records['lacry_decision_tool_result']['result'])
            self.assertEqual(len({row['decision_turn_id'] for row in rows}), 1)
            self.assertEqual(records['lacry_decision_finished']['pending_plan_id'], None)
            self.assertFalse(runner.active)
            agent.backend.execute_step.assert_not_called()


if __name__ == '__main__':
    unittest.main()
