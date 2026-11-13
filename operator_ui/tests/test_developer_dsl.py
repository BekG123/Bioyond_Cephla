"""Offline checks for DSL previews and failure evidence. No hardware imports."""
import ast
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import Flask
from developer_dsl import EXAMPLE, compile_dsl
from developer_diagnostics import (DeveloperDiagnostics, capture_failure,
                                   register_developer_diagnostics, source_to_dsl)


class CompilerTests(unittest.TestCase):
    def setUp(self):
        self.result = compile_dsl(EXAMPLE)
        # Only the compiler's trusted generated output is executed in this test.
        # The application has no exec/eval path.
        namespace = {}
        exec(compile(self.result['python'], '<offline-test>', 'exec'), namespace)
        self.decide = namespace['decide']

    def test_wait_ready_fault_and_budget(self):
        observation = dict(has_fault=False, parked=False, no_tips=True)
        count = 0
        for _ in range(5):
            decision, count = self.decide(observation, count)
            self.assertEqual(decision['kind'], 'wait')
        observation['parked'] = True
        self.assertEqual(self.decide(observation, count)[0]['kind'], 'ask')
        observation['no_tips'] = False
        self.assertEqual(self.decide(observation, count)[0]['kind'], 'wait')
        self.assertEqual(self.decide(observation, 119)[0]['kind'], 'pause')
        observation.update(has_fault=True, no_tips=True)
        self.assertEqual(self.decide(observation, 0)[0]['kind'], 'pause')

    def test_missing_observation_is_not_assumed_ready(self):
        with self.assertRaises(KeyError):
            self.decide({}, 0)

    def test_roundtrip_preserves_condition_tree_and_decisions(self):
        for condition in ['Machine.parked & no.tips',
                          '!(Machine.parked OR no.tips)',
                          'Machine.parked & (no.tips OR Machine.has_fault)']:
            result = compile_dsl(EXAMPLE.replace('Machine.parked & no.tips', condition))
            other = compile_dsl(result['roundtrip_dsl'])
            self.assertEqual(ast.dump(ast.parse(result['python'])), ast.dump(ast.parse(other['python'])))
            self.assertFalse(result['executable'])

    def test_rejects_code_injection_and_unsupported_syntax(self):
        for source in [EXAMPLE.replace('Machine.has_fault', '__import__("os").system("bad")'),
                       EXAMPLE.replace('WAIT', 'CALL Hamilton.abort()'),
                       EXAMPLE.replace('count = 0', 'count = 0;'),
                       EXAMPLE.replace('    FOR', '\tFOR'),
                       EXAMPLE.replace('        IF', '    IF', 1),
                       EXAMPLE.replace('count >= 120', 'count >= True')]:
            with self.assertRaises(ValueError):
                compile_dsl(source)


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.diagnostics = DeveloperDiagnostics(self.folder)
        self.runner = SimpleNamespace(snapshot=lambda: dict(state='idle', result=None))
        self.credentials = SimpleNamespace(ready=lambda: True, model='offline-model')
        self.model = Mock()
        self.model.complete.return_value = dict(content=[dict(type='text', text='IF fault:\n    PAUSE = human.review')])
        app = Flask(__name__)
        from devin_review import DevinReview
        offline_devin = DevinReview(self.folder / 'devin', lambda value: str(value), resolve_cli=lambda: None)
        register_developer_diagnostics(app, self.diagnostics, lambda: self.runner,
                                       lambda: self.model, lambda: self.credentials, devin_worker=offline_devin)
        self.client = app.test_client()

    def test_capture_source_without_locals(self):
        hidden_secret = 'not-for-the-panel'
        try:
            raise RuntimeError('offline fault')
        except RuntimeError as error:
            evidence = capture_failure(error)
        self.assertEqual(evidence['location']['function'], 'test_capture_source_without_locals')
        self.assertNotIn('locals', evidence)
        self.assertTrue(evidence['source_sha256'])

    def test_failure_persists_and_success_does_not_erase_it(self):
        self.diagnostics.observe('sequence_finished', dict(sequence='test', state='error',
            result=dict(ok=False, error='Failure sk-ant-test-secret', failure_context=dict(
                source='def step():\n    if not parked:\n        raise RuntimeError("not ready")'))))
        self.diagnostics.observe('sequence_finished', dict(sequence='next', state='done', result=dict(ok=True)))
        saved = DeveloperDiagnostics(self.folder).snapshot()
        self.assertEqual(saved['sequence'], 'test')
        self.assertNotIn('sk-ant', saved['error'])
        self.assertIn('RAISE', saved['dsl'])
        self.assertNotIn('PAUSE', saved['dsl'])  # Never silently substitute failure semantics.

    def test_unknown_python_is_explicit(self):
        self.assertIn('REVIEW Python With', source_to_dsl('def f():\n    with lock:\n        move()'))
        self.assertIn('No source location', source_to_dsl(''))

    def test_translation_does_not_call_model(self):
        response = self.client.post('/developer/api/dsl/translate', json=dict(source=EXAMPLE))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['executable'])
        self.model.complete.assert_not_called()
        self.assertEqual(self.client.post('/developer/api/dsl/translate', json=[]).status_code, 400)

    def test_explanation_binds_failure_and_has_no_tools(self):
        self.diagnostics.observe('sequence_finished', dict(sequence='test', result=dict(ok=False, error='Not parked')))
        failure = self.diagnostics.snapshot()
        self.assertEqual(self.client.post('/developer/api/dsl/explain', json=dict(failure_id='old')).status_code, 409)
        response = self.client.post('/developer/api/dsl/explain', json=dict(failure_id=failure['id']))
        self.assertEqual(response.status_code, 200)
        payload = self.model.complete.call_args.args[0]
        self.assertNotIn('tools', payload)
        self.assertFalse(response.json['reviewed'])


if __name__ == '__main__':
    unittest.main()
