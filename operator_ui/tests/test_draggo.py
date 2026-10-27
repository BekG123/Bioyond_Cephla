"""No hardware: wire compatibility, mode transitions, failures and UI ownership."""
from pathlib import Path
import struct
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from draggo import DragGo, DragGoRPC
from researcher_teaching import TeachingError


class FakeRPC:
    def __init__(self):
        self.state = dict(manual=False, enabled=False, disabled=True, moving=False,
                          emergency=False, drag=False, error=False)
        self.calls = []
        self.fail = ''

    def info(self):
        if self.fail == 'read':
            raise TimeoutError('connection lost')
        return self.state.copy()

    def disable(self, info):
        self.calls.append('disable')
        self.state.update(enabled=False, disabled=True)

    def write_di(self, pin, value):
        self.calls.append(('di', pin, value))
        if pin == 1:
            self.state['manual'] = value == 0
        if pin == 2:
            if value == 1 and self.fail == 'enable':
                raise TimeoutError('enable acknowledgement lost')
            self.state.update(enabled=bool(value), disabled=not value)

    def set_drag(self, value):
        self.calls.append(('drag', value))
        if self.fail == 'drag':
            raise TimeoutError('drag acknowledgement lost')
        assert self.state['disabled'], 'DragGo toggled while enabled'
        self.state['drag'] = value


class DragGoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.rpc = FakeRPC()
        self.robot_state = dict(ok=True, connected=True, errors=[], program_state={'state':'stopped'})
        self.service = SimpleNamespace(robot=SimpleNamespace(connected=True), _motion=threading.Lock(),
                                       _endpoint_addr=lambda: ('offline', 56788), status=lambda: self.robot_state)
        self.drag = DragGo(lambda: self.service, Path(self.tmp.name) / 'latch.json', lambda host: self.rpc)
        sleeper = patch('draggo.time.sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_read_only_status_never_changes_controller(self):
        self.assertTrue(self.drag.public(self.robot_state)['can_start'])
        self.assertEqual(self.rpc.calls, [])

    def test_start_waits_for_brief_status_poll_lock(self):
        held, release = threading.Event(), threading.Event()
        def poll():
            with self.drag.lock:
                held.set()
                release.wait(1)
        thread = threading.Thread(target=poll)
        thread.start(); self.assertTrue(held.wait(1))
        timer = threading.Timer(.03, release.set)
        timer.start()
        try:
            self.assertTrue(self.drag.change(True, True)['ok'])
        finally:
            release.set(); thread.join(1); timer.cancel()

    def test_status_waits_for_other_reader_instead_of_claiming_mode_change(self):
        held, release = threading.Event(), threading.Event()
        def poll():
            with self.drag.lock:
                held.set()
                release.wait(1)
        thread = threading.Thread(target=poll)
        thread.start()
        self.assertTrue(held.wait(1))
        timer = threading.Timer(.03, release.set)
        timer.start()
        try:
            status = self.drag.public(self.robot_state)
            self.assertEqual(status['state'], 'off')
            self.assertFalse(status['blocked'])
            self.assertEqual(self.rpc.calls, [])
        finally:
            release.set(); thread.join(1); timer.cancel()

    def auto_enabled(self):
        self.rpc.state.update(manual=False, enabled=True, disabled=False)
        self.service.robot.get_ctrl_mode = lambda:dict(mode='auto')
        def disable(enable, confirmed):
            self.assertFalse(enable)
            self.assertTrue(confirmed)
            self.rpc.state.update(enabled=False, disabled=True)
            return dict(ok=True)
        self.service.set_enable = Mock(side_effect=disable)

    def test_auto_enabled_start_uses_shared_disable_before_manual(self):
        self.auto_enabled()
        self.assertTrue(self.drag.change(True, True)['ok'])
        self.service.set_enable.assert_called_once_with(False, confirmed=True)
        self.assertEqual(self.rpc.calls, [('di',1,0), ('drag',True), ('di',2,0), ('di',2,1)])
        self.assertTrue(self.drag.public(self.robot_state)['active'])

    def test_latched_auto_exit_uses_shared_disable_and_clears_message(self):
        self.auto_enabled()
        self.drag._latch(True)
        self.drag.message = 'Previous transition failed'
        self.assertTrue(self.drag.change(False)['ok'])
        self.service.set_enable.assert_called_once_with(False, confirmed=True)
        self.assertFalse(self.drag.blocks_motion)
        self.assertTrue(self.rpc.state['disabled'])
        self.assertEqual(self.drag.message, '')
        self.assertEqual(self.rpc.calls, [])

    def test_auto_disable_rejection_cannot_enter_manual_or_enable(self):
        self.auto_enabled()
        self.service.set_enable.side_effect = lambda *args,**kw:dict(ok=False,error='rejected')
        with self.assertRaises(TeachingError): self.drag.change(True, True)
        self.assertTrue(self.drag.blocks_motion)
        self.assertEqual(self.rpc.calls, [])

    def test_auto_disable_ack_without_disabled_state_cannot_proceed(self):
        self.auto_enabled()
        self.service.set_enable.side_effect = lambda *args,**kw:dict(ok=True)
        with patch.object(self.drag, '_wait', side_effect=TimeoutError('still enabled')):
            with self.assertRaises(TeachingError): self.drag.change(True, True)
        self.assertTrue(self.drag.blocks_motion)
        self.assertEqual(self.rpc.calls, [])

    def test_mode_change_never_sends_auto_disable_in_manual(self):
        self.auto_enabled()
        self.service.robot.get_ctrl_mode = lambda:dict(mode='manual')
        with self.assertRaises(TeachingError): self.drag.change(True, True)
        self.service.set_enable.assert_not_called()
        self.assertEqual(self.rpc.calls, [])

    def test_explicit_ready_and_known_program_required(self):
        for ready in (False, 1, 'true', None):
            with self.assertRaises(TeachingError):
                self.drag.change(True, ready)
        self.robot_state['program_state']['state'] = 'unknown'
        with self.assertRaises(TeachingError):
            self.drag.change(True, True)
        self.assertEqual(self.rpc.calls, [])
        self.assertFalse(self.drag.blocks_motion)

    def running_program(self):
        self.auto_enabled()
        self.robot_state['program_state']['state'] = 'running'
        def stop(action):
            self.assertEqual(action, 'stop')
            self.assertEqual(self.rpc.calls, [])
            self.service.set_enable.assert_not_called()
            self.robot_state['program_state']['state'] = 'stopped'
            return dict(ok=True)
        self.service.program = Mock(side_effect=stop)

    def test_idle_running_program_is_stopped_before_draggo(self):
        self.running_program()
        self.assertTrue(self.drag.public(self.robot_state)['can_start'])
        self.service.program.assert_not_called()
        self.assertTrue(self.drag.change(True, True)['ok'])
        self.service.program.assert_called_once_with('stop')
        self.assertTrue(self.drag.public(self.robot_state)['active'])

    def test_paused_program_is_stopped_never_resumed(self):
        self.running_program()
        self.robot_state['program_state']['state'] = 'paused'
        self.assertTrue(self.drag.change(True, True)['ok'])
        self.service.program.assert_called_once_with('stop')

    def test_running_program_without_confirmation_or_while_moving_is_untouched(self):
        self.running_program()
        with self.assertRaises(TeachingError): self.drag.change(True, False)
        self.rpc.state['moving'] = True
        with self.assertRaises(TeachingError): self.drag.change(True, True)
        self.service.program.assert_not_called()
        self.assertFalse(self.drag.blocks_motion)

    def test_rejected_program_stop_never_switches_to_manual_or_enables(self):
        self.running_program()
        self.service.program.side_effect = lambda action:dict(ok=False,error='rejected')
        with self.assertRaises(TeachingError): self.drag.change(True, True)
        self.assertEqual(self.rpc.calls, [])
        self.assertTrue(self.drag.blocks_motion)

    def test_stop_ack_must_be_followed_by_stopped_status(self):
        self.running_program()
        self.service.program.side_effect = lambda action:dict(ok=True)
        with patch('draggo.time.monotonic', side_effect=[0, 5]):
            with self.assertRaises(TeachingError): self.drag.change(True, True)
        self.service.program.assert_called_once_with('stop')
        self.assertEqual(self.rpc.calls, [])
        self.assertTrue(self.drag.blocks_motion)

    def test_enter_capture_ready_and_exit_without_program_or_auto_enable(self):
        self.assertTrue(self.drag.change(True, True)['ok'])
        self.assertEqual(self.rpc.calls, ['disable', ('di',1,0), ('drag',True), ('di',2,0), ('di',2,1)])
        self.assertTrue(self.drag.public(self.robot_state)['active'])
        self.assertTrue(self.drag.blocks_motion)
        self.assertTrue(self.drag.change(False)['ok'])
        self.assertEqual(self.rpc.calls[-2:], ['disable', ('drag',False)])
        self.assertTrue(self.rpc.state['disabled'])
        self.assertFalse(self.drag.blocks_motion)

    def test_duplicate_start_does_not_toggle_or_reenable(self):
        self.drag.change(True, True)
        previous = self.rpc.calls.copy()
        with self.assertRaises(TeachingError):
            self.drag.change(True, True)
        self.assertEqual(self.rpc.calls, previous)

    def test_unsupported_or_disconnected_no_writes(self):
        self.rpc.fail = 'read'
        with self.assertRaises(TeachingError):
            self.drag.change(True, True)
        self.assertEqual(self.rpc.calls, [])
        self.service.robot.connected = False
        with self.assertRaises(TeachingError):
            self.drag.change(True, True)

    def test_failed_enable_disables_and_latches_across_restart(self):
        self.rpc.fail = 'enable'
        with self.assertRaises(TeachingError):
            self.drag.change(True, True)
        self.assertEqual(self.rpc.calls[-1], 'disable')
        self.assertTrue(self.drag.blocks_motion)
        restarted = DragGo(lambda: self.service, self.drag.path, lambda host: self.rpc)
        self.assertTrue(restarted.blocks_motion)
        self.rpc.fail = ''
        restarted.change(False)
        self.assertFalse(restarted.blocks_motion)

    def test_failed_exit_never_unlocks_other_controls(self):
        self.drag.change(True, True)
        self.rpc.fail = 'drag'
        with self.assertRaises(TeachingError):
            self.drag.change(False)
        self.assertTrue(self.drag.blocks_motion)

    def test_disconnect_does_not_claim_off_or_allow_restart(self):
        self.drag.change(True, True)
        status = self.drag.public(dict(connected=False))
        self.assertEqual(status['state'], 'unknown')
        self.assertFalse(status['can_start'])
        self.assertTrue(status['blocked'])

    def test_fault_and_moving_refuse_enable(self):
        for field in ('moving', 'emergency', 'error'):
            self.rpc.state[field] = True
            with self.assertRaises(TeachingError):
                self.drag.change(True, True)
            self.rpc.state[field] = False
        self.assertEqual(self.rpc.calls, [])

    def test_cancel_before_servo_enable_prevents_later_enable(self):
        original = self.rpc.set_drag
        def interrupt(value):
            original(value)
            self.drag.cancelled.set()
        self.rpc.set_drag = interrupt
        with self.assertRaises(TeachingError):
            self.drag.change(True, True)
        self.assertNotIn(('di', 2, 1), self.rpc.calls)
        self.assertTrue(self.drag.blocks_motion)

    def test_motion_lock_refuses_transition(self):
        with self.service._motion:
            with self.assertRaises(TeachingError):
                self.drag.change(True, True)
        self.assertEqual(self.rpc.calls, [])


class ProtocolTests(unittest.TestCase):
    def test_unsupported_native_auto_disable_is_never_sent(self):
        rpc = DragGoRPC('offline')
        with patch.object(rpc,'call') as call:
            with self.assertRaises(RuntimeError): rpc.disable(dict(disabled=False,manual=False))
            call.assert_not_called()

    def test_already_disabled_sends_no_redundant_disable(self):
        rpc = DragGoRPC('offline')
        with patch.object(rpc, 'call') as call:
            rpc.disable(dict(disabled=True, manual=False))
            rpc.disable(dict(disabled=True, manual=True))
            call.assert_not_called()

    def test_live_draggo_state_six_is_recognized(self):
        # Captured 2026-10-16: Manual=0, enabled DragGo=6, moving=1,
        # four arm joints, two external axes, native DragGo flag=1.
        data = self.payload()
        data[98:104] = bytes((0, 0, 6, 4, 2, 1))
        rpc = DragGoRPC('offline')
        with patch.object(rpc, 'call', return_value=data):
            info = rpc.info()
            self.assertTrue(info['manual'] and info['drag'] and info['enabled'])
            self.assertTrue(info['moving'])
            self.assertFalse(info['disabled'] or info['error'])
            data[100] = 9  # enum MAX is not a valid state
            with self.assertRaises(ValueError):
                rpc.info()

    @staticmethod
    def payload():
        data = bytearray(740)
        for offset, value in ((0,b'BRC-full'), (32,b'1.8.2504101654'), (64,b'S4-1.5-0.4-Z0.4-G')):
            data[offset:offset+len(value)] = value
        data[98:104] = bytes((0,0,2,4,2,0))
        struct.pack_into('<I', data, 732, 1)  # errorCount must not be interpreted as DragGo
        struct.pack_into('<i', data, 736, 1)
        return data

    def test_aligned_drag_flag_and_firmware_gate(self):
        data = self.payload()
        rpc = DragGoRPC('offline')
        with patch.object(rpc, 'call', return_value=data):
            self.assertTrue(rpc.info()['drag'])
            struct.pack_into('<i', data, 736, 0)
            self.assertFalse(rpc.info()['drag'])
            data[32] = ord('2')
            with self.assertRaises(ValueError):
                rpc.info()

    def test_native_external_feedback_units_and_validation(self):
        data = self.payload()
        data[368:370] = bytes((1, 0))
        struct.pack_into('<2f', data, 336, .015, -3.141592653589793 / 2)
        rpc = DragGoRPC('offline')
        with patch.object(rpc, 'call', return_value=data):
            info = rpc.info()
            self.assertAlmostEqual(info['external_axes']['E1'], 15, places=5)
            self.assertAlmostEqual(info['external_axes']['E2'], -90, places=4)
            self.assertEqual(info['external_units'], {'E1': 'mm', 'E2': 'degrees'})
            data[368] = 9
            with self.assertRaises(ValueError):
                rpc.info()
            data[368] = 1
            struct.pack_into('<f', data, 336, float('nan'))
            with self.assertRaises(ValueError):
                rpc.info()

    def test_fragmented_response_and_wrong_header(self):
        class Socket:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def settimeout(self, timeout): pass
            def sendall(self, data): self.sent = data
            def recv(self, size):
                part, self.data = self.data[:min(size,3)], self.data[min(size,3):]
                return part
        sock = Socket()
        sock.data = struct.pack('<iii4B', 756, 0, 10, 1, 0, 0, 0) + self.payload()
        with patch('draggo.socket.create_connection', return_value=sock):
            self.assertTrue(DragGoRPC('offline').info()['drag'])
            self.assertEqual(struct.unpack('<i', sock.sent[8:12])[0], 10)
            for size, seq, cmd, resp in ((15,0,10,1), (99999,0,10,1), (16,7,10,1), (16,0,137,1), (16,0,10,0)):
                sock.data = struct.pack('<iii4B', size, seq, cmd, resp, 0, 0, 0)
                with self.assertRaises(ValueError):
                    DragGoRPC('offline').info()


if __name__ == '__main__':
    unittest.main()
