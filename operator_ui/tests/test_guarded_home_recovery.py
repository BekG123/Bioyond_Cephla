"""Recovery lifecycle using the fake controller, never physical hardware."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_ik_home as fixtures
from guarded_home_recovery import GuardedHomeRecovery
from researcher_teaching import TeachingError
from home_recovery import recovered
from sequences import Runner
from latest_hamilton import LatestHamilton


class GuardedRecoveryTests(unittest.TestCase):
    def setUp(self):
        fixtures.IKHomeTests.setUp(self)
        self.service.e1 = .02
        # The shared fake queue updates XY joints but leaves its vertical axis
        # static. Model the measured J1 travel for recovery completion checks.
        old_status = self.service.status
        def status():
            snapshot = deepcopy(old_status())
            snapshot['joints']['J1'] = 261.401 + snapshot['pose_mm']['Z'] - 300.
            return snapshot
        self.service.status = status
        self.state.update(enabled=False, program_state=dict(state='stopped'))
        self.runner = Runner()
        def prepare(run, service):
            self.state.update(enabled=True, control_mode=dict(mode='auto'), program_state=dict(state='running'))
        self.home.prepare = prepare
        self.connection.folder.mkdir()
        self.failed = self.connection.folder/'failed.json'
        self.failed.write_text(json.dumps(dict(status='failed_or_stopped',
            sequence=dict(state='error', result=dict(ok=False, error='joint soft limit')))))
        self.original = self.failed.read_bytes()
        # Real secondary route-history implementation, omitted by the original
        # fake setup; this reproduces the live preflight refusal.
        route = LatestHamilton.__new__(LatestHamilton)
        route.attempts = Path(self.tmp.name)/'route_attempts'
        route.attempts.mkdir()
        self.route_failed = route.attempts/'0001_saved_home.json'
        self.route_failed.write_text(json.dumps(dict(status='stopped_or_failed')))
        self.route_original = self.route_failed.read_bytes()
        self.home.hamilton_route = route
        self.recovery = GuardedHomeRecovery(self.connection)

    def preview(self):
        return self.recovery.preview()['plan']

    def confirmation(self, plan):
        return dict(plan_id=plan['id'], ready=True, empty_gripper=True, cell_clear=True,
                    operator_checked_recovery=True, reviewed_failure=True,
                    review_notes='Fake-device review: operator corrected the condition and confirmed clearance.')

    def wait(self):
        deadline = time.time()+5
        while self.runner.reserved and time.time() < deadline:
            time.sleep(.01)
        self.assertFalse(self.runner.reserved)

    def test_preview_never_unlocks_or_moves(self):
        plan = self.preview()
        self.assertGreater(plan['dense_samples'], 0)
        self.assertEqual(self.service.moves, [])
        self.assertFalse(self.state['enabled'])
        self.assertFalse(recovered(self.failed))
        with self.assertRaises(TeachingError): self.home.hamilton_route.check_previous_attempt()
        with self.assertRaises(TeachingError): self.connection.propose()

    def test_success_resolves_only_exact_original_after_completion(self):
        plan = self.preview()
        self.recovery.confirm(self.confirmation(plan))
        self.wait()
        self.assertTrue(self.runner.result['ok'], self.runner.result)
        self.assertTrue(recovered(self.failed), [p.read_text() for p in self.connection.folder.glob('*.json') if p != self.failed])
        self.assertEqual(self.failed.read_bytes(), self.original)
        self.assertEqual(self.route_failed.read_bytes(), self.route_original)
        self.home.hamilton_route.check_previous_attempt()
        self.assertEqual(len(self.connection.history()), 2)
        with self.assertRaises(TeachingError): self.recovery.confirm(self.confirmation(plan))
        (self.connection.folder/'new.json').write_bytes(self.original)
        with self.assertRaises(TeachingError): self.connection.history()

    def test_failed_motion_does_not_resolve_original(self):
        plan = self.preview()
        # IDLE now uses the Lua pivot queue; fail its upload, not the unused
        # legacy discrete wrist function.
        self.service.robot.set_sys_var_i = Mock(side_effect=RuntimeError('fake queue failure'))
        self.recovery.confirm(self.confirmation(plan))
        self.wait()
        self.assertFalse(recovered(self.failed))
        with self.assertRaises(TeachingError): self.connection.history()
        with self.assertRaises(TeachingError): self.recovery.confirm(self.confirmation(plan))

    def test_changed_pose_hash_and_expired_token_block(self):
        plan = self.preview()
        self.service.pose['X'] += 1
        with self.assertRaises(TeachingError): self.recovery.confirm(self.confirmation(plan))
        self.service.pose['X'] -= 1
        self.failed.write_text(self.original.decode()+' ')
        with self.assertRaises(TeachingError): self.recovery.confirm(self.confirmation(plan))
        self.failed.write_bytes(self.original)
        self.recovery.pending[plan['id']]['expires_at'] = 0
        with self.assertRaises(TeachingError): self.recovery.confirm(self.confirmation(plan))
        self.assertEqual(self.service.moves, [])

    def test_fault_payload_running_and_missing_confirmation_block(self):
        plan = self.preview()
        for delta in (dict(errors=[3571]), dict(enabled=True), dict(program_state=dict(state='running'))):
            old = deepcopy(self.state)
            self.state.update(delta)
            with self.assertRaises(TeachingError): self.recovery.confirm(self.confirmation(plan))
            self.state.clear(); self.state.update(old)
        self.service.e1 = 3.9
        with self.assertRaises(TeachingError): self.recovery.confirm(self.confirmation(plan))
        self.service.e1 = .02
        with self.assertRaises(TeachingError): self.recovery.confirm({**self.confirmation(plan), 'cell_clear': False})
        self.assertEqual(self.service.moves, [])

    def test_restart_and_new_preview_invalidate_old_token(self):
        plan = self.preview()
        with self.assertRaises(TeachingError): GuardedHomeRecovery(self.connection).confirm(self.confirmation(plan))
        self.preview()
        with self.assertRaises(TeachingError): self.recovery.confirm(self.confirmation(plan))

    def test_changed_secondary_failure_blocks_before_motion(self):
        plan = self.preview()
        self.assertIn(self.route_failed.name, plan['route_recovery_of'])
        self.route_failed.write_text(self.route_original.decode() + ' ')
        with self.assertRaisesRegex(TeachingError, 'Route history changed'):
            self.recovery.confirm(self.confirmation(plan))
        self.assertEqual(self.service.moves, [])

    def test_new_secondary_failure_blocks_before_motion(self):
        plan = self.preview()
        (self.route_failed.parent/'2_new.json').write_bytes(self.route_original)
        with self.assertRaisesRegex(TeachingError, 'Route history changed'):
            self.recovery.confirm(self.confirmation(plan))
        self.assertEqual(self.service.moves, [])

    def test_limits_and_changed_settings_still_apply(self):
        self.service.pose['X'] = 700
        with self.assertRaises(TeachingError): self.preview()
        self.assertEqual(self.service.moves, [])


if __name__ == '__main__':
    unittest.main()
