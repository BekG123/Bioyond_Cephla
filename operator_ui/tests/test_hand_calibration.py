"""Hand-guided vision calibration: read-only hardware interface by construction."""
from types import SimpleNamespace
import unittest

from test_fast_disk import DiskService, Vision, PARAMS
from sequences import Runner
from fast_disk import run_hand_guided_disk, check_path


class ReadOnlyArm:
    def __init__(self, hardware):
        self.hardware = hardware
    def status(self):
        return dict(ok=True, connected=True, errors=[], program_state={'state':'stopped'})
    def pose_mm(self): return self.hardware.pose.copy()
    def joints(self): return self.hardware.q.copy()
    def __getattr__(self, name):
        raise AssertionError('Calibration accessed non-read-only arm capability: ' + name)


class GuidedCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.hardware = DiskService()
        self.arm = ReadOnlyArm(self.hardware)
        self.run = Runner()
        self.run.state = 'running'
        self.vision = Vision(self.hardware)
        self.progress = []
        self.hand = dict(active=True)
        self.camera = SimpleNamespace(snap=lambda:None,save=lambda *a,**k:'fake.png')
        self.follow = True

    def publish(self, update):
        self.progress.append(update)
        if len(self.progress) > 60:
            self.run.request_stop()
        if self.follow and update.get('adjustment'):
            # Simulate the HUMAN repositioning, without calling a motion API.
            previous = self.hardware.pose
            goal = {k:previous[k]+update['adjustment'][k] for k in previous}
            self.hardware.q = check_path(previous,goal,self.hardware.q,PARAMS,None)
            self.hardware.pose = goal

    def execute(self):
        return run_hand_guided_disk(self.run,self.arm,self.camera,self.vision,PARAMS,
                                   lambda:self.hand,self.publish,poll_seconds=0)

    def test_human_guidance_converges_with_no_arm_commands(self):
        result = self.execute()
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['commands_sent'],0)
        self.assertEqual(self.hardware.moves+self.hardware.grips+self.hardware.rotations,[])
        self.assertEqual(self.progress[-1]['confirmation'],2)
        self.assertEqual(result['target']['config'],'Wide')
        self.assertEqual(result['target']['z_calibrated'],69)
        self.assertTrue(self.hand['active'])

    def test_two_fresh_images_needed_when_already_converged(self):
        self.vision.goal = self.hardware.pose.copy()
        result = self.execute()
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['observations'],2)
        self.assertEqual(self.vision.calls,2)
        self.assertFalse(any(x.get('adjustment') for x in self.progress))

    def test_unavailable_draggo_does_not_enable_or_fallback_to_auto(self):
        self.hand['active'] = False
        result = self.execute()
        self.assertFalse(result['ok'])
        self.assertIsNone(self.run.target)
        self.assertEqual(self.vision.calls,0)

    def test_stop_leaves_hand_guiding_active_and_no_stale_target(self):
        self.run.target = {'old':True}
        self.run.request_stop()
        result = self.execute()
        self.assertTrue(result['stopped'])
        self.assertIsNone(self.run.target)
        self.assertTrue(self.hand['active'])

    def test_lost_disks_can_recover_without_three_frame_limit(self):
        solve = self.vision.evaluate_ways
        missed = [0]
        def detect(*args):
            missed[0] += 1
            return dict(detected=False) if missed[0] <= 5 else solve(*args)
        self.vision.evaluate_ways = detect
        result = self.execute()
        self.assertTrue(result['ok'],result)
        self.assertEqual(sum(p['state']=='no_disks' for p in self.progress),5)

    def test_moving_during_image_is_discarded(self):
        def snap():
            self.hardware.pose['Z'] += 1
            self.run.request_stop()
        self.camera.snap = snap
        result = self.execute()
        self.assertFalse(result['ok'])
        self.assertEqual(self.vision.calls,0)
        self.assertIsNone(self.run.target)

    def test_stationary_drift_resets_confirmation(self):
        self.vision.goal = self.hardware.pose.copy()
        original = self.publish
        moved = [False]
        def publish(update):
            original(update)
            if update['state']=='confirming' and not moved[0]:
                moved[0] = True
                self.hardware.pose['Z'] += 1
                self.vision.goal = self.hardware.pose.copy()
        self.publish = publish
        result = self.execute()
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['observations'],3)

    def test_vision_disagreement_never_publishes_target(self):
        self.vision.goal = self.hardware.pose.copy()
        self.vision.jitter = True
        result = self.execute()
        self.assertFalse(result['ok'])
        self.assertIsNone(self.run.target)
        self.assertTrue(any(p['state']=='inconsistent' for p in self.progress))

    def test_no_envelope_prompt_or_access_in_hand_guiding(self):
        # ReadOnlyArm deliberately has no envelope or _preflight attribute.
        self.hardware.envelope_enabled = False
        self.hardware.envelope['Z'] = (0,1)
        self.assertTrue(self.execute()['ok'])


if __name__ == '__main__':
    unittest.main()
