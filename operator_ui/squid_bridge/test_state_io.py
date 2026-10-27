"""Real Windows file-sharing checks and native writer tests; no hardware."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.getcwd())  # Squid software cwd for the native-writer check.
import state_io


def sharing_error(code=5):
    error = PermissionError('fixture: file temporarily held')
    error.winerror = code
    return error


class StateIOTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'run.json'
        state_io.atomic_write_json(self.path, {'status':'running'})

    def test_reader_remains_valid_while_file_is_replaced(self):
        with state_io.shared_reader(self.path) as reader:
            state_io.atomic_write_json(self.path, {'status':'ended'})
            self.assertEqual(json.loads(reader.read()), {'status':'running'})
            self.assertEqual(state_io.read_json(self.path), {'status':'ended'})

    def test_transient_error_retries_identical_file_only(self):
        replace = state_io.replace_file
        payloads = []
        def attempt(source, target):
            payloads.append(Path(source).read_bytes())
            if len(payloads) < 3:
                raise sharing_error(32 if len(payloads)==1 else 5)
            replace(source, target)
        with patch.object(state_io, 'replace_file', side_effect=attempt) as mocked, \
                patch.object(state_io.time, 'sleep') as sleep:
            state_io.atomic_write_json(self.path, {'status':'ended', 'run_id':'same-job'})
        self.assertEqual(mocked.call_count, 3)
        self.assertEqual(len(set(payloads)), 1)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [.02,.04])
        self.assertEqual(state_io.read_json(self.path)['run_id'], 'same-job')

    def test_persistent_lock_is_bounded_and_keeps_previous_record(self):
        with patch.object(state_io, 'replace_file', side_effect=sharing_error()) as mocked, \
                patch.object(state_io.time, 'sleep') as sleep:
            with self.assertRaises(PermissionError):
                state_io.atomic_write_json(self.path, {'status':'ended'})
        self.assertEqual(mocked.call_count, 7)
        self.assertAlmostEqual(sum(c.args[0] for c in sleep.call_args_list), .7)
        self.assertEqual(state_io.read_json(self.path)['status'], 'running')
        self.assertEqual(list(self.path.parent.glob('.run-*.tmp')), [])

    def test_other_io_errors_and_invalid_json_are_not_retried(self):
        with patch.object(state_io, 'replace_file', side_effect=OSError('disk failed')) as mocked, \
                patch.object(state_io.time, 'sleep') as sleep:
            with self.assertRaisesRegex(OSError, 'disk failed'):
                state_io.atomic_write_json(self.path, {'status':'ended'})
            self.assertEqual(mocked.call_count, 1)
            sleep.assert_not_called()
        self.path.write_text('{')
        with self.assertRaises(json.JSONDecodeError):state_io.read_json(self.path)

    def test_read_transition_retry_and_persistent_failure_bound(self):
        reader=state_io.shared_reader
        with patch.object(state_io,'shared_reader') as mocked, patch.object(state_io.time,'sleep') as sleep:
            def open_again(path):
                if mocked.call_count < 3:raise sharing_error(2)
                return reader(path)
            mocked.side_effect=open_again
            self.assertEqual(state_io.read_json(self.path)['status'],'running')
            self.assertEqual(mocked.call_count,3)
            self.assertEqual([c.args[0] for c in sleep.call_args_list],[.01,.02])
        with patch.object(state_io,'shared_reader',side_effect=sharing_error(32)) as mocked, \
                patch.object(state_io.time,'sleep') as sleep:
            with self.assertRaises(PermissionError):state_io.read_json(self.path)
            self.assertEqual(mocked.call_count,5)
            self.assertAlmostEqual(sum(c.args[0] for c in sleep.call_args_list),.15)

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics')
    def test_actual_windows_lock_releases_during_retry(self):
        held = open(self.path, 'rb')  # Legacy reader without delete sharing.
        with self.assertRaises(OSError):
            candidate = self.path.with_suffix('.candidate')
            candidate.write_text('{}')
            os.replace(candidate, self.path)
        timer = threading.Timer(.06, held.close)
        timer.start()
        try:
            state_io.atomic_write_json(self.path, {'status':'ended'})
        finally:
            timer.join();held.close()
        self.assertEqual(state_io.read_json(self.path)['status'], 'ended')

    def test_fifty_atomic_updates_with_continuous_shared_reader(self):
        errors=[];stop=threading.Event();reads=[]
        def poll():
            while not stop.is_set():
                try:reads.append(state_io.read_json(self.path))
                except Exception as error:errors.append(error)
        worker=threading.Thread(target=poll);worker.start()
        try:
            for number in range(50):
                state_io.atomic_write_json(self.path, {'cycle':number, 'status':'ended'})
        finally:
            stop.set();worker.join(3)
        self.assertFalse(worker.is_alive());self.assertFalse(errors, errors)
        self.assertTrue(reads)
        self.assertEqual(state_io.read_json(self.path)['cycle'],49)

    def test_native_end_retries_status_write_without_restarting_acquisition(self):
        try:
            from squid import acquisition_state as native
        except ImportError:
            self.skipTest('Run in Squid Python with its software cwd for native writer check')
        source=Path(native.__file__).read_bytes()
        state_io.install(native)
        first=native._atomic_write_json;state_io.install(native)
        self.assertIs(first,native._atomic_write_json)
        writer=native.RunStateWriter.start(experiment_id='fixture',pid=123,config_path=None,
            output_path='fixture-images',expected={'timepoints':5},state_dir=self.path.parent)
        ident=writer.run_id
        replace=state_io.replace_file
        with patch.object(state_io,'replace_file') as mocked:
            # Use a real replacement after the first denied attempt.
            def attempt(source,target):
                if mocked.call_count==1:raise sharing_error()
                replace(source,target)
            mocked.side_effect=attempt
            writer.end('completed',{'total_images':5,'errors_encountered':0})
        record=native.read_run(self.path.parent)
        self.assertEqual(record['run_id'],ident)
        self.assertEqual(record['status'],'ended')
        self.assertEqual(record['stats']['total_images'],5)
        self.assertEqual(mocked.call_count,2)
        self.assertEqual(Path(native.__file__).read_bytes(),source)


if __name__=='__main__':unittest.main()
