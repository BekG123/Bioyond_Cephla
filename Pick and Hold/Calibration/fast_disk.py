"""Two-disk plate calibration: complete algorithm in one file.

Read top to bottom:
  1. start_calibration / run_fast_disk: capture -> solve -> step -> confirm.
  2. Camera goals, bounded steps, yaw review and convergence.
  3. Robot readiness, pose units, path/IK checks, command and arrival guards.
  4. Vendor configuration, disk detection, image/robot pose math and annotation.
  5. Offline SDK validation.

Hardware boundary: cam.snap()/save() use the shared GigE driver; svc methods
use the existing locked robot transport. This module never opens a second
connection, enables the controller, or starts Align/Descend/Grip.
The Flask Runner only schedules this algorithm and exposes its log/result.
Historical imports (teach, mcp_teach, sdk_pose, autonomy helpers) delegate here.

Offline only: python "Pick and Hold/Calibration/fast_disk.py" test
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = str(ROOT / "operator_ui")  # compatibility with the former teach module
GRAB_DIR = str(ROOT / "grab_skill")
CAL_PATH = os.path.join(GRAB_DIR, "calibration.json")
CFG_BASE = str(ROOT / "Vision_context/S4-VisionDemo/USVisionDemo/VisionServer/Locator/Config")
CFG_DIRS = [(name, str(Path(CFG_BASE) / "Test" / name / "1/LocatorInfoCV_NEW.json"))
            for name in ("Wide", "Long")]
_cfgs = None
_selftest: tuple[bool, str] | None = None

SPEED = 10
XY_STEP_MM = 10.0
Z_STEP_MM = 5.0
ROTATE_STEP_DEG = 10.0
ROTATE_Z_MM = 300.0
XY_TOL_MM, Z_TOL_MM, RZ_TOL_DEG = 0.3, 0.3, 0.2
# Scheduling thresholds only. Final convergence tolerances above are unchanged.
COARSE_YAW_DEG = 2.0
YAW_REVIEW_XY_MM, YAW_REVIEW_Z_MM = 1.0, 1.0
YAW_SAMPLES = 3
YAW_SPREAD_DEG = 0.2


# ===========================================================================
# 1. MAIN FLOW - begin reading here
# ===========================================================================

def start_calibration(run, svc, cam, params, vision=None):
    """Entry point for the console; dependencies are passed in, never connected here.

    Production vision functions are in this file. Tests may inject fake vision.
    run provides stopped()/say() and stores target/state; svc owns the single
    robot connection; cam owns the single camera; params are the robot limits.
    """
    if vision is None:
        vision = sys.modules[__name__]
    return run_fast_disk(run, svc, cam, vision, params)


def run_fast_disk(run, svc, cam, teach, params):
    """Same Flask Runner/target contract as Find Disk; never calls Align/Descend."""
    started = time.monotonic()
    run.target = None  # no stale target after ANY failure, including preflight
    guard = DiskGuard(svc, run, params)
    observations = moves = 0
    travel = 0.0
    pinned = None
    stable = []
    errors = []
    yaw_errors = []
    yaw_samples = []
    yaw_pose = None

    try:
        guard._preflight()
        ok, out = teach.selftest()
        if not ok:
            raise TransferError('vendor teach selftest FAILED; no motion')
        run.say('Fast disk v4: vendor selftest ALL PASS; continue until confirmed convergence, operator stop or fault; no observation/time/travel caps')
        while True:
            guard._preflight()
            pose = guard.pose_mm()
            if yaw_pose is not None and (
                    any(abs(pose[k]-yaw_pose[k]) > 0.1 for k in ('X','Y','Z'))
                    or abs(wrap(pose['Rz']-yaw_pose['Rz'])) > 0.05):
                raise TransferError('robot moved during stationary yaw review; no stale correction')
            q = svc.joints() or {}
            check_path(pose, pose, q, params, svc.envelope)
            ev = None
            for attempt in range(3):
                guard._preflight()
                frame = cam.snap()  # guaranteed fresh, never cached /frame fallback
                path = cam.save(frame, prefix='teach_fast')
                actual = guard.pose_mm()
                if (any(abs(actual[k]-pose[k]) > 0.1 for k in ('X','Y','Z'))
                        or abs(wrap(actual['Rz']-pose['Rz'])) > 0.05):
                    raise TransferError('robot moved during capture; no motion from this image')
                # One circle detection per capture, shared by both vendor configs.
                ev = teach.evaluate_ways(path, pose['X'], pose['Y'], pose['Z'], pose['Rz'])
                if ev.get('detected') and ev.get('ways'):
                    break
                run.say(f'No circle pair ({attempt+1}/3); recapture without moving', 'warn')
            else:
                raise TransferError('disk not detected; no search/recovery motion or stale target')
            observations += 1
            options, reasons = [], []
            for way in ev['ways']:
                if pinned is not None and way['cfg'] != pinned:
                    continue
                sol = way['solve']
                validate_solve(sol)
                try:
                    legs = camera_plan(pose, sol, q, params, svc.envelope,
                                       center_first=center_before_yaw(pose, sol))
                    options.append((route_cost(pose, legs), way, legs))
                except TransferError as ex:
                    reasons.append(f"{way['cfg']}: CAMERA path blocked: {ex}")
            if not options:
                raise TransferError('; '.join(reasons) or 'selected camera configuration missing')
            _, way, legs = min(options, key=lambda item: item[0])
            sol = way['solve']
            if pinned is None:
                pinned = way['cfg']
                for reason in reasons:
                    run.say(reason, 'warn')
                run.say(f'Selected {pinned}: shortest checked camera route. Grasp is validated separately.')
            try:
                run.detection_path = teach.annotate(path, sol)
                run.detection_ts = time.time()
            except Exception as ex:
                run.say(f'Annotation unavailable: {ex}', 'warn')
            run.say(f"View {observations}: {pinned}, XY {sol['xy_err_mm']:.3f} mm, "
                    f"yaw {sol['rz_err_deg']:.3f} deg, Z {sol['z_err_mm']:.3f} mm; "
                    f"{moves} moves, {time.monotonic()-started:.1f} s, {travel:.1f} mm travel")
            if converged(sol):
                if stable and not agree(stable[-1], sol):
                    raise TransferError('converged images disagree on grasp pose; no target published')
                stable.append(sol)
                if len(stable) == 2:
                    break
                run.say('Converged; confirming with a second fresh stationary image')
                continue
            stable.clear()
            centering = center_before_yaw(pose, sol)
            error = max(sol['center_err_mm'], sol['z_err_mm'])
            errors.append(error)
            del errors[:-3]
            if len(errors) >= 3 and errors[-1] > errors[-2]+0.5 and errors[-2] > errors[-3]+0.5:
                raise TransferError('calibration error increasing; disk moved or vision is inconsistent')
            # Complete only lift/rotate/observation-height before re-observing.
            # Otherwise execute ONE bounded combined XY/Z correction, then capture.
            phase = [(kind, p) for kind, p in legs if kind in ('orientation', 'rotation')]
            if centering:
                yaw_samples.clear()
                yaw_pose = None
                run.say('Center XY/height first; hold wrist despite small yaw residual')
            elif phase or yaw_samples:
                # No movement while accumulating evidence. Signed deltas avoid
                # treating alternating +/- noise as a consistent correction.
                yaw_pose = dict(pose)
                yaw_samples.append(wrap(sol['move_xyrz'][3]-pose['Rz']))
                run.say(f'Stationary yaw review {len(yaw_samples)}/{YAW_SAMPLES}: '
                        f'{yaw_samples[-1]:+.3f} deg')
                if len(yaw_samples) < YAW_SAMPLES:
                    continue
                delta = confirmed_yaw(yaw_samples)
                yaw_samples.clear()
                yaw_pose = None
                if delta is None:
                    run.say('Yaw samples disagree or straddle tolerance; stay still and recheck', 'warn')
                    continue
                legs = camera_plan(pose, sol, q, params, svc.envelope,
                                   yaw_target=pose['Rz']+delta)
                phase = [(kind,p) for kind,p in legs if kind in ('orientation','rotation')]
            if phase:
                # Repeated improving corrections are allowed; detect worsening
                # confirmed yaw instead of stopping after two orientation phases.
                yaw_errors.append(abs(delta))
                del yaw_errors[:-3]
                if (len(yaw_errors) == 3
                        and yaw_errors[-1] > yaw_errors[-2] + RZ_TOL_DEG
                        and yaw_errors[-2] > yaw_errors[-3] + RZ_TOL_DEG):
                    raise TransferError('confirmed yaw error increasing; inspect disk or calibration')
                run.say('Safe-height orientation phase; each segment checked, then re-detect')
                errors.clear()
            else:
                phase = legs[:1]
            if not phase:
                raise TransferError('non-converged solve requests no motion; inspect calibration')
            for kind, point in phase:
                guard._preflight()
                if moves == 0:
                    telemetry = guard.torque_report()
                    number(telemetry.get('e1_position'), 'E1 position')
                    if number(telemetry.get('e1_torque'), 'E1 torque') <= -100:
                        raise TransferError('gripper may be holding an object; calibration requires empty jaws')
                current = guard.pose_mm()
                distance = math.dist([current[k] for k in ('X','Y','Z')],
                                     [point[k] for k in ('X','Y','Z')])
                move_started = time.monotonic()
                if kind == 'rotation':
                    if any(abs(current[k]-point[k]) > 0.1 for k in ('X','Y','Z')):
                        raise TransferError('rotation start drifted from planned XYZ; no motion')
                    run.say(f"Wrist-only MoveJ: Rz {point['Rz']:.2f} @ {SPEED}; XYZ fixed")
                    guard.rotate_to_rz(point['Rz'])
                else:
                    run.say(f"Camera MoveL: X {point['X']:.2f} Y {point['Y']:.2f} "
                            f"Z {point['Z']:.2f} Rz {point['Rz']:.2f} @ {SPEED}")
                    guard.move_cartesian(point['X'], point['Y'], point['Z'], point['Rz'], SPEED, 'linear')
                run.say(f'{kind} segment arrived in {time.monotonic()-move_started:.2f} s')
                moves += 1
                travel += distance
            yaw_samples.clear()
            yaw_pose = None
        guard._preflight()
        # Both solves have individually passed full vendor convergence tolerances.
        sol = stable[-1]
        g = [sum(s['grasp_estimate'][i] for s in stable)/2 for i in range(3)]
        rz = stable[0]['grasp_estimate'][3]
        rz = wrap(rz + wrap(sol['grasp_estimate'][3]-rz)/2)
        cal = sol['z_calibration_applied']
        target = dict(x=g[0], y=g[1], z=g[2], rz=rz, z_calibrated=g[2]+cal,
                      config=pinned, big_r=sol['big_r'], found_at=time.strftime('%H:%M:%S'),
                      calibrated_at=time.time(), source='fast_disk', converged=True,
                      alignment_requires_preflight=True)
        warnings = []
        for key, value in (('X', target['x']), ('Y', target['y']), ('Z', target['z_calibrated'])):
            lo, hi = svc.envelope[key]
            if not lo <= value <= hi:
                warnings.append(f'Future grasp {key}={value:.2f} outside current envelope [{lo:g}, {hi:g}]; '
                                'calibration only, Align/Descend require separate validation')
        zs = [s['grasp_estimate'][2] for s in stable]
        target['z_detail'] = dict(samples=zs, spread=max(zs)-min(zs), vision_z=g[2], touch_offset=cal)
        for warning in warnings:
            run.say(warning, 'warn')
        run.target = target
        elapsed = round(time.monotonic()-started, 3)
        run.say(f'CALIBRATED: {observations} views, {moves} moves, {elapsed:.1f} s. '
                'Review target, then Align separately. No descent or grip.', 'good')
        return dict(ok=True, target=target, warnings=warnings, observations=observations,
                    moves=moves, elapsed_s=elapsed, travel_mm=round(travel, 3))
    except (TransferError, ValueError, KeyError, TypeError, RuntimeError) as ex:
        run.target = None
        run.state = 'stopped' if run.stopped() else 'error'
        run.say(str(ex), 'err')
        return dict(ok=False, error=str(ex), observations=observations, moves=moves)

# ===========================================================================
# 2. GOALS, STEPS AND CONVERGENCE
# ===========================================================================

def camera_goal(pose, sol):
    """Compose BOTH vendor corrections, matching teach._compute's conv_full."""
    c, z = sol['move_xyrz'], sol['move_z']
    return dict(X=number(c[0], 'camera X'), Y=number(c[1], 'camera Y'),
                Z=number(c[2], 'camera Z') + number(z[2], 'height correction') - pose['Z'],
                Rz=pose['Rz'] + wrap(number(c[3], 'camera yaw') - pose['Rz']))


def center_before_yaw(pose, sol):
    """Defer small wrist changes until fixed-wrist XY/height have settled."""
    delta = abs(wrap(sol['move_xyrz'][3] - pose['Rz']))
    return (delta <= COARSE_YAW_DEG
            and (sol['center_err_mm'] >= YAW_REVIEW_XY_MM
                 or sol['z_err_mm'] >= YAW_REVIEW_Z_MM))


def confirmed_yaw(deltas):
    """Three consistent signed corrections, not one noisy threshold crossing."""
    if len(deltas) != YAW_SAMPLES:
        return None
    # Unwrap near the first measurement to handle the +/-180 boundary.
    ds = [deltas[0] + wrap(d-deltas[0]) for d in deltas]
    if max(ds)-min(ds) > YAW_SPREAD_DEG:
        return None
    if not (all(d >= RZ_TOL_DEG for d in ds) or all(d <= -RZ_TOL_DEG for d in ds)):
        return None
    return wrap(statistics.median(ds))


def camera_plan(pose, sol, joints, params, envelope, *, center_first=False, yaw_target=None):
    """Preflight the full CAMERA route; never test grasp Z against this box.

    Rotation: lift, rotate in place, then go to the corrected camera height
    if it is higher than the starting height. Never descend below the starting
    observation height without fresh feedback. Translation follows a fixed-yaw
    MoveL. Every segment preserves the live IK branch.
    Returns the rotation phase and bounded feedback-translation segments.
    """
    goal = camera_goal(pose, sol)
    if center_first:
        # move_xyrz's XY assumes the full yaw correction. At fixed wrist use
        # the SDK's pure-translation correction, NOT that virtual-rotation XY.
        c = sol['move_center']
        goal = dict(X=number(c[0], 'center X'), Y=number(c[1], 'center Y'),
                    Z=number(sol['move_z'][2], 'camera height'), Rz=pose['Rz'])
    elif yaw_target is not None:
        # Only the orientation phase is executed from this median yaw. Its
        # completion is followed by a fresh solve, not stale XY/grasp execution.
        goal['Rz'] = pose['Rz'] + wrap(number(yaw_target, 'confirmed yaw')-pose['Rz'])
    p, q, legs = dict(pose), dict(joints), []

    def leg(end, phase):
        nonlocal p, q
        start = dict(p)
        delta = wrap(end['Rz'] - start['Rz'])
        n = max(1, math.ceil(math.hypot(end['X']-p['X'], end['Y']-p['Y']) / XY_STEP_MM),
                math.ceil(abs(end['Z']-p['Z']) / Z_STEP_MM),
                math.ceil(abs(delta) / ROTATE_STEP_DEG))
        if n > 100:
            raise TransferError('camera correction is too large; reposition manually')
        for i in range(1, n+1):
            point = {k: start[k] + (end[k]-start[k])*i/n for k in ('X', 'Y', 'Z')}
            point['Rz'] = start['Rz'] + delta*i/n
            q = check_path(p, point, q, params, envelope)
            if any(abs(point[k]-p[k]) > 1e-6 for k in point):
                legs.append((phase, point))
            p = point

    if abs(wrap(goal['Rz'] - p['Rz'])) >= RZ_TOL_DEG:
        observation_z = max(pose['Z'], goal['Z'])
        height = max(ROTATE_Z_MM, observation_z)
        leg({**p, 'Z': height}, 'orientation')
        leg({**p, 'Rz': goal['Rz']}, 'rotation')
        leg({**p, 'Z': observation_z}, 'orientation')
    # Ignore sub-tolerance yaw noise; never ride wrist rotation down near objects.
    leg({**goal, 'Rz': p['Rz']}, 'feedback')
    return legs


def route_cost(pose, legs):
    cost = 0.0
    for _, p in legs:
        cost += math.dist([pose[k] for k in ('X','Y','Z')], [p[k] for k in ('X','Y','Z')])
        cost += abs(wrap(p['Rz']-pose['Rz']))  # ranking heuristic, not seconds
        pose = p
    return cost


def validate_solve(sol):
    for key in ('xy_err_mm', 'center_err_mm', 'z_err_mm', 'rz_err_deg', 'big_r', 'small_r'):
        if number(sol.get(key), key) < 0:
            raise TransferError(f'invalid {key}')
    for key in ('move_xyrz', 'move_center', 'move_z', 'grasp_estimate'):
        if len(sol.get(key, [])) != 4:
            raise TransferError(f'invalid {key}')
        for value in sol[key]:
            number(value, key)
    number(sol.get('z_calibration_applied'), 'disk touch-offset calibration')
    if sol['big_r'] <= 0 or sol['small_r'] <= 0:
        raise TransferError('invalid circle radius')


def converged(sol):
    return (sol['xy_err_mm'] < XY_TOL_MM and sol['z_err_mm'] < Z_TOL_MM
            and sol['rz_err_deg'] < RZ_TOL_DEG)


def agree(a, b):
    ga, gb = a['grasp_estimate'], b['grasp_estimate']
    return (math.dist(ga[:2], gb[:2]) <= 1.0 and abs(ga[2]-gb[2]) <= 1.0
            and abs(wrap(ga[3]-gb[3])) <= 0.5)

# ===========================================================================
# 3. READINESS, POSE UNITS, PATH CHECKS AND GUARDED MOVEMENT
# ===========================================================================

class TransferError(ValueError):
    pass


def number(value, name):
    if isinstance(value, bool):
        raise TransferError(f"{name} must be a finite number")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise TransferError(f"{name} must be a finite number") from None
    if not math.isfinite(value):
        raise TransferError(f"{name} must be a finite number")
    return value


def wrap(angle):
    return (angle + 180) % 360 - 180


def near(angle, reference):
    return reference + wrap(angle - reference)


def controller_pose_mm(raw: dict) -> dict:
    """Pose in mm/deg — the only units ever fed back into moves."""
    out = {}
    for k, v in raw.items():
        if k in ("X", "Y", "Z"):
            out[k] = round(v * 1000.0, 3)
        elif k in ("Rx", "Ry", "Rz"):
            out[k] = round(math.degrees(v), 3)
    return out


def controller_preflight(robot) -> str | None:
    if not robot.connected:
        return "not connected — press Connect first"
    errors = robot.get_robot_errors()
    if errors:
        return ("robot has active errors, refusing to move: "
                f"{errors} — resolve the cause, then Clear errors "
                "(operator-confirmed)")
    if robot.get_ctrl_mode()["mode"] != "auto":
        return "robot is in manual mode — switch to auto first"
    if not robot.get_enable_status():
        return "robot is disabled — Enable first (operator-confirmed)"
    prog = robot.get_prog_state()
    if prog["state"] != "running":
        return f"Lua program is '{prog['state']}' — Start program first"
    if not robot.get_lua_app_status():
        return "Lua app reports uninitialized — wait or restart the program"
    return None


def ik(x, y, reference, params):
    """Both planar IK branches; unwrap onto the current physical winding."""
    x -= params["base_x_mm"]
    y -= params["base_y_mm"]
    a, b = params["link1_mm"], params["link2_mm"]
    r = math.hypot(x, y)
    if r < 20 or r > a + b - params["extension_margin_mm"] - 2:
        raise TransferError("path enters the folded/extended singularity margin")
    c = (r*r - a*a - b*b) / (2*a*b)
    if abs(c) >= 1:
        raise TransferError("unreachable path")
    candidates = []
    for sign in (-1, 1):
        beta = sign * math.acos(c)
        q2 = math.degrees(math.atan2(y, x) - math.atan2(b*math.sin(beta), a+b*math.cos(beta))) - params["j2_offset_deg"]
        q3 = math.degrees(beta) - params["j3_offset_deg"] + params["j2_offset_deg"]
        candidates.append((near(q2, reference[0]), near(q3, reference[1])))
    return min(candidates, key=lambda q: sum((q[i]-reference[i])**2 for i in (0, 1)))


def check_path(start, end, joints, params, envelope):
    """Sample a MoveL in TCP space, maintaining the measured J2/J3 branch.

    This checks calibrated planar reach, envelope and wrist headroom, NOT
    mesh collisions or all controller constraints. No joint-interp shortcuts.
    """
    start = {k: number(start[k], k) for k in ("X", "Y", "Z", "Rz")}
    end = {k: number(end[k], k) for k in start}
    q2, q3, q4 = (number(joints.get(k), k) for k in ("J2", "J3", "J4"))
    fit = ik(start["X"], start["Y"], (q2, q3), params)
    if max(abs(fit[0]-q2), abs(fit[1]-q3)) > 2:
        raise TransferError("live joints disagree with calibrated XY model; no motion")
    delta = wrap(end["Rz"]-start["Rz"])
    if abs(delta) >= 179:
        raise TransferError("ambiguous 180-degree wrist path; choose another orientation")
    n = max(1, math.ceil(max(abs(end[k]-start[k]) for k in ("X", "Y", "Z"))/2), math.ceil(abs(delta)))
    if n > 5000:
        raise TransferError("path is too large")
    q2prev, q3prev = q2, q3
    q4end = q4
    for i in range(n+1):
        f = i/n
        p = {k: start[k]+(end[k]-start[k])*f for k in ("X", "Y", "Z")}
        for axis in p:
            if not envelope[axis][0] <= p[axis] <= envelope[axis][1]:
                raise TransferError(f"path outside {axis} envelope")
        a, b = ik(p["X"], p["Y"], (q2prev, q3prev), params)
        if max(abs(a-q2prev), abs(b-q3prev)) > 10:
            raise TransferError("path changes IK branch or nears a singularity")
        # symmetric: the controller faults at J2 ~+/-95 (fault 3571), hit
        # live on BOTH sides 2026-09-14 — a lower-bound-only check missed
        # the +95 side and let the controller fault there instead
        j2_bound = abs(params["j2_min_deg"]) - params["j2_margin_deg"]
        if abs(a) > j2_bound:
            raise TransferError(f"path crosses J2 limit (predicted {a:.1f} deg, "
                                f"limit +/-{j2_bound:.1f})")
        q4end = q4 + f*delta - (a+b-q2-q3)
        limit = min(params["j4_pref_abs_deg"], params["j4_hard_abs_deg"]-5)
        if abs(q4end) > limit:
            raise TransferError(f"path requires J4 {q4end:.1f} deg; automatic headroom is +/-{limit:g}. Reposition manually")
        q2prev, q3prev = a, b
    return {**joints, "J2": q2prev, "J3": q3prev, "J4": q4end}


def ensure_arrival(actual, target):
    for key in ("X", "Y", "Z", "Rz"):
        d = number(actual.get(key), f"measured {key}") - target[key]
        if key == "Rz":
            d = wrap(d)
        if abs(d) > (0.5 if key == "Rz" else 1.0):
            raise TransferError(f"arrival mismatch: {key} {actual[key]} vs {target[key]}; no retry")


class GuardedService:
    """Recheck before EVERY step; reject recovered/uncertain acknowledgements."""
    def __init__(self, service, run, params):
        self.service, self.run, self.params = service, run, params
        self.holding = False

    def _preflight(self):
        if self.run.stopped():
            raise TransferError("stopped between steps; use hardware E-stop for immediate stop")
        if not self.service.envelope_enabled:
            raise TransferError("enable and verify the workspace envelope before automatic transfer")
        refusal = self.service._preflight()
        if refusal:
            raise TransferError(refusal)
        return None

    def pose_mm(self):
        self._preflight()
        return self.service.pose_mm()

    @staticmethod
    def checked(result):
        if not result.get("ok") or result.get("recovered") or result.get("gripper_warning"):
            raise TransferError(str(result.get("error") or result.get("gripper_warning") or "connection recovery during transfer; inspect before retry"))
        return result

    def move_cartesian(self, x, y, z, rz, speed=10, interpolation="linear"):
        self._preflight()
        if interpolation != "linear":
            raise TransferError("automatic transfer only supports checked linear paths")
        target = dict(X=x, Y=y, Z=z, Rz=rz)
        check_path(self.service.pose_mm(), target, self.service.joints() or {}, self.params, self.service.envelope)
        result = self.checked(self.service.move_cartesian(x, y, z, rz, min(speed, 15), "linear"))
        self._preflight()
        ensure_arrival(self.service.pose_mm(), target)
        return result

    def move_gripper(self, target):
        self._preflight()
        result = self.checked(self.service.move_gripper(target))
        g = result.get("gripper", {})
        for key in ("e1_position", "e1_torque", "position_error"):
            number(g.get(key), key)
        self._preflight()
        return result

    def torque_report(self):
        self._preflight()
        result = self.checked(self.service.torque_report())
        if not result.get("telemetry_live"):
            raise TransferError("live J1-J4 torque telemetry required")
        for key in ("J1", "J2", "J3", "J4"):
            number(result.get("joints", {}).get(key), key+" torque")
        if self.holding and number(result.get("e1_torque"), "hold torque") >= -100:
            raise TransferError("holding torque lost; no further motion or release")
        return result


class DiskGuard(GuardedService):
    """Disk-only pure-wrist exception; translations still require MoveL."""

    rotation_speed = SPEED

    def rotate_to_rz(self, rz):
        self._preflight()
        start = self.service.pose_mm()
        # Arrival telemetry is rounded to 0.001 mm. This is only a 0.05 mm
        # measurement tolerance, not permission for a low-height wrist sweep.
        if number(start['Z'], 'rotation height') < ROTATE_Z_MM - 0.05:
            raise TransferError('disk wrist rotation requires TCP Z >=300 mm')
        delta = wrap(number(rz, 'rotation yaw') - start['Rz'])
        if abs(delta) > ROTATE_STEP_DEG + 0.05:
            raise TransferError('disk wrist rotation exceeds the 10-degree segment limit')
        # Only yaw is passed to the dedicated service method: it pins XYZ to
        # live values. Never pass a translated target to joint interpolation.
        target = {**start, 'Rz': start['Rz'] + delta}
        expected = check_path(start, target, self.service.joints() or {},
                              self.params, self.service.envelope)
        result = self.checked(self.service.rotate_to_rz(target['Rz'], self.rotation_speed,
                                                       force_delta=delta))
        self._preflight()
        ensure_arrival(self.service.pose_mm(), target)
        actual = self.service.joints() or {}
        for key in ('J2', 'J3', 'J4'):
            if abs(number(actual.get(key), key) - expected[key]) > 0.5:
                raise TransferError(f'rotation joint arrival mismatch: {key}; no retry')
        return result

# ===========================================================================
# 4. VENDOR CONFIGURATION, IMAGE MEASUREMENTS AND POSE MATH
# ===========================================================================

def _configs():
    global _cfgs
    if _cfgs is None:
        _cfgs = load_configs()
    return _cfgs


def cfg_geometry(name: str) -> dict:
    """Vendor geometry constants for one trigger config — what the anchor
    rows need: the taught optical distance (H at the taught view), the
    taught circle radius (for H-from-radius at a live capture) and the
    taught mark pixel."""
    cfg = next(c for c in _configs() if c["name"] == name)
    return {"dis_mm": float(cfg["cal_tab_raw"][5]) * 1000.0,
            "model_radius": float(cfg["model_radius"]),
            "model_mark_img": [float(v) for v in cfg["model_mark_img"]]}


def z_calibration() -> float | None:
    """z_touch_offset from grab_skill/calibration.json — the measured gap
    between vision grasp Z and the physically touchable depth. NO safety
    margin is added: the operator wants the true value published
    (2026-07-23); the torque-guarded descent is the surface protection."""
    if not os.path.exists(CAL_PATH):
        return None
    c = json.load(open(CAL_PATH, encoding="utf-8-sig"))
    return float(c["z_touch_offset_mm"])


def _rot(a, b, g):
    a, b, g = np.radians([a, b, g])
    Rx = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    Ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
    Rz = np.array([[np.cos(g), -np.sin(g), 0], [np.sin(g), np.cos(g), 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def _to_euler(R):
    sy = np.hypot(R[0, 0], R[1, 0])
    if sy > 1e-6:
        rx = np.arctan2(R[2, 1], R[2, 2])
        ry = np.arctan2(-R[2, 0], sy)
        rz = np.arctan2(R[1, 0], R[0, 0])
    else:
        rx = np.arctan2(-R[1, 2], R[1, 1])
        ry = np.arctan2(-R[2, 0], sy)
        rz = 0.0
    return np.degrees([rx, ry, rz])


def _norm360(a):
    while a > 360.0:
        a -= 360.0
    while a < 0.0:
        a += 360.0
    return a


def compose(p1, p2):
    p1, p2 = np.asarray(p1, float), np.asarray(p2, float)
    R1 = _rot(p1[3], p1[4], p1[5])
    R = R1 @ _rot(p2[3], p2[4], p2[5])
    t = R1 @ p2[:3] + p1[:3]
    e = _to_euler(R)
    return np.array([t[0], t[1], t[2], _norm360(e[0]), _norm360(e[1]), _norm360(e[2])])


def invert(p):
    p = np.asarray(p, float)
    T = np.eye(4)
    T[:3, :3] = _rot(p[3], p[4], p[5])
    T[:3, 3] = p[:3]
    Ti = np.linalg.inv(T)
    e = _to_euler(Ti[:3, :3])
    return np.array([Ti[0, 3], Ti[1, 3], Ti[2, 3], e[0], e[1], e[2]])


def wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


def _arr(s):
    return np.array([float(v) for v in s.split(",")], float)


def load_configs():
    cfgs = []
    for name, path in CFG_DIRS:
        j = json.load(open(path, encoding="utf-8"))
        cam_in_tool = _arr(j["CamInTool"]["data"])[:6]
        cal_tab = _arr(j["CalTabInCam"]["data"])[:6]
        cfgs.append({
            "name": name,
            "model_mark_img": _arr(j["ModelMarkInImage"]["data"]),   # u, v, ang
            "model_mark_robot": _arr(j["ModelMarkInRobot"]["data"])[:6],
            "model_radius": float(j["ModelMarkRadius"]["data"]),
            "teach_in_trigger": _arr(j["TeachInTrigger"]["data"])[:6],
            "cam_param": _arr(j["CamParam"]["data"]),
            "cam_in_tool_raw": cam_in_tool,     # stored (rx,ry,rz, x,y,z)
            "cal_tab_raw": cal_tab,             # stored (rx,ry,rz, x,y,z[m])
        })
    return cfgs


def _swap(p):
    """SwapFirstAndLastThree: stored (r..., t...) -> pose (t..., r...)."""
    return np.concatenate([p[3:6], p[0:3]])


def sdk_detect(img_path):
    """FindWellPlateLabel: exact Hough params + pair rule. Angle in [0,360).

    Brightness normalization stands in for the SDK's hardware auto-exposure:
    it targets the same 128-180 ROI-mean window the VisionServer regulates to
    (digital gain toward the window midpoint when the frame is outside it).
    """
    raw = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if raw is None:
        return None
    h, w = raw.shape
    roi = raw[int((h - h / 1.1) / 2):int((h + h / 1.1) / 2),
              int((w - w / 1.5) / 2):int((w + w / 1.5) / 2)]
    mean = float(roi.mean())
    # escalate like the SDK's exposure-increment loop: brighter passes within
    # its accepted 128-180 window until the pair is found
    for target in (mean if 128.0 <= mean <= 180.0 else 154.0, 175.0, 200.0):
        img = (raw if abs(target - mean) < 1.0 else
               np.clip(raw.astype(np.float32) * (target / mean), 0, 255).astype(np.uint8))
        result = _detect_pair(img)
        if result is not None:
            return result
    return None


def _detect_pair(img):
    m = cv2.GaussianBlur(img, (11, 11), 5)
    cs = cv2.HoughCircles(m, cv2.HOUGH_GRADIENT, 1.5, 500,
                          param1=50, param2=150, minRadius=50, maxRadius=300)
    if cs is None:
        return None
    cs = cs[0]
    pair = None
    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            a, b = cs[i], cs[j]
            big, small = (a, b) if a[2] >= b[2] else (b, a)
            sep = math.hypot(big[0] - small[0], big[1] - small[1])
            if 400 < sep < 900 and 1.2 < big[2] / small[2] < 3.0:
                pair = (big, small)
                break
        if pair:
            break
    if not pair:
        return None
    big, small = pair
    ang = math.degrees(math.atan2(small[1] - big[1], small[0] - big[0]))
    if ang < 0:
        ang += 360.0
    return {"mark": [float((big[0] + small[0]) / 2), float((big[1] + small[1]) / 2), ang],
            "big_r": float(big[2]), "small_r": float(small[2]),
            "big_c": [float(big[0]), float(big[1])],
            "small_c": [float(small[0]), float(small[1])]}


def image_points_to_world_plane(cam_param, cal_tab_pose_mm, px, py):
    """ImagePointsToWorldPlane, with CalTab translation already in mm."""
    f = cam_param[0] * 1000.0
    sx = cam_param[6] * 1000.0
    sy = cam_param[7] * 1000.0
    cx, cy = cam_param[8], cam_param[9]
    dist = np.array([cam_param[1] * f**2, cam_param[2] * f**4,
                     cam_param[5] * f, cam_param[4] * f, cam_param[3] * f**6])
    K = np.array([[f / sx, 0, cx], [0, f / sy, cy], [0, 0, 1.0]])
    und = cv2.undistortPoints(np.array([[[px, py]]], np.float32), K, dist)
    nx, ny = float(und[0, 0, 0]), float(und[0, 0, 1])
    a, b, g = cal_tab_pose_mm[3], cal_tab_pose_mm[4], cal_tab_pose_mm[5]
    t = cal_tab_pose_mm[:3]
    Rm = _rot_euler(a, b, g)
    ray = np.linalg.inv(Rm) @ np.array([nx, ny, 1.0])
    s = -t[2] / ray[2]
    return np.array([-s * ray[0] + t[0], -s * ray[1] + t[1], 0.0])


def _rot_euler(a, b, g):
    a, b, g = np.radians([a, b, g])
    Rx = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    Ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
    Rz = np.array([[np.cos(g), -np.sin(g), 0], [np.sin(g), np.cos(g), 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def trans_img_pos_2_world(cfg, px, py):
    """TransImgPos2World -> mark position in the TOOL frame (mm)."""
    cal_tab = _swap(cfg["cal_tab_raw"].copy())
    cal_tab[:3] *= 1000.0                     # meters -> mm (verified vs logs)
    cam_in_tool = _swap(cfg["cam_in_tool_raw"].copy())
    point = image_points_to_world_plane(cfg["cam_param"], cal_tab, px, py)
    hom = compose(cam_in_tool, cal_tab)
    R = _rot_euler(hom[3], hom[4], hom[5])
    return R @ point + hom[:3]


def mark_in_robot_pose(cfg, mark):
    """TransImgPos2Robot: (X,Y,Z, 0,0, -angle)."""
    X, Y, Z = trans_img_pos_2_world(cfg, mark[0], mark[1])
    return np.array([X, Y, Z, 0.0, 0.0, -mark[2]])


def calc_image_offset(cfg, mark):
    """CalcImageOffset: pixel dist + 5*|wrapped angle diff|."""
    mm = cfg["model_mark_img"]
    d = math.hypot(mark[0] - mm[0], mark[1] - mm[1])
    ad = mark[2] - mm[2]
    ad -= 360.0 * round(ad / 360.0)
    return d + 5.0 * abs(ad), d, abs(ad)


def select_trigger(cfgs, mark):
    """FindClosestMark."""
    best, best_err, details = None, float("inf"), []
    for i, c in enumerate(cfgs):
        err, d, ad = calc_image_offset(c, mark)
        details.append({"cfg": c["name"], "err": round(err, 1),
                        "px_dist": round(d, 1), "ang_diff": round(ad, 2)})
        if err < best_err:
            best_err, best = err, i
    return best, details


def tool_offset_xyrz(cfg, cur_mark_pose):
    """CalcToolOffsetXYRz: compose(curMark, invert(ModelMarkInRobot))."""
    return compose(cur_mark_pose, invert(cfg["model_mark_robot"]))


def tool_offset_z(cfg, big_r):
    """CalcToolOffsetZ via CalcCircleZOffset; Circle2CamDis in mm."""
    dis = cfg["cal_tab_raw"][5] * 1000.0      # 0.205 m -> 205 mm
    num = big_r - cfg["model_radius"]
    if abs(num) < 1.0:
        num *= 0.5
    z = -dis * num / (cfg["model_radius"] + num)
    off = np.zeros(6)
    off[2] = -z
    return off


def new_acc_pose(cur_pose, offset):
    """CalcNewAccPose (without the |X|>400 flip branch; radius guard external)."""
    p = compose(np.asarray(cur_pose, float), offset)
    if p[5] > 180.0:
        p[5] -= 360.0
    return p


def final_acc_pose(cfg, cur_pose):
    """CalcFinalAccPose: compose(curPose, TeachInTrigger)."""
    p = compose(np.asarray(cur_pose, float), cfg["teach_in_trigger"])
    if p[5] > 180.0:
        p[5] -= 360.0
    return p


def solve(img_path: str, x: float, y: float, z: float, rz: float,
          force_cfg: str | None = None) -> dict:
    """One teach iteration at the given current pose (mm/deg).

    Same fields as mcp_teach cmd_solve: detection, selected config,
    move_xyrz / move_z correction targets, errors, and the grasp pose
    (raw + Z-touch-calibrated).
    """
    cfgs = _configs()
    det = sdk_detect(img_path)
    if det is None:
        return {"detected": False}
    sel, details = select_trigger(cfgs, det["mark"])
    if force_cfg:
        sel = next(i for i, c in enumerate(cfgs) if c["name"] == force_cfg)
    return _compute(cfgs[sel], det, [x, y, z, 0.0, 0.0, rz], details)


def evaluate_ways(img_path: str, x: float, y: float, z: float,
                  rz: float) -> dict:
    """Evaluate every grasp way on one capture.

    Two convergence configs (Wide straddles the tray's short span, Long the
    long span) x two wrist sides each (the claw is symmetric about the tool
    axis, so the same grip point works with the wrist at Rz or Rz+180 —
    verified numerically; flipping the VISION model instead mirrors the
    grip about the mark and lands off the tray). Returns per-way radii so
    the caller can pick a physically reachable way and fall back.
    """
    cfgs = _configs()
    det = sdk_detect(img_path)
    if det is None:
        return {"detected": False}
    _, details = select_trigger(cfgs, det["mark"])
    ways = []
    for cfg in cfgs:
        s = _compute(cfg, det, [x, y, z, 0.0, 0.0, rz], details)
        c, g = s["move_xyrz"], s["grasp_estimate"]
        ways.append({
            "cfg": cfg["name"],
            "ang_diff": next(d["ang_diff"] for d in details
                             if d["cfg"] == cfg["name"]),
            "conv_radius": round(math.hypot(c[0], c[1]), 1),
            "grasp_radius": round(math.hypot(g[0], g[1]), 1),
            "grasp_rz": g[3],
            "grasp_rz_alt": round(wrap180(g[3] + 180.0), 2),
            "solve": s,
        })
    return {"detected": True, "mark": [round(float(v), 3)
                                       for v in det["mark"]],
            "big_r": round(float(det["big_r"]), 2), "ways": ways}


def _compute(cfg, det: dict, cur_pose: list, details: list) -> dict:
    cur_mark = mark_in_robot_pose(cfg, det["mark"])
    off_xyrz = tool_offset_xyrz(cfg, cur_mark)
    off_z = tool_offset_z(cfg, det["big_r"])
    move_xyrz = new_acc_pose(cur_pose, off_xyrz)
    move_z = new_acc_pose(cur_pose, off_z)
    # pure-translation target that puts the mark at its TAUGHT tool-frame
    # position (mark centered as taught) WITHOUT any wrist rotation.
    # move_xyrz's XY presumes the full rotation is also made — chasing it
    # with a capped wrist walks the mark out of the frame; this target is
    # reachable and keeps the mark in view at any Rz.
    mm = cfg["model_mark_robot"]
    dcx = float(cur_mark[0]) - float(mm[0])
    dcy = float(cur_mark[1]) - float(mm[1])
    off_c = np.zeros(6)
    off_c[0], off_c[1] = dcx, dcy
    move_center = new_acc_pose(cur_pose, off_c)
    center_err = float(np.hypot(dcx, dcy))
    grasp = final_acc_pose(cfg, cur_pose)
    # where the grasp will land once converged: apply BOTH measured
    # corrections to the current pose — XY/Rz from the mark AND the height
    # from the circle radius — then compose the trigger from there. Without
    # the height term the estimate inherits the camera's full remaining
    # z_err (Find corrects Z only after XY converges, so an early publish
    # was XY-tight but Z-blind).
    conv_full = np.array(move_xyrz, float).copy()
    conv_full[2] += float(move_z[2]) - float(cur_pose[2])
    grasp_est = final_acc_pose(cfg, conv_full)
    cal = z_calibration()
    return {
        "detected": True,
        "mark": [round(float(v), 3) for v in det["mark"]],
        "big_r": round(float(det["big_r"]), 2),
        "small_r": round(float(det["small_r"]), 2),
        "big_c": [round(float(v), 1) for v in det["big_c"]],
        "small_c": [round(float(v), 1) for v in det["small_c"]],
        "selection": details,
        "selected": cfg["name"],
        "z_calibration_applied": cal,
        "grasp_z_calibrated": (round(float(grasp_est[2]) + cal, 3)
                               if cal is not None else None),
        "move_xyrz": ([round(float(move_xyrz[i]), 3) for i in (0, 1, 2)]
                      + [round(wrap180(float(move_xyrz[5])), 4)]),
        "move_z": ([round(float(move_z[i]), 3) for i in (0, 1, 2)]
                   + [round(wrap180(float(move_z[5])), 4)]),
        "move_center": ([round(float(move_center[i]), 3) for i in (0, 1, 2)]
                        + [round(wrap180(float(move_center[5])), 4)]),
        "center_err_mm": round(center_err, 4),
        "grasp_if_converged": ([round(float(grasp[i]), 3) for i in (0, 1, 2)]
                               + [round(wrap180(float(grasp[5])), 4)]),
        "grasp_estimate": ([round(float(grasp_est[i]), 3) for i in (0, 1, 2)]
                           + [round(wrap180(float(grasp_est[5])), 4)]),
        "xy_err_mm": round(float(np.hypot(off_xyrz[0], off_xyrz[1])), 4),
        "rz_err_deg": round(abs(wrap180(float(off_xyrz[5]))), 4),
        "z_err_mm": round(abs(float(off_z[2])), 4),
    }


def annotate(img_path: str, sol: dict, max_edge: int = 1400) -> str:
    """Draw the detected circle pair + mark on the capture; returns the path
    of the annotated JPEG (browser-sized) for the console's detection panel."""
    img = cv2.imread(img_path)
    if img is None:
        raise RuntimeError(f"cannot read {img_path}")
    big = tuple(int(round(v)) for v in sol["big_c"])
    small = tuple(int(round(v)) for v in sol["small_c"])
    cv2.circle(img, big, int(round(sol["big_r"])), (0, 230, 0), 4)
    cv2.circle(img, small, int(round(sol["small_r"])), (0, 140, 255), 4)
    cv2.line(img, big, small, (0, 200, 255), 2)
    mark = (int(round(sol["mark"][0])), int(round(sol["mark"][1])))
    cv2.drawMarker(img, mark, (0, 0, 255), cv2.MARKER_CROSS, 60, 3)
    cv2.putText(img, f"ang {sol['mark'][2]:.1f} deg  bigR {sol['big_r']:.0f}px",
                (mark[0] + 30, mark[1] - 30), cv2.FONT_HERSHEY_SIMPLEX,
                1.4, (0, 0, 255), 3)
    h, w = img.shape[:2]
    scale = max_edge / max(h, w)
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)),
                         interpolation=cv2.INTER_AREA)
    out = os.path.splitext(img_path)[0] + "_det.jpg"
    cv2.imwrite(out, img)
    return out

# ===========================================================================
# 5. OFFLINE VALIDATION - no hardware connection
# ===========================================================================

def selftest() -> tuple[bool, str]:
    """Run mcp_teach's offline validation (cached). Must print ALL PASS."""
    global _selftest
    if _selftest is None:
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "test"],
            capture_output=True, text=True, timeout=120)
        out = (proc.stdout or "") + (proc.stderr or "")
        _selftest = ("ALL PASS" in out, out.strip())
    return _selftest


def cmd_test():
    cfgs = load_configs()
    wide = cfgs[0]
    ok = True

    # GT1 (run-8 VCS log): mark px (2291.25, 1138.5) -> tool (43.070, 97.400, -237.248)
    got = trans_img_pos_2_world(wide, 2291.25, 1138.5)
    want = np.array([43.070242385615, 97.3995933688142, -237.247873837359])
    e1 = np.abs(got - want).max()
    print(f"GT1 TransImgPos2World: got {np.round(got,3)} want {np.round(want,3)} "
          f"max err {e1:.4f} mm {'PASS' if e1 < 0.05 else 'FAIL'}")
    ok &= e1 < 0.05

    # GT2 (run-7 log, correctly paired): logged offset-15 applied to the logged
    # current pose must reproduce the logged "Robot move to" command:
    #   offset (41.6083, 6.8977, 0.0365, 0,0, 28.301329) at (305,-265,270,0,0,-110.0002)
    #   -> move to (297.2509, -306.4582, 270.0365, 0,0, -81.69867)
    off15 = np.array([41.6083279228099, 6.89773349721193, 0.0364955752026219,
                      0, 0, 28.301329])
    mv = new_acc_pose([305, -265, 270, 0, 0, -110.0002], off15)
    want2 = np.array([297.250862987777, -306.458202511643, 270.036495575203])
    e2 = max(np.abs(mv[:3] - want2).max(), abs(wrap180(mv[5]) - (-81.69867)))
    print(f"GT2 NewAccPose: got ({mv[0]:.4f},{mv[1]:.4f},{mv[2]:.4f},Rz {wrap180(mv[5]):.4f}) "
          f"want (297.2509,-306.4582,270.0365,Rz -81.6987) max err {e2:.4f} {'PASS' if e2 < 0.01 else 'FAIL'}")
    ok &= e2 < 0.01
    # GT2b round trip: tool_offset_xyrz(compose(off, model)) == off
    rt_mark = compose(off15, wide["model_mark_robot"])
    rt_off = tool_offset_xyrz(wide, rt_mark)
    e2b = max(np.abs(rt_off[:3] - off15[:3]).max(), abs(wrap180(rt_off[5]) - off15[5]))
    print(f"GT2b offset round-trip err {e2b:.2e} {'PASS' if e2b < 1e-9 else 'FAIL'}")
    ok &= e2b < 1e-9

    # GT3 (runs 7+8): compose((305,-265,270,0,0,-110.0002), Wide TeachInTrigger)
    #                 -> (219.732, -230.853, 46.407, Rz -28.1373)
    fp = final_acc_pose(wide, [305, -265, 270, 0, 0, -110.0002])
    want3 = np.array([219.731999558746, -230.853105884278, 46.407])
    e3 = max(np.abs(fp[:3] - want3).max(), abs(wrap180(fp[5]) - (331.8627 - 360)))
    print(f"GT3 FinalAccPose: got ({fp[0]:.4f},{fp[1]:.4f},{fp[2]:.4f},Rz {wrap180(fp[5]):.4f}) "
          f"want (219.7320,-230.8531,46.4070,Rz -28.1373) max err {e3:.4f} {'PASS' if e3 < 0.01 else 'FAIL'}")
    ok &= e3 < 0.01

    # GT4 (run-8 log): Z offset for bigR 185.9 -> -4.9623
    oz = tool_offset_z(wide, 185.899993896484)
    e4 = abs(oz[2] - (-4.9623455098853))
    print(f"GT4 ToolOffsetZ: got {oz[2]:.6f} want -4.962346 err {e4:.6f} {'PASS' if e4 < 1e-4 else 'FAIL'}")
    ok &= e4 < 1e-4

    print("ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1

# Backward-compatible teach.T access; functions above call each other directly.
T = sys.modules[__name__]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["test"], help="Run offline SDK math checks")
    parser.parse_args()
    sys.exit(cmd_test())
