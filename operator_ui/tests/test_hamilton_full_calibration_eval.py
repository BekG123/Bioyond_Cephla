"""Your implementation workspace: offline full-calibration handshake evaluation.

Implement STEP 1 through STEP 5 below, then remove the unittest.skip decorator.
This is a scaffold, not a completed evaluation. No model or hardware is needed.

Run from the repository root:
  .venv-realsense/Scripts/python.exe -B -m unittest discover -s operator_ui/tests -p test_hamilton_full_calibration_eval.py -v

References:
  test_hamilton_prep.py                 Existing Device, Events, and config fixture
  test_hamilton_calibration_loading.py  Unloading event and assertion examples
  ../hamilton_prep.py                   Production code you are evaluating

The baseline Device publishes a channel Pass immediately. Override that behavior:
your fake must publish a NEW Pass only after the simulated cleanup completes.
The existing fixture uses a synthetic 300 uL/site-7 setup; it does not change the
real instrument's selected rack. Model a different rack consistently if needed.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_hamilton_prep as fixtures


class RunLog:
    """Permanent JSONL evidence, separate from the fixture's temporary journals."""

    def __init__(self, scenario):
        self.run_id = uuid4().hex
        root = Path(__file__).resolve().parents[1] / 'reports/evals/hamilton_handshake'
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / f'{self.run_id}.jsonl'
        self.record('run_started', scenario=scenario, implementation='scaffold')

    def record(self, kind, **data):
        row = dict(run_id=self.run_id, at=datetime.now(timezone.utc).isoformat(),
                   kind=kind, **data)
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')


class CalibrationDevice(fixtures.Device):
    def __init__(self, log, parked_after_checks=5):
        super().__init__()
        self.log = log
        self.parked_after_checks = parked_after_checks
        self.parking_checks = 0
        self.cleanup_started = False
        self.operator_confirmed = False
        self.cleanup_completed = False

    def emit(self, name, payload, source='Unloads'):
        event = dict(code='generic', data=json.dumps(
            dict(Name=name, Payload=payload, Source=source)))
        self.events.append(('instinctevents', event))
        self.log.record('fake_event', event=event)

    def __call__(self, method, path, body=None):
        self.log.record('request', method=method, path=path, body=deepcopy(body))
        try:
            result = self.respond(method, path, body)
        except Exception as error:
            self.log.record('request_error', message=str(error))
            raise
        self.log.record('response', method=method, path=path, result=result)
        return result

    def respond(self, method, path, body):
        # STEP 1: Preserve the baseline's read-only status/configuration replies
        # and self-calibration behavior using super().__call__ where appropriate.
        # Intercept channel-height-squeeze: emit a native tiprack dialog instead
        # of letting the baseline immediately create a passing channel result.
        # After close-labware-view, emit Loads/ShowDialog. On begin-load emit
        # Loads/Status/PrepareLoadingFinished; on end-load emit LoadingFinished,
        # then Unloads/ShowDialog. Use fixed fake dialog IDs.
        # Record intercepted commands in self.calls too (without double logging
        # calls delegated to the base Device).
        #
        # STEP 2: On begin-cleanup set cleanup_started=True, then emit
        # Unloads/Status/UnloadStarted. Before cleanup, preserve normal readiness
        # so preflight can pass. During cleanup return False for the first five
        # is-parked checks, then True. Return has-tips=False for this first case.
        #
        # STEP 3: On end-cleanup require operator_confirmed and verified parking.
        # Emit UnloadFinished, call self.finish_channel() to publish a fresh Pass,
        # emit a native finished event, and mark cleanup_completed=True.
        # Unknown endpoints must raise, never fall back to real HTTP.
        raise NotImplementedError('Implement the fake calibration lifecycle here.')


class FullCalibrationEval(unittest.TestCase):
    @unittest.skip('Implementation exercise: complete STEPS 1-5, then remove this skip.')
    def test_delayed_parking(self):
        log = RunLog('full_calibration_delayed_parking')
        fixture = fixtures.PrepTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fake = CalibrationDevice(log, parked_after_checks=5)
        adapter = fixture.adapter
        adapter.request = fake
        fixture.settings['timeout_s'] = 10
        fixture.config.write_text(json.dumps(fixture.settings))

        def simulated_operator(state):
            log.record('progress', state=deepcopy(state))
            # STEP 4: Inspect adapter.prompt and log it before responding.
            # For the cleanup prompt assert fake.parking_checks > 5, then set
            # fake.operator_confirmed=True. Respond once using
            # adapter.respond(prompt['id'], 'Ok'). Answer self-calibration and
            # rack-selection prompts explicitly too. This is a simulated human,
            # not permission for production code to auto-answer real prompts.
            raise NotImplementedError('Implement the simulated operator here.')

        # Guard against accidental use of real HTTP or WebSocket connections.
        with patch.object(adapter.opener, 'open', side_effect=AssertionError('Real HTTP forbidden')), \
             patch('socket.create_connection', side_effect=AssertionError('Real socket forbidden')):
            try:
                result = adapter.run_action('full_calibration', progress=simulated_operator)
                # STEP 5: Assert both calibration steps completed; no abort;
                # begin-cleanup/end-cleanup each occurred once and in order;
                # readiness preceded the prompt and operator confirmation;
                # cleanup completed and the result contains the NEW channel Pass.
                # Do not rely on result['ok'] alone. Score the recorded sequence.
                raise NotImplementedError('Add outcome and sequence assertions here.')
            except Exception as error:
                log.record('evaluation_finished', passed=False, error=str(error))
                raise
            else:
                log.record('evaluation_finished', passed=True, result=result)


if __name__ == '__main__':
    unittest.main()
