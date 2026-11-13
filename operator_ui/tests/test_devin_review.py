"""Devin handoff tests: fake subprocess only, no usage or hardware."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import Flask
from developer_diagnostics import scrub
from developer_dsl import EXAMPLE
from devin_review import DevinReview, register_devin_review, capture_home_preflight


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.worker = DevinReview(Path(self.tmp.name), scrub, lambda: 'fake-devin.exe', timeout=.02)
        self.failure = dict(id='failure1', error='Delayed parking', sequence='offline',
            evidence={'source': 'raise RuntimeError("late")'})

    def test_proposal_is_text_and_no_shell_or_credentials(self):
        seen = {}
        def launch(args, **kwargs):
            seen.update(args=args, kwargs=kwargs)
            seen['prompt'] = Path(args[args.index('--prompt-file')+1]).read_text(encoding='utf-8')
            seen['config'] = json.loads(Path(args[args.index('--config')+1]).read_text())
            kwargs['stdout'].write(b'Proposed change only')
            return Mock(poll=lambda: 0, returncode=0)
        with patch('devin_review.subprocess.Popen', side_effect=launch), patch.dict('os.environ', {'SECRET_API_KEY':'not-for-devin'}):
            self.worker.start(self.failure, EXAMPLE)
            self.worker.thread.join(3)
        result = self.worker.snapshot()
        self.assertEqual(result['state'], 'complete')
        self.assertFalse(result['applied'])
        self.assertFalse(seen['kwargs']['shell'])
        self.assertEqual(seen['kwargs']['stdin'], subprocess.DEVNULL)
        self.assertNotIn('SECRET_API_KEY', seen['kwargs']['env'])
        self.assertIn('intended_dsl', seen['prompt'])
        self.assertIn('exec', seen['config']['permissions']['deny'])
        self.assertIn('mcp__*', seen['config']['permissions']['deny'])
        self.assertNotIn('--cloud', seen['args'])
        self.assertEqual(list(Path(self.tmp.name).glob('*.prompt.txt')), [])

    def test_timeout_kills_worker_without_retry(self):
        process = Mock(poll=lambda: None)
        with patch('devin_review.subprocess.Popen', return_value=process) as launch:
            self.worker.start(self.failure, EXAMPLE)
            self.worker.thread.join(3)
        self.assertEqual(self.worker.snapshot()['state'], 'error')
        self.assertIn('timed out', self.worker.snapshot()['error'])
        process.kill.assert_called_once()
        launch.assert_called_once()

    def test_failure_keeps_cli_explanation(self):
        def launch(args, **kwargs):
            kwargs['stdout'].write(b'Workspace not trusted')
            return Mock(poll=lambda: 1, returncode=1)
        with patch('devin_review.subprocess.Popen', side_effect=launch):
            self.worker.start(self.failure, EXAMPLE)
            self.worker.thread.join(3)
        self.assertEqual(self.worker.snapshot()['state'], 'error')
        self.assertIn('not trusted', self.worker.snapshot()['response'])

    def test_missing_cli_invalid_source_and_duplicate_job(self):
        self.worker.resolve_cli = lambda: None
        with self.assertRaises(FileNotFoundError):
            self.worker.start(self.failure, EXAMPLE)
        with self.assertRaises(ValueError):
            self.worker.start(self.failure, 'exec("bad")')
        self.worker.resolve_cli = lambda: 'fake'
        self.worker.job = {'state':'running'}
        with self.assertRaises(RuntimeError):
            self.worker.start(self.failure, EXAMPLE)

    def test_stale_cross_origin_and_remote_requests_never_start(self):
        app = Flask(__name__)
        diagnostics = Mock(snapshot=lambda: self.failure)
        register_devin_review(app, diagnostics, scrub, self.worker)
        client = app.test_client()
        headers = {'X-Cephla-View':'developer'}
        with patch.object(self.worker, 'start') as start:
            self.assertEqual(client.post('/developer/api/dsl/devin', json={'failure_id':'old'}, headers=headers).status_code, 409)
            self.assertEqual(client.post('/developer/api/dsl/devin', json={}, headers={**headers,'Origin':'https://other.test'}).status_code, 403)
            self.assertEqual(client.post('/developer/api/dsl/devin', json={}, headers=headers, environ_overrides={'REMOTE_ADDR':'192.168.1.2'}).status_code, 403)
            start.assert_not_called()

    def test_restart_marks_job_interrupted(self):
        (Path(self.tmp.name)/'latest.json').write_text(json.dumps({'state':'running'}))
        worker = DevinReview(self.tmp.name, scrub)
        self.assertEqual(worker.snapshot()['state'], 'interrupted')
        self.assertEqual(scrub('cog_secret ghp_secret github_pat_secret'), '[REDACTED] [REDACTED] [REDACTED]')

    def test_cloud_repair_without_dsl_verifies_pushed_branch(self):
        commands = []
        def git(args, **kwargs):
            if args[1] == 'rev-parse': return 'b' * 40
            if args[1] == 'status': return ''
            return 'a' * 40 + '\trefs/heads/' + self.worker.job['branch']
        def launch(args, **kwargs):
            commands.append(args)
            report = dict(outcome='pushed', branch=self.worker.job['branch'],
                commit='a'*40, tests_passed=True, tests=['offline regression: passed'])
            kwargs['stdout'].write(('```json\n' + json.dumps(report) + '\n```').encode())
            return Mock(poll=lambda: 0, returncode=0)
        with patch('devin_review.subprocess.check_output', side_effect=git), patch('devin_review.subprocess.Popen', side_effect=launch):
            self.worker.start(self.failure, '', repair=True)
            self.worker.thread.join(3)
        job = self.worker.snapshot()
        self.assertEqual(job['state'], 'pushed')
        self.assertTrue(job['remote_verified'])
        self.assertFalse(job['tests_verified'])
        self.assertFalse(job['applied'])
        self.assertIn('--cloud', commands[0])
        with self.assertRaises(RuntimeError): self.worker.start(self.failure, '', repair=True)

    def test_mismatched_remote_or_test_report_never_claims_pushed(self):
        self.worker.job = dict(branch='lacry/repair/test', mode='repair')
        report = dict(outcome='pushed', branch='lacry/repair/test', commit='a'*40,
                      tests_passed=True, tests=['test: passed'])
        with patch('devin_review.subprocess.check_output', return_value='b'*40):
            state, _ = self.worker._verify_repair('```json\n' + json.dumps(report) + '\n```')
        self.assertEqual(state, 'cloud_unknown')
        report['branch'] = 'main'
        with patch('devin_review.subprocess.check_output') as git:
            state, _ = self.worker._verify_repair('```json\n' + json.dumps(report) + '\n```')
            git.assert_not_called()
        self.assertEqual(state, 'cloud_unknown')

    def test_preflight_captures_refusal_without_motion(self):
        from types import SimpleNamespace
        from developer_diagnostics import DeveloperDiagnostics
        diagnostics = DeveloperDiagnostics(Path(self.tmp.name)/'diagnostics')
        service = Mock(envelope={'Z':[100,400]})
        service.status.return_value = {'connected':True, 'enabled':False}
        home = Mock()
        home.public.return_value = {'can_start':False,'blocker':'Wrist limit exceeded'}
        home.target.return_value = ({'X':1}, 'target-id')
        hand = Mock()
        result = capture_home_preflight(diagnostics, service, home, hand, lambda: {})
        self.assertFalse(result['movement_started'])
        self.assertEqual(diagnostics.snapshot()['event'], 'home_preflight_failed')
        home.start.assert_not_called()
        self.assertEqual([call[0] for call in service.method_calls], ['status'])

    def test_auto_listener_does_not_submit_when_disabled(self):
        with patch.object(self.worker, 'start') as start:
            self.worker.on_failure(self.failure)
            start.assert_not_called()
        self.worker.configure(True)
        import threading
        called = threading.Event()
        with patch.object(self.worker, 'start', side_effect=lambda *a, **k: called.set()) as start:
            self.worker.on_failure(self.failure)
            self.assertTrue(called.wait(2))
            self.assertTrue(start.call_args.kwargs['repair'])

    def test_unknown_cloud_outcome_blocks_further_jobs(self):
        self.worker.job = dict(state='cloud_unknown')
        with self.assertRaises(RuntimeError): self.worker.start(self.failure, '')


if __name__ == '__main__':
    unittest.main()
