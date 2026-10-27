"""Fake-hardware regressions for the actual Flask Find Disk sequence."""
import math
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_transfer import FakeService, PARAMS, CAM
from sequences import Runner, seq_find_disk
from fast_disk import (DiskGuard, camera_plan, camera_goal, run_fast_disk,
                       TransferError, center_before_yaw, confirmed_yaw, converged, check_path)
import teach


class DiskService(FakeService):
    def __init__(self):
        super().__init__()
        self.rotations = []
        self.elapsed = 0.

    def move_cartesian(self, x, y, z, rz, speed=10, interpolation='linear'):
        # Simulated controller latency from the failed live run. Catch any
        # accidental reintroduction of a pure-yaw MoveL, not just final poses.
        if abs(rz-self.pose['Rz']) > 0.05:
            raise AssertionError('wrist rotation dispatched as MoveL')
        self.elapsed += 3.
        return super().move_cartesian(x,y,z,rz,speed,interpolation)

    def rotate_to_rz(self, rz_target, speed, force_delta=None):
        self.rotations.append((rz_target, speed, force_delta))
        self.elapsed += 5.  # hypothetical MoveJ duration, NOT a live benchmark
        p = self.pose
        return super().move_cartesian(p['X'],p['Y'],p['Z'],rz_target,speed,'joint')


class Vision:
    def __init__(self, svc, goal=None):
        self.svc = svc
        self.goal = goal or dict(X=346., Y=0., Z=310., Rz=0.)
        self.calls = 0
        self.lost_after = None
        self.no_progress = False
        self.nan = False
        self.jitter = False

    def selftest(self):
        return True, 'ALL PASS'

    def annotate(self, *args):
        return 'fake_detection.jpg'

    def evaluate_ways(self, *args):
        self.calls += 1
        if self.lost_after is not None and self.calls > self.lost_after:
            return dict(detected=False)
        p, g = self.svc.pose, self.goal
        c = [g['X'], g['Y'], p['Z'], g['Rz']]
        if self.no_progress:
            c[0] = p['X']+10
        if self.nan:
            c[0] = float('nan')
        grasp_z = 60.+(2*self.calls if self.jitter else 0)
        sol = dict(move_xyrz=c, move_z=[p['X'],p['Y'],g['Z'],p['Rz']],
                   move_center=[c[0],c[1],p['Z'],p['Rz']],
                   center_err_mm=math.hypot(c[0]-p['X'],c[1]-p['Y']),
                   grasp_estimate=[340.,-63.,grasp_z,84.], z_calibration_applied=9.,
                   xy_err_mm=math.hypot(c[0]-p['X'],c[1]-p['Y']),
                   z_err_mm=abs(g['Z']-p['Z']), rz_err_deg=abs(g['Rz']-p['Rz']),
                   big_r=190.4, small_r=95.2, selected='Wide')
        return dict(detected=True, ways=[dict(cfg='Wide', solve=sol)])


class FastDiskTests(unittest.TestCase):
    def inject_height_errors(self, values):
        detect = self.vision.evaluate_ways
        def measured(*args):
            ev = detect(*args)
            p = self.svc.pose
            error = values[min(self.vision.calls-1,len(values)-1)]
            sol = ev['ways'][0]['solve']
            sol.update(move_xyrz=[p['X'],p['Y'],p['Z'],p['Rz']],
                move_center=[p['X'],p['Y'],p['Z'],p['Rz']],
                move_z=[p['X'],p['Y'],p['Z']+error,p['Rz']],
                xy_err_mm=0, center_err_mm=0, rz_err_deg=0, z_err_mm=error)
            return ev
        self.vision.evaluate_ways = measured

    def test_good_images_break_noisy_error_history(self):
        # Reproduces the live failure: good views 22 and 25 were omitted from
        # the trend, joining view 23=.242, 24=1.443 and 26=2.286 instead.
        self.inject_height_errors([.6,.1,1.2,.1,1.8,.1,.1])
        result = self.execute()
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['observations'],7)
        self.assertEqual(result['moves'],3)

    def test_suspected_increase_rechecks_without_moving_then_recovers(self):
        self.inject_height_errors([1,2,3,.1,.1])
        result = self.execute()
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['moves'],2)
        self.assertEqual(result['observations'],5)

    def test_true_increase_is_confirmed_stationary_before_stopping(self):
        self.inject_height_errors([1,2,3,3.1,3.2])
        result = self.execute()
        self.assertFalse(result['ok'])
        self.assertIn('three stationary images',result['error'])
        self.assertEqual(result['moves'],2)
        self.assertEqual(result['observations'],5)
        self.assertIsNone(self.run.target)

    def test_movement_during_divergence_review_rejects_stale_measurements(self):
        self.inject_height_errors([1,2,3,3.1])
        annotate = self.vision.annotate
        def shifted(*args):
            if self.vision.calls == 3:
                self.svc.pose['X'] += 1
            return annotate(*args)
        self.vision.annotate = shifted
        result = self.execute()
        self.assertFalse(result['ok'])
        self.assertIn('moved during stationary divergence review',result['error'])
        self.assertEqual(result['moves'],2)

    def test_explicit_wide_does_not_choose_shorter_long_route(self):
        detect = self.vision.evaluate_ways
        def ways(*args):
            from copy import deepcopy
            ev = detect(*args)
            other = deepcopy(ev['ways'][0])
            other['cfg'] = 'Long'
            p = self.svc.pose
            other['solve'].update(move_xyrz=[p['X'],p['Y'],p['Z'],p['Rz']],
                move_z=[p['X'],p['Y'],p['Z'],p['Rz']],xy_err_mm=0,z_err_mm=0,rz_err_deg=0)
            ev['ways'].insert(0,other)
            return ev
        self.vision.evaluate_ways = ways
        updates = []
        result = run_fast_disk(self.run,self.svc,CAM,self.vision,PARAMS,config='Wide',publish=updates.append)
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['target']['config'],'Wide')
        self.assertGreater(result['moves'],0)
        self.assertEqual(updates[-1]['confirmation'],2)
        self.assertEqual(updates[-1]['moves'],result['moves'])
        self.assertEqual(updates[1]['initial_metrics']['xy_mm'],20)

    def test_missing_wide_fails_without_falling_back_or_moving(self):
        detect = self.vision.evaluate_ways
        def ways(*args):
            ev = detect(*args)
            ev['ways'][0]['cfg'] = 'Long'
            return ev
        self.vision.evaluate_ways = ways
        result = run_fast_disk(self.run,self.svc,CAM,self.vision,PARAMS,config='Wide')
        self.assertFalse(result['ok'])
        self.assertIn('no fallback',result['error'])
        self.assertEqual(self.svc.moves+self.svc.rotations,[])

    def test_calibration_journal_has_images_measurements_and_arrivals(self):
        import json
        import tempfile
        from fast_disk import CalibrationTrace
        with tempfile.TemporaryDirectory() as folder:
            trace = CalibrationTrace(folder,'automatic','Wide')
            result = run_fast_disk(self.run,self.svc,CAM,self.vision,PARAMS,config='Wide',trace=trace)
            self.assertTrue(result['ok'],result)
            rows = [json.loads(line) for line in trace.path.read_text().splitlines()]
            observations = [r for r in rows if r['event']=='observation']
            self.assertEqual(len(observations),result['observations'])
            self.assertIn('image',observations[0])
            self.assertIn('solve',observations[0])
            self.assertEqual(len([r for r in rows if r['event']=='movement_arrived']),result['moves'])
            second = CalibrationTrace(folder,'automatic','Wide')
            self.assertNotEqual(trace.path,second.path)

    def setUp(self):
        self.svc, self.run = DiskService(), Runner()
        self.vision = Vision(self.svc)
        self.run.state = 'running'
        self.svc.envelope['Z'] = (250, 320)  # camera-only, NOT grasp depth

    def execute(self):
        return seq_find_disk(self.run, self.svc, CAM, self.vision)

    def test_fast_combined_correction_and_stationary_confirmation(self):
        result = self.execute()
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['moves'], 2)
        self.assertEqual(result['observations'], 4)
        self.assertEqual(self.vision.calls, 4)  # no duplicate detection for selection
        self.assertEqual(self.svc.moves[0], (336.,0.,305.,0.))
        self.assertEqual(self.svc.grips, [])
        self.assertTrue(result['target']['converged'])
        self.assertTrue(result['target']['alignment_requires_preflight'])
        self.assertTrue(any('Future grasp Z' in w for w in result['warnings']))
        self.assertEqual(self.svc.envelope['Z'], (250,320))

    def test_already_converged_takes_two_images_no_motion(self):
        self.vision.goal = self.svc.pose.copy()
        result = self.execute()
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['observations'], 2)
        self.assertEqual(self.svc.moves+self.svc.grips, [])

    def test_lost_detection_never_searches_or_publishes(self):
        self.vision.lost_after = 1
        self.run.target = {'old':True}
        result = self.execute()
        self.assertFalse(result['ok'])
        self.assertEqual(len(self.svc.moves), 1)
        self.assertIsNone(self.run.target)

    def test_no_initial_detection_no_motion(self):
        self.vision.lost_after = 0
        self.assertFalse(self.execute()['ok'])
        self.assertEqual(self.svc.moves, [])

    def test_nonconverged_run_can_be_stopped_without_publishing(self):
        self.vision.no_progress = True
        detect = self.vision.evaluate_ways
        def stop_after_three(*args):
            result = detect(*args)
            if self.vision.calls == 3:
                self.run.request_stop()
            return result
        self.vision.evaluate_ways = stop_after_three
        result = self.execute()
        self.assertFalse(result['ok'])
        self.assertIsNone(self.run.target)
        self.assertEqual(self.run.state, 'stopped')
        self.assertEqual(len(self.svc.moves), 2)

    def test_recovered_or_stale_ack_no_retry(self):
        for failure in ('recovered', 'stale'):
            with self.subTest(failure=failure):
                self.setUp()
                self.svc.motion_failure = failure
                result = self.execute()
                self.assertFalse(result['ok'], result)
                self.assertEqual(len(self.svc.moves), 1)
                self.assertIsNone(self.run.target)

    def test_invalid_solve_fails_closed(self):
        self.vision.nan = True
        self.assertFalse(self.execute()['ok'])
        self.assertEqual(self.svc.moves, [])

    def test_stationary_target_disagreement_is_failure(self):
        self.vision.goal = self.svc.pose.copy()
        self.vision.jitter = True
        self.assertFalse(self.execute()['ok'])
        self.assertIsNone(self.run.target)

    def test_missing_joint_clears_old_target(self):
        self.run.target = {'old':True}
        self.svc.q = {}
        self.assertFalse(self.execute()['ok'])
        self.assertIsNone(self.run.target)
        self.assertEqual(self.svc.moves, [])

    def test_disabled_envelope_respected_for_calibration_only(self):
        self.svc.envelope_enabled = False
        self.svc.envelope['Z'] = (0, 1)  # saved box intentionally not in use
        result = self.execute()
        self.assertTrue(result['ok'], result)
        self.assertFalse(self.svc.envelope_enabled)
        self.assertEqual(result['warnings'], [])
        from fast_disk import GuardedService
        with self.assertRaisesRegex(TransferError, 'workspace envelope'):
            GuardedService(self.svc, self.run, PARAMS)._preflight()

    def test_disabled_box_keeps_joint_checks(self):
        self.svc.envelope_enabled = False
        self.svc.q['J2'] = 179
        self.assertFalse(self.execute()['ok'])
        self.assertEqual(self.svc.moves, [])

    def test_stop_during_motion_prevents_next_step(self):
        move = self.svc.move_cartesian
        def stopped_move(*args):
            out = move(*args)
            self.run.request_stop()
            return out
        self.svc.move_cartesian = stopped_move
        self.assertFalse(self.execute()['ok'])
        self.assertEqual(len(self.svc.moves), 1)
        self.assertEqual(self.run.state, 'stopped')

    def test_camera_envelope_block_is_specific_no_partial_motion(self):
        self.vision.goal['Z'] = 330
        result = self.execute()
        self.assertFalse(result['ok'])
        self.assertIn('CAMERA path blocked: path outside Z envelope', result['error'])
        self.assertEqual(self.svc.moves, [])

    def test_rotation_only_at_safe_height(self):
        self.svc.pose['Z'] = 280
        self.vision.goal = {**self.svc.pose, 'Rz':8}
        result = self.execute()
        self.assertTrue(result['ok'], result)
        previous = dict(X=326,Y=0,Z=280,Rz=0)
        for x,y,z,rz in self.svc.moves:
            if rz != previous['Rz']:
                self.assertEqual((x,y), (previous['X'],previous['Y']))
                self.assertGreaterEqual(min(z,previous['Z']), 300)
            previous = dict(X=x,Y=y,Z=z,Rz=rz)
        self.assertEqual(self.svc.pose['Z'], 280)
        self.assertEqual(len(self.svc.rotations), 1)

    def test_guarded_rotation_failures_never_continue(self):
        for failure in ('stale', 'recovered'):
            with self.subTest(failure=failure):
                self.setUp()
                self.vision.goal = {**self.svc.pose, 'Rz':8}
                self.svc.motion_failure = failure
                result = self.execute()
                self.assertFalse(result['ok'],result)
                self.assertEqual(len(self.svc.moves),1)
                self.assertEqual(len(self.svc.rotations),1)
                self.assertIsNone(self.run.target)

    def test_rotation_helper_refuses_low_height_large_angle_and_missing_joints(self):
        guard = DiskGuard(self.svc,self.run,PARAMS)
        self.svc.pose['Z'] = 280
        with self.assertRaisesRegex(TransferError,'300'):
            guard.rotate_to_rz(8)
        self.svc.pose['Z'] = 300
        with self.assertRaisesRegex(TransferError,'10-degree'):
            guard.rotate_to_rz(11)
        self.svc.q = {}
        with self.assertRaises(TransferError):
            guard.rotate_to_rz(8)
        self.assertEqual(self.svc.moves,[])

    def test_corrected_height_avoids_old_height_detour(self):
        self.svc.pose['Z'] = 260.746
        self.vision.goal = dict(X=346,Y=0,Z=283.055,Rz=8.132)
        with patch('fast_disk.time.monotonic',side_effect=lambda:self.svc.elapsed):
            result = self.execute()
        self.assertTrue(result['ok'],result)
        self.assertEqual(len(self.svc.rotations),1)
        rotation_index = next(i for i,p in enumerate(self.svc.moves) if p[3] != 0)
        self.assertTrue(all(p[2] >= 283.055-1e-6 for p in self.svc.moves[rotation_index:]))
        # 8 lift + 1 wrist + 4 height + 2 XY; avoids the old 260.746 return.
        self.assertEqual(result['moves'],15)
        self.assertEqual(result['elapsed_s'],47.)
        self.assertAlmostEqual(result['travel_mm'],76.199,places=3)

    def test_lower_camera_target_waits_for_fresh_feedback(self):
        self.svc.pose['Z'] = 280
        self.vision.goal = dict(X=326,Y=0,Z=270,Rz=8)
        sol = self.vision.evaluate_ways()['ways'][0]['solve']
        plan = camera_plan(self.svc.pose,sol,self.svc.q,PARAMS,self.svc.envelope)
        self.assertTrue(all(p['Z'] >= 280 for phase,p in plan if phase != 'feedback'))
        self.assertTrue(any(p['Z'] < 280 for phase,p in plan if phase == 'feedback'))

    def test_wrong_joint_arrival_stops_after_rotation(self):
        rotate = self.svc.rotate_to_rz
        def wrong_joint(*args, **kwargs):
            result = rotate(*args, **kwargs)
            self.svc.q['J3'] += 1
            return result
        self.svc.rotate_to_rz = wrong_joint
        self.vision.goal = {**self.svc.pose,'Rz':8}
        self.assertFalse(self.execute()['ok'])
        self.assertEqual(len(self.svc.moves),1)
        self.assertIsNone(self.run.target)

    def test_rotation_clearance_outside_envelope_no_lift(self):
        self.svc.pose['Z'] = 280
        self.svc.envelope['Z'] = (250,290)
        self.vision.goal = {**self.svc.pose, 'Rz':8}
        self.assertFalse(self.execute()['ok'])
        self.assertEqual(self.svc.moves, [])

    def test_camera_motion_during_capture_rejected(self):
        def snap():
            self.svc.pose['X'] += 1
        cam = SimpleNamespace(snap=snap, save=lambda *a,**k:'fake.png')
        result = run_fast_disk(self.run,self.svc,cam,self.vision,PARAMS)
        self.assertFalse(result['ok'])
        self.assertIn('during capture',result['error'])
        self.assertEqual(self.svc.moves, [])

    def test_vendor_z_composition_keeps_small_xy_z_component(self):
        sol = dict(move_xyrz=[326,0,300.15,0],move_z=[326,0,310,0])
        self.assertAlmostEqual(camera_goal(self.svc.pose, sol)['Z'],310.15)

    def test_j4_limit_is_not_overridden(self):
        self.vision.goal = {**self.svc.pose, 'Rz':-40}
        # Fixture limit, independent of the commissioned hardware's settings.
        with patch.dict(PARAMS,j4_pref_abs_deg=150,j4_hard_abs_deg=150), \
                patch('sequences._RP',PARAMS):
            result = self.execute()
        self.assertFalse(result['ok'])
        self.assertIn('J4',result['error'])
        self.assertEqual(self.svc.moves, [])

    def test_recorded_wide_camera_passes_but_long_j2_fails(self):
        pose = dict(X=292.472,Y=55.859,Z=251.452,Rz=-5.842)
        joints = dict(J1=212.853,J2=82.5098,J3=52.0783,J4=-140.4299)
        envelope = dict(X=(255,315),Y=(10,70),Z=(250,305))
        wide = dict(move_xyrz=[282.44,28.567,251.609,2.026],
                    move_z=[292.472,55.859,283.066,-5.842])
        long = dict(move_xyrz=[264.559,74.992,251.588,-25.268],
                    move_z=[292.472,55.859,279.147,-5.842])
        plan = camera_plan(pose,wide,joints,PARAMS,envelope)
        self.assertTrue(plan)
        with self.assertRaisesRegex(TransferError,'J2|J4|envelope'):
            camera_plan(pose,long,joints,PARAMS,envelope)

    def test_sdk_math_selftest(self):
        ok, out = teach.selftest()
        self.assertTrue(ok, out)

    def test_signed_yaw_confirmation_rejects_noise_and_threshold_crossing(self):
        for ds in ([.276,-.366,.507], [.1,.3,.4], [.3,.31,.7], [.3,.3]):
            self.assertIsNone(confirmed_yaw(ds),ds)
        self.assertAlmostEqual(confirmed_yaw([.31,.35,.33]),.33)
        self.assertAlmostEqual(confirmed_yaw([-.31,-.35,-.33]),-.33)

    def test_fixed_wrist_centering_uses_sdk_translation_not_rotated_xy(self):
        sol = self.vision.evaluate_ways()['ways'][0]['solve']
        sol.update(move_xyrz=[450,50,300.1,.5], move_center=[336,0,300,0],
                   center_err_mm=10,rz_err_deg=.5)
        self.assertTrue(center_before_yaw(self.svc.pose,sol))
        plan = camera_plan(self.svc.pose,sol,self.svc.q,PARAMS,self.svc.envelope,center_first=True)
        self.assertTrue(all(phase == 'feedback' and p['Rz'] == 0 for phase,p in plan))
        self.assertEqual(plan[-1][1],dict(X=336,Y=0,Z=310,Rz=0))

    def test_live_small_yaw_pattern_does_not_interrupt_centering(self):
        self.vision.goal = dict(X=356,Y=0,Z=310,Rz=0)
        detect = self.vision.evaluate_ways
        pattern = [.154,.276,-.366,.066,.109,.507]
        def noisy(*args):
            ev = detect(*args)
            sol = ev['ways'][0]['solve']
            # Replay the observed yaw excursions while out of center. At the
            # stationary goal, accurate fresh detections converge normally.
            if sol['center_err_mm'] >= 1 or sol['z_err_mm'] >= 1:
                d = pattern[(self.vision.calls-1)%len(pattern)]
                sol['move_xyrz'][3] = self.svc.pose['Rz']+d
                sol['rz_err_deg'] = abs(d)
            return ev
        self.vision.evaluate_ways = noisy
        result = self.execute()
        self.assertTrue(result['ok'],result)
        self.assertEqual(self.svc.rotations,[])
        self.assertEqual(result['moves'],3)
        self.assertEqual(result['observations'],5)

    def test_consistent_small_yaw_corrected_only_after_centering_and_three_views(self):
        self.vision.goal = dict(X=346,Y=0,Z=310,Rz=.5)
        detect = self.vision.evaluate_ways
        seen = []
        def observing(*args):
            seen.append(dict(self.svc.pose))
            return detect(*args)
        self.vision.evaluate_ways = observing
        result = self.execute()
        self.assertTrue(result['ok'],result)
        self.assertEqual(len(self.svc.rotations),1)
        stationary = [p for p in seen if p == dict(X=346,Y=0,Z=310,Rz=0)]
        self.assertEqual(len(stationary),3)
        rotation_index = next(i for i,p in enumerate(self.svc.moves) if p[3] != 0)
        self.assertEqual(self.svc.moves[rotation_index][:3],(346,0,310))

    def test_unstable_stationary_yaw_never_rotates_or_publishes(self):
        self.vision.goal = self.svc.pose.copy()
        detect = self.vision.evaluate_ways
        def noisy(*args):
            ev = detect(*args)
            sol = ev['ways'][0]['solve']
            d = .4 if self.vision.calls%2 else -.4
            sol['move_xyrz'][3] = d
            sol['rz_err_deg'] = abs(d)
            if self.vision.calls == 20:
                self.run.request_stop()
            return ev
        self.vision.evaluate_ways = noisy
        result = self.execute()
        self.assertFalse(result['ok'])
        self.assertIsNone(self.run.target)
        self.assertEqual(self.svc.moves,[])
        self.assertEqual(self.run.state,'stopped')
        self.assertEqual(self.vision.calls,20)

    def test_final_tolerances_are_not_relaxed_by_scheduling_thresholds(self):
        sol = self.vision.evaluate_ways()['ways'][0]['solve']
        sol.update(xy_err_mm=.29,z_err_mm=.29,rz_err_deg=.19)
        self.assertTrue(converged(sol))
        for key,value in [('xy_err_mm',.3),('z_err_mm',.3),('rz_err_deg',.2)]:
            self.assertFalse(converged({**sol,key:value}))

    def test_pose_change_between_yaw_samples_fails_closed(self):
        self.vision.goal = {**self.svc.pose,'Rz':.5}
        annotate = self.vision.annotate
        def shifted(*args):
            if self.vision.calls == 1:
                self.svc.pose['X'] += 1
            return annotate(*args)
        self.vision.annotate = shifted
        result = self.execute()
        self.assertFalse(result['ok'])
        self.assertIn('stationary yaw review',result['error'])
        self.assertEqual(self.svc.moves,[])

    def test_holding_or_missing_telemetry_prevents_motion(self):
        self.svc.torque = -187
        self.assertFalse(self.execute()['ok'])
        self.assertEqual(self.svc.moves, [])
        self.svc.torque_report = lambda: dict(ok=True, telemetry_live=False)
        self.assertFalse(self.execute()['ok'])
        self.assertEqual(self.svc.moves, [])

    def test_converges_beyond_old_observation_time_and_travel_caps(self):
        self.svc.envelope['Z'] = (70,320)  # fake cell: 210 mm checked vertical route
        self.vision.goal = {**self.svc.pose, 'Z':90.}
        move = self.svc.move_cartesian
        def slow_move(*args):
            result = move(*args)
            self.svc.elapsed += 4.
            return result
        self.svc.move_cartesian = slow_move
        with patch('fast_disk.time.monotonic',side_effect=lambda:self.svc.elapsed):
            result = self.execute()
        self.assertTrue(result['ok'],result)
        self.assertGreater(result['observations'],14)
        self.assertGreater(result['elapsed_s'],120)
        self.assertGreater(result['travel_mm'],200)
        self.assertTrue(result['target']['converged'])
        self.assertEqual(self.svc.grips,[])

    def test_more_than_two_improving_yaw_corrections_can_converge(self):
        self.vision.goal = {**self.svc.pose,'Rz':8.}
        detect = self.vision.evaluate_ways
        def partial_correction(*args):
            result = detect(*args)
            sol = result['ways'][0]['solve']
            delta = (self.vision.goal['Rz']-self.svc.pose['Rz'])/2
            sol['move_xyrz'][3] = self.svc.pose['Rz']+delta
            sol['rz_err_deg'] = abs(delta)
            return result
        self.vision.evaluate_ways = partial_correction
        result = self.execute()
        self.assertTrue(result['ok'],result)
        self.assertGreater(len(self.svc.rotations),2)

    def test_increasing_confirmed_yaw_stops_without_target(self):
        self.vision.goal = self.svc.pose.copy()
        detect = self.vision.evaluate_ways
        def increasing(*args):
            result = detect(*args)
            sol = result['ways'][0]['solve']
            delta = .4*(len(self.svc.rotations)+1)
            sol['move_xyrz'][3] = self.svc.pose['Rz']+delta
            sol['rz_err_deg'] = delta
            return result
        self.vision.evaluate_ways = increasing
        result = self.execute()
        self.assertFalse(result['ok'],result)
        self.assertIn('yaw error increasing',result['error'])
        self.assertEqual(len(self.svc.rotations),2)
        self.assertIsNone(self.run.target)

    def test_flask_routes_require_confirmation_and_use_fast_sequence(self):
        import app as console
        with patch.object(console.runner, 'start', return_value=dict(ok=True)) as start, \
                patch.object(console.draggo, 'latched', False):
            client = console.app.test_client()
            for path in ('/seq/find_disk_fast',):
                self.assertEqual(client.post(path,json={}).status_code,400)
                self.assertEqual(client.post(path,json=dict(confirm=True,cell_clear=True,
                                                            empty_gripper='true')).status_code,400)
            start.assert_not_called()
            for path in ('/seq/find_disk_fast',):
                reply = client.post(path,json=dict(confirm=True,cell_clear=True,empty_gripper=True))
                self.assertEqual(reply.status_code,200)
                self.assertIs(start.call_args.args[1], seq_find_disk)


if __name__ == '__main__':
    unittest.main()
