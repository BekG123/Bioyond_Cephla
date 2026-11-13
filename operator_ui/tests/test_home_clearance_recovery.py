"""Offline recovery checks with real accepted geometry and fake command transport."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import home_clearance_recovery as recovery

POSE = dict(X=306.2, Y=-62.88, Z=106.37, Rz=87.88)
JOINTS = dict(J1=67.7711749800802, J2=42.26499, J3=56.99738, J4=-11.38240)


class Service:
    def __init__(self):
        self.envelope = deepcopy(recovery.geometry()['envelope'])
        self.envelope_enabled = True
        self.e1, self.e2 = 28., 90.70836825348935
        self.moving = False
        self.calls = []
        self.registers = {}
        self.robot = SimpleNamespace(get_sys_var_i=lambda keys: self.registers)
        self.s = dict(connected=True, ok=True, enabled=True, errors=[],
                      control_mode={'mode': 'auto'}, program_state={'state': 'running'},
                      pose_mm=deepcopy(POSE), joints=deepcopy(JOINTS))
    def _preflight(self): return None
    def status(self): return deepcopy(self.s)
    def native(self): return dict(moving=self.moving, external_axes=dict(E1=self.e1, E2=self.e2))
    def _locked(self, fn): return fn()
    def _hostpoint(self, values, job, timeout):
        self.calls.append(job)
        if job == 13: self.registers = {7: int(values[7]), 8: 250104}
        elif job == 14: self.e2 = values[9]
        return dict(ok=True)
    def program(self, action):
        self.calls.append(action)
        return dict(ok=True)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.s = Service()
        self.cfg = recovery.geometry()['cfg']
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (patch.object(recovery, 'native', lambda s: s.native()),
                  patch.object(recovery, 'OUTPUT', Path(self.tmp.name)),
                  patch.object(recovery.time, 'sleep', lambda _: None)):
            p.start()
            self.addCleanup(p.stop)
        self.run = SimpleNamespace(stopped=Mock(return_value=False), say=Mock())
        self.queue = Mock()
        self.queue.capability.return_value = dict(available=True, version=220109)
        self.queue.execute.side_effect = self.travel
        p = patch.object(recovery, 'LuaTrajectory', return_value=self.queue)
        p.start()
        self.addCleanup(p.stop)
    def plan(self): return json.loads(json.dumps(recovery.preview(self.s, self.cfg)))
    def execute(self, plan): return recovery.execute(self.run, self.s, self.cfg, plan, True, True)
    def travel(self, run, start, joints, points, cfg, speed, progress, **flags):
        self.assertEqual(speed, 5)
        self.assertEqual(flags, dict(reviewed=True, vertical_runs=True))
        self.assertEqual(self.s.e1, 28)
        self.assertTrue(recovery.accepted(self.s.e2))
        self.s.calls.append('travel')
        progress()
        self.s.s['pose_mm'] = deepcopy(points[-1])
        return dict(ok=True)
    def test_live_hamilton_pose_plans_only_existing_empty_prefix(self):
        plan = self.plan()
        self.assertEqual(plan['steps'], recovery.compile_steps(['squid'], 1)[1:3])
        self.assertEqual(self.s.calls, [])
        self.queue.capability.assert_not_called()
        self.assertFalse(plan['calibration_established'])
    def test_rotates_then_connects_and_verifies_without_jaw_or_startup_commands(self):
        plan = self.plan()
        result = self.execute(plan)
        self.assertEqual(self.s.calls, [13, 14, 'travel'])
        self.assertEqual(result['pose_mm'], plan['target'])
        self.assertEqual(result['plate'], 'HOME')
        record = json.loads(Path(result['record']).read_text())
        self.assertEqual(record['status'], 'completed')
        self.assertFalse(record['calibration_established'])
        self.assertFalse(record['experiment_resumed'])
        with self.assertRaises(FileExistsError):
            self.s.s['pose_mm'] = deepcopy(POSE)
            self.s.e2 = plan['axes']['E2']
            self.execute(plan)
    def test_confirmation_is_required_independently_of_open_jaws(self):
        for empty, seated in ((False, True), (True, False), (1, True)):
            with self.assertRaisesRegex(Exception, 'confirmation'):
                recovery.execute(self.run, self.s, self.cfg, self.plan(), empty, seated)
        self.assertEqual(self.s.calls, [])
    def test_unknown_pose_held_jaws_angle_fault_or_invalid_feedback_never_dispatch(self):
        mutations = [lambda: self.s.s['pose_mm'].update(Z=105),
                     lambda: setattr(self.s, 'e1', 25),
                     lambda: setattr(self.s, 'e2', 45),
                     lambda: setattr(self.s, 'e2', float('nan')),
                     lambda: self.s.s['pose_mm'].update(X=float('nan')),
                     lambda: self.s.s['joints'].update(J1=float('inf')),
                     lambda: self.s.s.update(errors=['fault']),
                     lambda: setattr(self.s, 'moving', True),
                     lambda: setattr(self.s, 'envelope_enabled', False)]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.s = Service()
                mutate()
                with self.assertRaises(Exception): self.plan()
                self.assertEqual(self.s.calls, [])
    def test_stale_or_tampered_plan_never_dispatches(self):
        for field in ('at', 'steps', 'axes', 'start', 'acceptance_sha256'):
            with self.subTest(field=field):
                plan = self.plan()
                if field == 'at': plan[field] -= 121
                elif field == 'steps': plan[field][1]['points'][0]['Z'] -= 10
                elif field == 'axes': plan[field]['E2'] = float('nan')
                elif field == 'start': plan[field]['X'] = float('nan')
                else: plan[field] = 'changed'
                with self.assertRaises(Exception): self.execute(plan)
                self.assertEqual(self.s.calls, [])
    def test_pose_and_holder_changes_since_preview_refused(self):
        plan = self.plan()
        self.s.e2 += .06
        with self.assertRaisesRegex(Exception, 'changed'): self.execute(plan)
        self.s.e2 = plan['axes']['E2']
        self.s.s['pose_mm']['X'] += .06
        with self.assertRaises(Exception): self.execute(plan)
        self.assertEqual(self.s.calls, [])
    def test_short_pose_already_restored_only_connects(self):
        self.s.e2 = 1.77
        self.execute(self.plan())
        self.assertEqual(self.s.calls, ['travel'])
    def test_long_pose_at_original_orientation_is_read_only(self):
        self.s.s['pose_mm'] = deepcopy(recovery.geometry()['clearance'])
        self.s.e2 = 1.77
        self.execute(self.plan())
        self.assertEqual(self.s.calls, [])
        self.queue.capability.assert_not_called()
    def test_long_pose_rotated_holder_only_restores_holder(self):
        self.s.s['pose_mm'] = deepcopy(recovery.geometry()['clearance'])
        self.execute(self.plan())
        self.assertEqual(self.s.calls, [13, 14])
    def test_stop_after_probe_sends_no_rotation_or_travel(self):
        original = self.s._hostpoint
        def command(*args):
            result = original(*args)
            self.run.stopped.return_value = True
            return result
        self.s._hostpoint = command
        with self.assertRaises(Exception): self.execute(self.plan())
        self.assertEqual(self.s.calls, [13])
        self.queue.execute.assert_not_called()
    def test_rotation_timeout_stops_and_does_not_retry(self):
        original = self.s._hostpoint
        def command(values, job, timeout):
            if job == 14:
                self.s.calls.append(job)
                raise TimeoutError('lost rotation reply')
            return original(values, job, timeout)
        self.s._hostpoint = command
        plan = self.plan()
        with self.assertRaises(TimeoutError): self.execute(plan)
        self.assertEqual(self.s.calls, [13, 14, 'stop'])
        self.queue.execute.assert_not_called()
        with self.assertRaises(FileExistsError): self.execute(plan)
    def test_incorrect_rotation_arrival_never_connects(self):
        original = self.s._hostpoint
        def command(*args):
            result = original(*args)
            if args[1] == 14: self.s.e2 = 1.84
            return result
        self.s._hostpoint = command
        with self.assertRaisesRegex(Exception, 'not settled'): self.execute(self.plan())
        self.assertEqual(self.s.calls, [13, 14, 'stop'])
        self.queue.execute.assert_not_called()
    def test_uncertain_queue_reply_stops_without_retry(self):
        self.queue.execute.side_effect = lambda *a, **kw: dict(ok=True, recovered=True)
        with self.assertRaisesRegex(Exception, 'uncertain'): self.execute(self.plan())
        self.assertEqual(self.s.calls, [13, 14, 'stop'])
        self.queue.execute.assert_called_once()
    def test_holder_drift_during_connector_stops(self):
        def travel(*args, **kwargs):
            self.s.e2 += 1
            args[6]()
        self.queue.execute.side_effect = travel
        with self.assertRaisesRegex(Exception, 'Holder changed'): self.execute(self.plan())
        self.assertEqual(self.s.calls[-1], 'stop')

    def test_wrong_lua_version_never_rotates_or_moves(self):
        self.queue.capability.return_value = dict(available=True, version=220108)
        with self.assertRaisesRegex(Exception, 'Lua220109'): self.execute(self.plan())
        self.assertEqual(self.s.calls, [])

    def test_wrong_queue_arrival_stops_without_repeat(self):
        self.queue.execute.side_effect = lambda *args, **kwargs: dict(ok=True)
        with self.assertRaisesRegex(Exception, 'Pose mismatch'): self.execute(self.plan())
        self.assertEqual(self.s.calls, [13, 14, 'stop'])
        self.queue.execute.assert_called_once()

    def test_jaw_feedback_change_during_rotation_never_connects(self):
        original = self.s._hostpoint
        def command(*args):
            result = original(*args)
            if args[1] == 14: self.s.e1 = 25
            return result
        self.s._hostpoint = command
        with self.assertRaisesRegex(Exception, 'jaws'): self.execute(self.plan())
        self.assertEqual(self.s.calls, [13, 14, 'stop'])
        self.queue.execute.assert_not_called()


if __name__ == '__main__': unittest.main()
