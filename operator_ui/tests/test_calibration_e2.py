import sys
from pathlib import Path
import unittest
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calibration_e2 import verify


class E2Tests(unittest.TestCase):
    def check(self, **changes):
        state = dict(error=False, emergency=False, moving=False, drag=False,
                     external_axes={'E2': 1.77}, external_units={'E2': 'degrees'})
        state.update(changes)
        run = Mock()
        run.stopped.return_value = False
        read = Mock(return_value=state)
        result = verify(None, run, read=read, sleep=lambda _: None)
        self.assertEqual(read.call_count, 3)
        return result

    def test_three_fresh_samples(self):
        self.assertEqual(self.check(), [1.77]*3)

    def test_rejects_off_target_invalid_and_unsafe(self):
        for change in [dict(external_axes={'E2': 2.01}), dict(external_axes={}),
                       dict(external_axes={'E2': float('nan')}),
                       dict(external_units={'E2': 'mm'}), dict(error=True),
                       dict(emergency=True), dict(moving=True), dict(drag=True)]:
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                self.check(**change)

    def test_cancel_before_read(self):
        run, read = Mock(), Mock()
        run.stopped.return_value = True
        with self.assertRaises(RuntimeError):
            verify(None, run, read=read)
        read.assert_not_called()

    def test_positive_tolerance_only(self):
        self.assertEqual(self.check(external_axes={'E2': 1.76855}), [1.76855]*3)
        self.assertEqual(self.check(external_axes={'E2': 1.82}), [1.82]*3)
        for value in (1.76, 1.7684, 1.8201, 1.97):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                self.check(external_axes={'E2': value})

    def test_single_correction_and_fresh_feedback(self):
        run, svc = Mock(), Mock()
        run.stopped.return_value = False
        svc.position_calibration_e2.return_value = {'ok': True}
        def state(value):
            return dict(error=False, emergency=False, moving=False, drag=False,
                        external_axes={'E2': value}, external_units={'E2': 'degrees'})
        read = Mock(side_effect=[state(2.1)] + [state(1.82)]*3)
        self.assertEqual(verify(svc, run, read, lambda _: None, correct=True), [1.82]*3)
        svc.position_calibration_e2.assert_called_once()
        svc.reset_mock()
        with self.assertRaises(RuntimeError):
            verify(svc, run, lambda: state(2.1), lambda _: None, correct=True)
        svc.position_calibration_e2.assert_called_once()

    def test_failed_command_never_retried(self):
        run, svc = Mock(), Mock()
        run.stopped.return_value = False
        svc.position_calibration_e2.return_value = {'ok': False, 'error': 'UNKNOWN STATE'}
        read = Mock(return_value=dict(error=False, emergency=False, moving=False, drag=False,
                    external_axes={'E2': 2.1}, external_units={'E2': 'degrees'}))
        with self.assertRaisesRegex(RuntimeError, 'UNKNOWN STATE'):
            verify(svc, run, read, correct=True)
        svc.position_calibration_e2.assert_called_once()
        self.assertEqual(read.call_count, 1)


if __name__ == '__main__':
    unittest.main()
