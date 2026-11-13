"""Transport fault injection using the isolated MCP venv and stdlib unittest."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lacry_mcp_server import Backend, BackendFailure
from lacry_recovery import RequestJournal


def reply(value):
    return io.BytesIO(json.dumps(value).encode())


def http_error(status, value):
    return HTTPError('http://127.0.0.1', status, 'fixture', {}, reply(value))


class ReconnectionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)
        token = self.path/'token';token.write_text('fixture')
        self.backend = Backend(token_path=token)
        self.backend.opener = Mock()
        self.sleep = patch('lacry_mcp_server.time.sleep').start()
        self.addCleanup(patch.stopall)

    def test_lost_reply_reconnects_with_same_id_and_recovers_without_invoking_twice(self):
        journal = RequestJournal(self.path/'requests.db')
        tools_run, requests = [], []
        def opened(req, timeout):
            body = json.loads(req.data);requests.append(body)
            cached = journal.begin(body['request_id'], body['name'], body['arguments'])
            if cached:
                return reply(cached[0])
            tools_run.append(body['name'])
            journal.finish(body['request_id'], dict(content='original result', is_error=False), 200)
            raise ConnectionResetError('reply lost after operation completed')
        self.backend.opener.open.side_effect = opened
        result = self.backend.call('call', dict(name='plan_workflow', arguments={'operations': ['x']}))
        self.assertEqual(tools_run, ['plan_workflow'])
        self.assertEqual(requests[0], requests[1])
        self.assertTrue(result['recovery']['receipt_replayed'])

    def test_connection_restored_before_first_dispatch(self):
        self.backend.opener.open.side_effect = [URLError('offline'), reply({'content': 'ready', 'is_error': False})]
        result = self.backend.call('call', dict(name='get_workflow_catalog', arguments={}))
        self.assertEqual(result['content'], 'ready')
        calls = self.backend.opener.open.call_args_list
        self.assertEqual(calls[0].args[0].data, calls[1].args[0].data)

    def test_busy_predispatch_retries_and_then_succeeds(self):
        self.backend.opener.open.side_effect = [http_error(409, dict(message='busy',
            recovery=dict(code='control_busy', retryable=True))), reply(dict(content='ready', is_error=False))]
        self.assertEqual(self.backend.call('call', dict(name='plan_workflow', arguments={}))['content'], 'ready')
        self.assertEqual(self.backend.opener.open.call_count, 2)

    def test_auth_schema_unknown_outcome_and_generic_conflict_are_not_retried(self):
        for status, code in [(403, 'authentication'), (400, 'invalid'), (409, 'outcome_unknown'),
                             (409, 'cancelled_by_stop'), (500, 'outcome_unknown'), (409, 'generic_busy')]:
            with self.subTest(status=status, code=code):
                self.backend.opener.open.reset_mock()
                self.backend.opener.open.side_effect = http_error(status, dict(message=code,
                    recovery=dict(code=code, retryable=True)))
                with self.assertRaises(BackendFailure):
                    self.backend.call('call', dict(name='plan_workflow', arguments={}))
                self.backend.opener.open.assert_called_once()

    def test_backend_unavailable_exhausts_budget_without_infinite_retry(self):
        self.backend.opener.open.side_effect = URLError('offline')
        with self.assertRaises(BackendFailure) as failure:
            self.backend.call('call', dict(name='plan_workflow', arguments={}))
        recovery = failure.exception.value['recovery']
        self.assertTrue(recovery['budget_exhausted'])
        self.assertFalse(recovery['retryable'])
        self.assertEqual(self.backend.opener.open.call_count, 6)
        ids = {json.loads(c.args[0].data)['request_id'] for c in self.backend.opener.open.call_args_list}
        self.assertEqual(ids, {recovery['request_id']})

    def test_malformed_reply_uses_same_receipt_id(self):
        self.backend.opener.open.side_effect = [io.BytesIO(b'{'), reply({'content': 'saved', 'is_error': False})]
        result = self.backend.call('call', dict(name='plan_workflow', arguments={}))
        self.assertEqual(result['content'], 'saved')
        self.assertEqual(len({c.args[0].data for c in self.backend.opener.open.call_args_list}), 1)

    def test_catalog_connection_recovers_without_any_tool_dispatch(self):
        self.backend.opener.open.side_effect = [URLError('offline'), reply({'tools': []})]
        self.assertEqual(self.backend.call('tools'), {'tools': []})
        self.assertTrue(all(c.args[0].data is None for c in self.backend.opener.open.call_args_list))


if __name__ == '__main__':
    unittest.main()
