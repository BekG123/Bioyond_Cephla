"""Background operator-triggered sequences for the S4 console.

Each sequence is a series of small envelope-checked steps with a stop flag
checked between every step, a live log the browser polls, and NO retries of
timed-out motion (an unknown-state error aborts the sequence and tells the
operator to re-check state).

Sequences:
  find_disk — the proven full-precision flow (validated live 2026-07-23
              against the vendor SDK): solve, ROTATE the wrist in place to
              the taught convergence angle (<=30 deg chunks, choosing the
              winding that keeps J4 off its ±220 soft limit), then iterate
              capture -> solve -> capped correction move until xy/rz/z all
              reach the detection noise floor. If the rotation swings the
              plate out of the frame, step toward the known convergence
              point to re-acquire it. Lost detections stay non-fatal
              (backtrack / opposite side / settle for the last good
              estimate). If NO safe J4 winding exists, falls back to
              centering the mark without rotation (the grasp estimate
              composes the virtual rotation and stays valid).
  align     — rotate Rz in place (<=30 deg joint chunks), then move linearly
              to the target X/Y at hover height.
  descend   — approach to target Z + 20, take a J1-J4 torque baseline, then
              step down 1.0/0.5 mm at speed 5 checking torque after every
              step; FIRST band breach stops, retreats 1 mm and classifies
              contact vs drift. Never grips on its own.
  grip      — torque-guided close (open -> step close until torque crossing);
              reopens if the floor is reached with nothing gripped.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time

TORQUE_CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "torque_config.json")
ROBOT_PARAMS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "robot_params.json")


def _robot_params() -> dict:
    """Arm-specific limits + planar kinematics from robot_params.json —
    every number here differs between arms; edit the file when porting,
    never the code. link1/link2 = 0 disables the kinematic model and
    falls back to the legacy origin-circle guards."""
    d = {"reach_hard_mm": 480.0, "j4_pref_abs_deg": 150.0,
         "j4_hard_abs_deg": 205.0, "inner_reach_mm": 280.0,
         "claw_gap_min_mm": 60.0, "claw_gap_max_mm": 88.0,
         "base_x_mm": 0.0, "base_y_mm": 0.0,
         "link1_mm": 0.0, "link2_mm": 0.0,
         "j2_offset_deg": 0.0, "j3_offset_deg": 180.0,
         "j2_min_deg": -999.0, "j2_margin_deg": 2.0,
         "extension_margin_mm": 15.0}
    try:
        j = json.load(open(ROBOT_PARAMS_PATH, encoding="utf-8-sig"))
        d.update({k: float(v) for k, v in j.items() if k in d})
    except Exception:  # noqa: BLE001
        pass
    return d


_RP = _robot_params()


def _kinematics_on() -> bool:
    return _RP["link1_mm"] > 0 and _RP["link2_mm"] > 0


def _ik_j2j3(x: float, y: float):
    """Exact planar IK on the fitted model (our elbow branch — the one all
    live poses use: J3 in (-180, 0)). Returns (J2, J3) in degrees, or None
    when the kinematic block is unconfigured or the point lies beyond full
    extension. Fitted 2026-07-28 with 0.00 mm residual over 8 live poses;
    reproduced the live J2 soft-limit stop (-95.10) to the decimal."""
    if not _kinematics_on():
        return None
    l1, l2 = _RP["link1_mm"], _RP["link2_mm"]
    px, py = x - _RP["base_x_mm"], y - _RP["base_y_mm"]
    r2 = px * px + py * py
    c = (r2 - l1 * l1 - l2 * l2) / (2.0 * l1 * l2)
    if abs(c) > 1.0:
        return None
    g = math.degrees(math.acos(c))          # + branch = observed elbow side
    alpha = math.degrees(math.atan2(
        l2 * math.sin(math.radians(g)),
        l1 + l2 * math.cos(math.radians(g))))
    phi = math.degrees(math.atan2(py, px))
    j2 = _wrap180(phi - alpha - _RP["j2_offset_deg"])
    j3 = _wrap180(g - (_RP["j3_offset_deg"] - _RP["j2_offset_deg"]))
    return j2, j3


def _extension_mm(x: float, y: float) -> float:
    """Distance from the J2 axis (NOT the world origin) — the quantity the
    arm's physical extension actually limits."""
    return math.hypot(x - _RP["base_x_mm"], y - _RP["base_y_mm"])


def _reach_block(x: float, y: float):
    """Why (x, y) is kinematically unreachable, or None if it is fine.
    With the fitted model: exact extension circle around the base + the
    measured J2 soft limit (fault 3571 froze J2 at -95.10 live). Without
    it: the legacy origin-circle guard."""
    if _kinematics_on():
        lim = _RP["link1_mm"] + _RP["link2_mm"] - _RP["extension_margin_mm"]
        ext = _extension_mm(x, y)
        if ext > lim - REACH_MARGIN_MM:
            return (f"extension {ext:.1f} mm from the arm base exceeds "
                    f"{lim - REACH_MARGIN_MM:.0f} (full stretch "
                    f"{_RP['link1_mm'] + _RP['link2_mm']:g} minus tracking "
                    "margin — controller faults 3570 out there)")
        ik = _ik_j2j3(x, y)
        if ik is None:
            return "no IK solution"
        j2_lim = _RP["j2_min_deg"] + _RP["j2_margin_deg"]
        if _RP["j2_min_deg"] > -900 and ik[0] < j2_lim:
            return (f"predicted J2 {ik[0]:.1f} deg is below the soft limit "
                    f"{_RP['j2_min_deg']:g} (+{_RP['j2_margin_deg']:g} "
                    "margin — fault 3571 territory)")
        return None
    if math.hypot(x, y) > REACH_HARD_MM - REACH_MARGIN_MM:
        return (f"radius {math.hypot(x, y):.1f} beyond the legacy reach "
                f"guard {REACH_HARD_MM:g}")
    return None


def band_floor() -> float:
    """Descent-guard band floor: the operator-picked deviation from the
    torque-feedback tab (torque_config.json), else the default MIN_BAND."""
    try:
        c = json.load(open(TORQUE_CFG_PATH, encoding="utf-8-sig"))
        v = float(c.get("band_counts", 0))
        return v if v > 0 else MIN_BAND
    except Exception:  # noqa: BLE001
        return MIN_BAND

# convergence thresholds from the validated grab pipeline (XY/Z only —
# the wrist is not rotated during Find, so Rz convergence does not apply)
XY_CONV_MM = 0.3
Z_CONV_MM = 0.3
MAX_ITERS = 25
DETECT_RETRIES = 3

# the disk is PLACED under the eye cam before Find is pressed — the sequence
# never searches. Flow: pin a grasp way, rotate in place to its taught
# convergence angle (J4-winding aware), then plan steps toward the solve
# target dynamically: proportional to the remaining error, shrunk or slid
# along the feasible boundary when blocked, and a travel budget derived
# from the first detection instead of a fixed bound. Losing the disk is
# recovered, not fatal: post-rotation, step toward the known convergence
# point; otherwise back to the last-seen position, then the opposite
# direction, and finally settle for the last good solve's estimate.
STEP_MIN_MM = 2.0        # never plan below this (detection noise floor)
STEP_MAX_MM = 40.0       # single-move ceiling, even far from the target
STEP_FRACTION = 0.6      # fraction of the remaining distance per move
DIRECT_STEP_MM = 25.0    # this close -> apply the full correction at once
RZ_CONV_DEG = 0.2        # wrist convergence threshold (rotation mode)
ROTATE_MIN_DEG = 2.0     # pending rotation above this -> explicit in-place
                         # rotation phase (<=30 deg chunks, J4-aware)
J4_PREF_ABS = _RP["j4_pref_abs_deg"]   # prefer windings landing |J4| under
                                       # this (margin for the translation)
J4_HARD_ABS = _RP["j4_hard_abs_deg"]   # refuse beyond this (controller
                                       # faults near the wrist soft limit)
RZ_RIDE_CAP = 10.0       # max Rz correction riding along one linear move
Z_RIDE_MAX = 15.0        # max height change riding along one move — a bad
                         # radius read must never become one big Z plunge
Z_REFINE_MM = 10.0       # after converge/settle: hop this far up, re-sample
                         # the radius-derived height, hop back, sample again
MAX_RECOVERIES = 6       # lost-plate recovery moves (back / other way)
CENTER_CONV_MM = 1.0     # centering FALLBACK (rotation blocked): mark
                         # within this of its taught spot = converged
RZ_CENTER_MODE = 8.0     # pending rotation beyond this cannot be chased
                         # unrotated (offset camera orbits away) — only
                         # relevant when no safe J4 winding exists
REACH_MARGIN_MM = 2.0    # stay this far inside the hard reach circle

# NOT a soft limit: the arm's elbow goes straight at ~this radius and the
# controller faults (3570, singularity/unreachable) regardless of any
# envelope setting — planning around it turns a hardware fault into advice.
# Value comes from robot_params.json (arm-specific).
REACH_HARD_MM = _RP["reach_hard_mm"]


def _wrap180(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def _j4_safe_delta(svc, delta: float):
    """Pick the wrist winding for an in-place rotation from live joint
    state. An in-place Rz rotation moves J4 by exactly the commanded delta
    on this arm, so the landing is computed dynamically: live J4 + each
    candidate winding. Prefer the short way when its landing leaves
    translation margin (|J4| <= J4_PREF_ABS), otherwise the winding with
    the smaller |landing|; refuse only landings past J4_HARD_ABS (the
    controller faults ~±220). Returns (delta, note); delta None = no safe
    winding. Unknown joints -> short way with a note."""
    j = svc.joints()
    if j is None:
        return delta, "joint read unavailable — assuming short-way is safe"
    j4 = float(j.get("J4", 0.0))
    alt = delta - math.copysign(360.0, delta) if abs(delta) > 1e-9 else delta
    land_s, land_a = j4 + delta, j4 + alt
    if abs(land_s) <= J4_PREF_ABS:
        return delta, ""
    pick, land = ((alt, land_a) if abs(land_a) < abs(land_s)
                  else (delta, land_s))
    if abs(land) > J4_HARD_ABS:
        return None, (f"no safe wrist winding: J4 {j4:.0f} deg, short-way "
                      f"lands {land_s:.0f}, long-way {land_a:.0f} "
                      f"(hard limit ±{J4_HARD_ABS:g})")
    note = ""
    if pick is alt:
        note = (f"short-way rotation would park J4 at {land_s:.0f} deg — "
                f"winding the other way ({alt:+.0f} deg, lands "
                f"{land_a:.0f})")
    elif abs(land) > J4_PREF_ABS:
        note = (f"rotation lands J4 at {land:.0f} deg — inside limits but "
                "little margin for the translation that follows")
    return pick, note


def _feasible(svc, x: float, y: float, z: float) -> bool:
    """Can the tool stand at (x, y, z)? Kinematic reach (extension circle
    around the BASE + J2 limit — physics, always on); box if armed."""
    if _reach_block(x, y) is not None:
        return False
    if svc.envelope_enabled:
        for axis, v in (("X", x), ("Y", y), ("Z", z)):
            lo, hi = svc.envelope[axis]
            if not (lo <= v <= hi):
                return False
    return True


def _project_feasible(svc, x: float, y: float, z: float):
    """Nearest-ish feasible point: clamp into the box, then onto the
    extension circle AROUND THE BASE (the origin circle was the pre-fit
    approximation). An exact projection is overkill — the loop re-solves
    anyway."""
    if svc.envelope_enabled:
        x = min(max(x, svc.envelope["X"][0]), svc.envelope["X"][1])
        y = min(max(y, svc.envelope["Y"][0]), svc.envelope["Y"][1])
        z = min(max(z, svc.envelope["Z"][0]), svc.envelope["Z"][1])
    if _kinematics_on():
        bx, by = _RP["base_x_mm"], _RP["base_y_mm"]
        rmax = (_RP["link1_mm"] + _RP["link2_mm"]
                - _RP["extension_margin_mm"] - REACH_MARGIN_MM)
        r = math.hypot(x - bx, y - by)
        if r > rmax:
            x = bx + (x - bx) * rmax / r
            y = by + (y - by) * rmax / r
        return x, y, z
    r = math.hypot(x, y)
    rmax = REACH_HARD_MM - REACH_MARGIN_MM
    if r > rmax:
        x, y = x * rmax / r, y * rmax / r
    return x, y, z


def _plan_xy_step(svc, px: float, py: float, tx: float, ty: float,
                  tz: float):
    """One feasible waypoint toward (tx, ty): full correction when close,
    a fraction when far, shrunk when blocked, slid to the nearest feasible
    point when the target itself is out of bounds. None = no progress."""
    note = ""
    if not _feasible(svc, tx, ty, tz):
        gx, gy, gz = _project_feasible(svc, tx, ty, tz)
        if (not _feasible(svc, gx, gy, gz)
                or math.hypot(gx - px, gy - py) < 1.0):
            return None
        note = (f"camera target ({tx:.0f}, {ty:.0f}) is out of bounds — "
                f"sliding toward the nearest feasible point "
                f"({gx:.0f}, {gy:.0f})")
        tx, ty = gx, gy
    dx, dy = tx - px, ty - py
    dist = math.hypot(dx, dy)
    if dist < 1e-9:
        return {"x": px, "y": py, "step": 0.0, "note": note}
    step = (dist if dist <= DIRECT_STEP_MM
            else min(max(STEP_FRACTION * dist, STEP_MIN_MM), STEP_MAX_MM))
    while True:
        wx, wy = px + dx / dist * step, py + dy / dist * step
        if _feasible(svc, wx, wy, tz):
            return {"x": wx, "y": wy, "step": step, "note": note}
        step *= 0.5
        if step < STEP_MIN_MM:
            return None

TRAVEL_SPEED = 15.0
DESCEND_SPEED = 15.0
PROBE_SPEED = 5.0
LIFT_SPEED = 10.0

APPROACH_OFFSET = 20.0   # descend starts torque-probing this far above target
FINE_ZONE = 6.0          # within this of target: 0.5 mm steps
STEP_COARSE = 1.0
STEP_FINE = 0.5
MIN_BAND = 25.0          # x1000 torque counts, from torque_probe.py
BASELINE_N = 5
J1_TREND_LEN = 3


class Runner:
    """Owns the one background sequence thread and its log/result/target."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.state = "idle"        # idle | running | done | error | stopped
        self.name = ""
        self.log: list[dict] = []
        self.result: dict | None = None
        self.target: dict | None = None   # the published grasp target
        self.detection_path: str | None = None   # annotated detection image
        self.detection_ts: float = 0.0
        self._t0 = 0.0

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, name: str, fn, *args) -> dict:
        with self._lock:
            if self.active:
                return {"ok": False,
                        "error": f"sequence '{self.name}' is still running"}
            self.stop_event.clear()
            self.state, self.name = "running", name
            self.log, self.result = [], None
            if name in ("find_disk", "find_aruco", "calibrate_aruco",
                        "generate_anchor"):  # stale highlight
                self.detection_path, self.detection_ts = None, 0.0
            self._t0 = time.time()
            self._thread = threading.Thread(
                target=self._run, args=(fn,) + args, daemon=True)
            self._thread.start()
            return {"ok": True, "started": name}

    def _run(self, fn, *args) -> None:
        try:
            result = fn(self, *args)
            self.result = result
            if self.state == "running":
                self.state = "stopped" if self.stop_event.is_set() else "done"
        except Exception as ex:  # noqa: BLE001 — surfaced to the operator
            self.say(f"SEQUENCE ERROR: {type(ex).__name__}: {ex}", "err")
            self.result = {"ok": False, "error": str(ex)}
            self.state = "error"

    def request_stop(self) -> dict:
        self.stop_event.set()
        return {"ok": True, "note": "stop requested — the sequence halts "
                                    "after the step in progress"}

    def stopped(self) -> bool:
        return self.stop_event.is_set()

    def say(self, msg: str, level: str = "info") -> None:
        self.log.append({"t": round(time.time() - self._t0, 1),
                         "level": level, "msg": msg})
        del self.log[:-400]

    def snapshot(self) -> dict:
        return {"state": self.state, "name": self.name, "active": self.active,
                "log": self.log, "result": self.result, "target": self.target,
                "detection_ts": self.detection_ts}


def _abort(run: Runner, msg: str) -> dict:
    run.say(msg, "err")
    run.state = "error"
    return {"ok": False, "error": msg}


def _halt(run: Runner) -> dict:
    run.say("stopped by operator", "warn")
    return {"ok": False, "stopped": True}


def _move(run: Runner, svc, x, y, z, rz, speed, why: str) -> dict | None:
    """One checked linear move; returns None on success, an abort dict on
    failure. Never retried."""
    run.say(f"{why}: linear to X {x:.2f} Y {y:.2f} Z {z:.2f} "
            f"Rz {rz:.2f} @ {speed:g}")
    res = svc.move_cartesian(x, y, z, rz, speed, "linear")
    if not res.get("ok"):
        return _abort(run, f"move refused/failed — {res.get('error')}")
    return None


# ------------------------------------------------------------- find disk


def seq_find_disk(run: Runner, svc, cam, teach) -> dict:
    ok, out = teach.selftest()
    tail = out.splitlines()[-1] if out else ""
    if not ok:
        return _abort(run, "mcp_teach selftest FAILED — refusing to drive "
                           f"motion from unvalidated vision math:\n{out}")
    run.say(f"teach selftest: {tail}")

    refusal = svc._preflight()
    if refusal:
        return _abort(run, refusal)

    pose = svc.pose_mm()
    run.say(f"start pose: X {pose['X']} Y {pose['Y']} Z {pose['Z']} "
            f"Rz {pose['Rz']}")
    # no fixed height gate: the calibrated vision needs the camera
    # ~205-240 mm above the PLATE, but the plate's own height is unknown
    # until detected — attempt the solve wherever we are; the radius
    # measurement then drives Z dynamically. Detection failing at start
    # aborts with guidance and no motion.

    sol = None
    pinned_cfg = None       # the selected grasp way's config
    way_switches = 0        # times the pinned way went unreachable
    budget = None           # travel budget, derived from the first solve
    total_travel = 0.0
    rotation_blocked = False  # no safe J4 winding -> centering fallback
    just_rotated = False    # last motion was the big in-place rotation
    rot_steps = 0           # post-rotation re-acquire steps used
    rotations = 0           # rotation phases used (bounded: a solve that
                            # keeps demanding rotation is bad detection,
                            # not a reason to spin forever)
    last_sol = None         # last good solve (lost-plate fallback)
    good_pos = None         # (x, y, z, rz) of the last successful detection
    last_step = None        # (dx, dy) of the last planned step
    lost_step = None        # the step that last walked the plate out of view
    last_was_recovery = False
    misses = 0              # consecutive solve failures (after retries)
    recoveries = 0          # lost-plate recovery moves used this Find
    err_hist = []           # xy_err per solve, for divergence detection
    for it in range(1, MAX_ITERS + 1):
        if run.stopped():
            return _halt(run)
        pose = svc.pose_mm()

        sol = None
        for attempt in range(1, DETECT_RETRIES + 1):
            frame = cam.snap()
            path = cam.save(frame, prefix="teach")
            s = teach.solve(path, pose["X"], pose["Y"], pose["Z"],
                            pose["Rz"], force_cfg=pinned_cfg)
            if s.get("detected"):
                sol = s
                break
            run.say(f"iter {it}: no detection (attempt {attempt}/"
                    f"{DETECT_RETRIES}) — recapturing", "warn")
        if sol is None:
            if it == 1:
                return _abort(run, "calibration disk NOT FOUND under the eye "
                                   "camera (no motion was made). Place it "
                                   "below the camera; if it IS in view, the "
                                   "camera is likely outside the calibrated "
                                   "working distance (~205-240 mm above the "
                                   "plate) — jog Z toward that gap and "
                                   "press Find again.")
            if just_rotated:
                # the rotation orbits the offset camera around the tool —
                # the plate often sits at the frame edge afterwards (seen
                # live). Backtracking would un-rotate the wrist; instead
                # step toward the known convergence XY, which brings the
                # mark back into the taught view.
                if rot_steps < 3 and last_sol is not None:
                    rot_steps += 1
                    tx = last_sol["move_xyrz"][0]
                    ty = last_sol["move_xyrz"][1]
                    plan = _plan_xy_step(svc, pose["X"], pose["Y"], tx, ty,
                                         pose["Z"])
                    if plan is not None and plan["step"] > 0.5:
                        run.say(f"iter {it}: plate out of view after the "
                                f"rotation — stepping {plan['step']:.0f} "
                                "mm toward the taught convergence point "
                                f"to re-acquire ({rot_steps}/3)", "warn")
                        err = _move(run, svc, plan["x"], plan["y"],
                                    pose["Z"], pose["Rz"], TRAVEL_SPEED,
                                    f"iter {it}: post-rotation re-acquire")
                        if err:
                            return err
                        continue
                if last_sol is not None:
                    sol = last_sol
                    run.say("plate not re-acquired after the rotation — "
                            "publishing the virtual-rotation estimate from "
                            "the last good solve (verified live to match "
                            "the converged grasp)", "warn")
                    break
                return _abort(run, "plate lost after the rotation and no "
                                   "prior solve to fall back on — press "
                                   "Find again.")
            misses += 1
            if misses == 1 and last_step is not None:
                lost_step = last_step   # remember what walked it out
            if recoveries < MAX_RECOVERIES and good_pos is not None:
                away = math.hypot(pose["X"] - good_pos[0],
                                  pose["Y"] - good_pos[1])
                if misses == 1 and away > 0.5:
                    recoveries += 1
                    run.say(f"iter {it}: lost the plate — going back to "
                            "the last position where it was detected "
                            f"(recovery {recoveries}/{MAX_RECOVERIES})",
                            "warn")
                    err = _move(run, svc, good_pos[0], good_pos[1],
                                good_pos[2], good_pos[3], TRAVEL_SPEED,
                                f"iter {it}: back to last-seen")
                    if err:
                        return err
                    last_was_recovery = True
                    continue
                if misses <= 2 and last_step is not None:
                    ox = good_pos[0] - last_step[0]
                    oy = good_pos[1] - last_step[1]
                    if _feasible(svc, ox, oy, good_pos[2]):
                        recoveries += 1
                        run.say(f"iter {it}: still no detection — trying "
                                "the other way from the last-seen spot "
                                f"(recovery {recoveries}/{MAX_RECOVERIES})",
                                "warn")
                        err = _move(run, svc, ox, oy, good_pos[2],
                                    good_pos[3], TRAVEL_SPEED,
                                    f"iter {it}: opposite-side try")
                        if err:
                            return err
                        last_was_recovery = True
                        continue
            if last_sol is not None:
                sol = last_sol
                run.say("could not re-acquire the plate, but the good "
                        f"solves so far are enough (last xy_err "
                        f"{sol['xy_err_mm']} mm, z_err {sol['z_err_mm']} "
                        "mm) — publishing the estimate from the last good "
                        "detection; review it before Align", "warn")
                break
            return _abort(run, f"lost the disk at iteration {it} and could "
                               "not re-acquire it — re-place / re-check "
                               "and press Find again.")

        misses = 0
        just_rotated = False
        rot_steps = 0
        if not last_was_recovery:
            lost_step = None    # a planned step ended with the plate in view
        last_was_recovery = False
        good_pos = (pose["X"], pose["Y"], pose["Z"], pose["Rz"])

        # highlight the detected circle pair for the operator
        try:
            run.detection_path = teach.annotate(path, sol)
            run.detection_ts = time.time()
        except Exception as ex:  # noqa: BLE001 — annotation is cosmetic
            run.say(f"could not annotate detection: {ex}", "warn")
        if it == 1:
            run.say(f"disk FOUND — circle pair highlighted (big R "
                    f"{sol['big_r']} px, small R {sol['small_r']} px, "
                    f"angle {sol['mark'][2]:.1f} deg)", "good")

        # grasp-way selection: Wide/Long convergence x wrist Rz/Rz+180 give
        # 4 physical ways to grab the tray. Pick a way whose convergence
        # pose AND grasp are reachable; re-evaluate if the pin goes bad.
        ge = sol.get("grasp_estimate")
        pin_bad = (pinned_cfg is not None and ge is not None
                   and not _feasible(svc, ge[0], ge[1], ge[2]))
        if pin_bad:
            run.say(f"pinned way {pinned_cfg} became unreachable — "
                    "re-evaluating all ways", "warn")
            way_switches += 1
            if way_switches > 2:
                return _abort(run, "grasp ways keep going unreachable — the "
                                   "tray is moving or sits at the workspace "
                                   "edge. Re-place it and press Find again.")
            pinned_cfg = None
        if pinned_cfg is None:
            ev = teach.evaluate_ways(path, pose["X"], pose["Y"], pose["Z"],
                                     pose["Rz"])
            feas, lines = [], []
            for w in ev.get("ways", []):
                c, g = w["solve"]["move_xyrz"], w["solve"]["grasp_estimate"]
                # normally the way drives to its taught convergence XY (we
                # rotate to it); if rotation is blocked (no safe J4
                # winding), centering never goes there — grasp reach only
                ok = (_feasible(svc, g[0], g[1], g[2])
                      and (rotation_blocked
                           or _feasible(svc, c[0], c[1], pose["Z"])))
                lines.append(f"{w['cfg']}: camera r={w['conv_radius']}, "
                             f"grasp r={w['grasp_radius']}, angle off "
                             f"{w['ang_diff']:.0f} deg -> "
                             + ("reachable" if ok else "UNREACHABLE"))
                if ok:
                    feas.append(w)
            for ln in lines:
                run.say("way " + ln)
            run.say("(each way also allows the wrist at Rz+180 on the same "
                    "grip point — that alternative is stored with the "
                    "target)")
            if not feas:
                return _abort(run, "all grasp ways are unreachable from "
                                   "this tray placement: " +
                                   "; ".join(lines) + ". Move the tray "
                                   "toward the robot and press Find again.")
            best = min(feas, key=lambda w: w["ang_diff"])
            pinned_cfg = best["cfg"]
            sol = best["solve"]
            run.say(f"selected way: {pinned_cfg} (smallest angle "
                    f"difference of the reachable ways)", "good")
        last_sol = sol

        # -------- rotation phase (the proven full-precision flow): rotate
        # the wrist in place to the pinned way's taught convergence angle,
        # <=30 deg chunks, choosing the winding that keeps J4 inside its
        # soft limits (fault 3571 near ±220 — hit live 2026-07-23; the
        # following translation moves J4 further, so keep a margin).
        rz_pending = _wrap180(sol["move_xyrz"][3] - pose["Rz"])
        if (abs(rz_pending) > ROTATE_MIN_DEG and not rotation_blocked
                and rotations < 2):
            delta, note = _j4_safe_delta(svc, rz_pending)
            if note:
                run.say(f"iter {it}: {note}", "warn")
            if delta is None:
                rotation_blocked = True
                run.say(f"iter {it}: falling back to mark-centering "
                        "without rotation (the grasp estimate composes "
                        "the virtual rotation)", "warn")
            else:
                run.say(f"iter {it}: rotating {delta:+.1f} deg in place to "
                        "the taught convergence angle "
                        f"({sol['move_xyrz'][3]:.2f} deg)")
                res = svc.rotate_to_rz(pose["Rz"] + delta, TRAVEL_SPEED,
                                       force_delta=delta)
                if not res.get("ok"):
                    return _abort(run, "rotation failed — "
                                       f"{res.get('error')} — check "
                                       "status/pose before pressing Find "
                                       "again")
                rotations += 1
                just_rotated = True
                continue

        centering = rotation_blocked and sol["rz_err_deg"] > RZ_CENTER_MODE
        run.say(f"iter {it}: cfg {sol['selected']}, bigR {sol['big_r']}, "
                f"xy_err {sol['xy_err_mm']} mm, rz_err {sol['rz_err_deg']} "
                f"deg, z_err {sol['z_err_mm']} mm"
                + (f", center_err {sol['center_err_mm']} mm [centering "
                   "fallback: no safe wrist winding]" if centering else ""))

        if centering:
            xy_ok, rz_ok = sol["center_err_mm"] < CENTER_CONV_MM, True
        else:
            xy_ok = sol["xy_err_mm"] < XY_CONV_MM
            rz_ok = sol["rz_err_deg"] < RZ_CONV_DEG
        if xy_ok and rz_ok and sol["z_err_mm"] < Z_CONV_MM:
            run.say("CONVERGED (xy/rz/z at the detection noise floor)"
                    if not centering else
                    "CONVERGED (mark centered + Z; rotation was blocked — "
                    "the estimate composes the virtual rotation)", "good")
            break

        if run.stopped():
            return _halt(run)

        # divergence check: errors must trend down as we approach
        err_hist.append(sol["center_err_mm"] if centering
                        else sol["xy_err_mm"])
        if (len(err_hist) >= 3 and err_hist[-1] > err_hist[-2] + 0.5
                and err_hist[-2] > err_hist[-3] + 0.5):
            return _abort(run, "xy error has RISEN for 3 solves in a row "
                               f"({err_hist[-3]:.1f} → {err_hist[-2]:.1f} → "
                               f"{err_hist[-1]:.1f} mm) — the disk moved "
                               "during Find, or the detector paired the "
                               "wrong circles (check the detection panel). "
                               "Re-place / re-check and press Find again.")

        # target for this round: XY from the mark solve (taught convergence
        # XY normally, centering target when rotation is blocked), height
        # ridden toward the radius-measured taught height from the FIRST
        # iteration.
        trz = sol["move_xyrz"][3]
        if centering:
            if sol["center_err_mm"] >= CENTER_CONV_MM:
                tx, ty = sol["move_center"][0], sol["move_center"][1]
            else:
                tx, ty = pose["X"], pose["Y"]
        elif sol["xy_err_mm"] >= XY_CONV_MM:
            tx, ty = sol["move_xyrz"][0], sol["move_xyrz"][1]
        else:
            tx, ty = pose["X"], pose["Y"]
        tz = sol["move_z"][2]
        if svc.envelope_enabled:
            tz = min(max(tz, svc.envelope["Z"][0]), svc.envelope["Z"][1])
        dist = math.hypot(tx - pose["X"], ty - pose["Y"])
        if budget is None:
            budget = max(100.0, 1.6 * dist + 50.0)
            run.say(f"travel budget for this Find: {budget:.0f} mm (scaled "
                    "from the first detection's distance)")

        plan = _plan_xy_step(svc, pose["X"], pose["Y"], tx, ty, tz)
        if plan is None:
            return _abort(run, "no feasible step toward the camera target "
                               f"(X {tx:.0f}, Y {ty:.0f}, radius "
                               f"{math.hypot(tx, ty):.0f} mm) — it is "
                               "outside the reachable/allowed area and "
                               "sliding along the boundary makes no "
                               "progress. Move the disk toward the robot "
                               "(or widen the envelope) and press Find "
                               "again.")
        if (lost_step is not None
                and math.hypot(plan["x"] - pose["X"] - lost_step[0],
                               plan["y"] - pose["Y"] - lost_step[1]) < 3.0):
            # never repeat the exact step that walked the plate out of
            # view — creep toward the visibility boundary instead
            plan["x"] = pose["X"] + (plan["x"] - pose["X"]) * 0.5
            plan["y"] = pose["Y"] + (plan["y"] - pose["Y"]) * 0.5
            plan["step"] *= 0.5
            run.say(f"iter {it}: that exact step lost the plate last time "
                    f"— halving to {plan['step']:.1f} mm", "warn")
        if total_travel + plan["step"] > budget:
            if last_sol is not None:
                sol = last_sol
                run.say(f"travel budget exhausted ({total_travel:.0f} of "
                        f"{budget:.0f} mm) — publishing the estimate from "
                        "the last good detection instead of chasing "
                        "further; review the residuals", "warn")
                break
            return _abort(run, f"travel budget exhausted: {total_travel:.0f}"
                               f" of {budget:.0f} mm used and the solve "
                               f"still wants {dist:.0f} mm more — the disk "
                               "likely moved, or detection is unstable "
                               "(check the detection panel). Press Find "
                               "again from here, or re-place the disk.")
        frac = plan["step"] / dist if dist > 1e-6 else 1.0
        dz = max(-Z_RIDE_MAX, min(Z_RIDE_MAX, (tz - pose["Z"]) * frac))
        wz = pose["Z"] + dz
        if centering:
            w_rz = pose["Rz"]   # rotation is blocked — hold the wrist
        else:
            # residual after the rotation phase is tiny; ride it, capped
            w_rz = pose["Rz"] + max(-RZ_RIDE_CAP, min(
                RZ_RIDE_CAP, _wrap180(trz - pose["Rz"]) * frac))
        if plan["note"]:
            run.say(f"iter {it}: {plan['note']}", "warn")
        last_step = (plan["x"] - pose["X"], plan["y"] - pose["Y"])
        err = _move(run, svc, plan["x"], plan["y"], wz, w_rz, TRAVEL_SPEED,
                    f"iter {it}: step {plan['step']:.1f} of {dist:.1f} mm")
        if err:
            return err
        total_travel += plan["step"] + abs(dz)
    else:
        if last_sol is None:
            return _abort(run, f"no convergence in {MAX_ITERS} iterations "
                               "(detection noise or the disk moved)")
        sol = last_sol
        run.say(f"no convergence in {MAX_ITERS} iterations — publishing "
                "the estimate from the last good detection; review the "
                "residuals before Align", "warn")

    # grasp_estimate composes the taught trigger from the solve's OWN
    # convergence pose (full offset applied, Rz included) — valid even
    # though the wrist never rotated during Find. grasp_if_converged
    # composes from the CURRENT wrist angle and would land off the disk.
    gx, gy, gz, grz = sol["grasp_estimate"]
    cal = sol.get("z_calibration_applied")

    # ---- Z refine: the radius-derived height is the noisiest number in
    # the solve (~±1.7 mm per frame), so sample it from a second height
    # and average. Every sample is published with the target so the
    # operator sees exactly what the script calculated.
    conv_z0 = round(float(sol["move_z"][2]), 3)
    z_samples = [conv_z0]
    base = svc.pose_mm()
    run.say(f"Z refine: sampling the radius-derived height at "
            f"+{Z_REFINE_MM:g} mm and back (current sample {conv_z0})")
    for dz_ref in (Z_REFINE_MM, 0.0):
        if run.stopped():
            return _halt(run)
        res = svc.move_cartesian(base["X"], base["Y"], base["Z"] + dz_ref,
                                 base["Rz"], TRAVEL_SPEED, "linear")
        if not res.get("ok"):
            run.say(f"z-refine hop {dz_ref:+.0f} mm refused "
                    f"({res.get('error')}) — sample skipped", "warn")
            continue
        p2 = svc.pose_mm()
        s2 = None
        for _ in range(DETECT_RETRIES):
            frame = cam.snap()
            pth = cam.save(frame, prefix="teach")
            s2 = teach.solve(pth, p2["X"], p2["Y"], p2["Z"], p2["Rz"],
                             force_cfg=pinned_cfg)
            if s2.get("detected"):
                break
            s2 = None
        if s2 is None:
            run.say(f"z-refine: no detection at {dz_ref:+.0f} mm — sample "
                    "skipped", "warn")
            continue
        z_samples.append(round(float(s2["move_z"][2]), 3))
    conv_z = sum(z_samples) / len(z_samples)
    spread = max(z_samples) - min(z_samples)
    run.say(f"z-refine samples (converged-camera height): {z_samples} -> "
            f"mean {conv_z:.2f}, spread {spread:.2f} mm"
            + (" — HIGH spread, detection is noisy; consider re-running "
               "Find" if spread > 3.0 else ""),
            "warn" if spread > 3.0 else "info")
    gz = round(gz + (conv_z - conv_z0), 3)
    z_cal = round(gz + cal, 3) if cal is not None else None
    reach = math.hypot(gx, gy)
    warnings = []
    if reach >= REACH_HARD_MM:
        warnings.append(f"grasp reach {reach:.1f} mm >= {REACH_HARD_MM:g} — "
                        "NOT reachable (controller faults out there)")
    grip_goal = z_cal if z_cal is not None else gz
    if svc.envelope_enabled:
        lo, hi = svc.envelope["Z"]
        if not (lo <= grip_goal <= hi):
            warnings.append(f"calibrated grip Z {grip_goal} is outside the "
                            f"envelope Z [{lo:g}, {hi:g}] — Descend would "
                            "be refused; adjust the envelope or re-place "
                            "the plate")
    if spread > 3.0:
        warnings.append(f"height samples disagree by {spread:.1f} mm — "
                        "consider re-running Find before descending")
    for w in warnings:
        run.say(w, "warn")

    rz_alt = round(_wrap180(grz + 180.0), 2)
    run.target = {
        "x": gx, "y": gy, "z": gz, "rz": grz, "rz_alt": rz_alt,
        "z_calibrated": z_cal if z_cal is not None else gz,
        "config": sol["selected"], "big_r": sol["big_r"],
        "found_at": time.strftime("%H:%M:%S"),
        "z_detail": {"samples": z_samples, "spread": round(spread, 2),
                     "vision_z": gz,
                     "touch_offset": cal if cal is not None else 0.0},
    }
    run.say(f"GRASP TARGET: X {gx} Y {gy} Rz {grz} "
            f"(config {sol['selected']})", "good")
    run.say(f"Z math: height samples {z_samples} -> vision grasp Z {gz}; "
            f"+ touch offset {cal if cal is not None else 0} = grip Z "
            f"{run.target['z_calibrated']} (no safety margin — value as "
            "measured)", "good")
    run.say(f"opposite-side grab of the SAME point: Rz {rz_alt} — if "
            "Descend or Grip fails on this approach, put that into the "
            "target's Rz field and Align again", "info")
    run.say("review the target, then Align when ready")
    return {"ok": True, "target": run.target, "warnings": warnings}


# ----------------------------------------------------------- find aruco

ARUCO_CENTER_MM = 20.0   # marker must sit within this of the camera's view
                         # center before a solve is trusted (off-center /
                         # off-range views showed a +12 mm bias live)
ARUCO_AGREE_MM = 2.0     # two consecutive centered solves must agree
ARUCO_MAX_ITERS = 8
ARUCO_INNER_REACH = _RP["inner_reach_mm"]  # TCPs closer risk the inner
                                           # joint limits (arm-specific)


def seq_find_aruco(run: Runner, svc, cam, aruco) -> dict:
    """Anchor-free ArUco target: fitted-camera solve + claw-arm-compensated
    TCP (the aruco-grab skill flow, validated on three blind placements).
    Publishes the SAME target shape the Align/Descend/Grip buttons use —
    the published X/Y is the TCP with the 184 mm claw arm already applied."""
    refusal = svc._preflight()
    if refusal:
        return _abort(run, refusal)
    cam_v, arm_v = aruco.model_stamps()
    if cam_v and arm_v and str(cam_v) != str(arm_v):
        run.say("WARNING: the camera model (fitted " + str(cam_v) + ") is "
                "NEWER than the claw-arm derivation (" + str(arm_v) + ") — "
                "published TCP targets may be off by millimetres. "
                "Re-derive the claw arm (Calibrate claw arm + Save wrist "
                "relation) before trusting a grab.", "warn")
    pose = svc.pose_mm()
    run.say(f"start pose: X {pose['X']} Y {pose['Y']} Z {pose['Z']} "
            f"Rz {pose['Rz']}")

    sol = None
    last_mw = None
    z_samples = []
    for it in range(1, ARUCO_MAX_ITERS + 1):
        if run.stopped():
            return _halt(run)
        pose = svc.pose_mm()
        s = None
        for attempt in range(1, DETECT_RETRIES + 1):
            frame = cam.snap()
            path = cam.save(frame, prefix="aruco")
            s = aruco.solve(path, pose["X"], pose["Y"], pose["Z"],
                            pose["Rz"])
            if s.get("detected"):
                break
            run.say(f"iter {it}: no marker (attempt {attempt}/"
                    f"{DETECT_RETRIES}) — recapturing", "warn")
            s = None
        if s is None:
            if it == 1:
                return _abort(run, "no ArUco marker in view (no motion was "
                                   "made). Jog the eye camera over the "
                                   "marker (~205-240 mm above it) and press "
                                   "Find ArUco again.")
            return _abort(run, f"marker lost at iteration {it} while "
                               "centering — re-check the view and press "
                               "Find ArUco again.")
        mw = s["marker_world"]
        z_samples.append(float(mw[2]))
        vcx, vcy = aruco.view_center_world(pose["X"], pose["Y"], pose["Rz"],
                                           s.get("H_mm"))
        off = math.hypot(mw[0] - vcx, mw[1] - vcy)
        run.say(f"iter {it}: id {s['id']} at world ({mw[0]}, {mw[1]}, "
                f"{mw[2]}), yaw {s['marker_yaw_deg']} deg — "
                f"{off:.1f} mm from the view center")

        if off <= ARUCO_CENTER_MM:
            if (last_mw is not None
                    and math.hypot(mw[0] - last_mw[0],
                                   mw[1] - last_mw[1]) < ARUCO_AGREE_MM):
                sol = s
                run.say("two centered solves agree — position locked",
                        "good")
                break
            last_mw = mw
            continue                      # re-capture without moving
        last_mw = None
        # move the camera's view center onto the marker (center-view rule)
        plan = _plan_xy_step(svc, pose["X"], pose["Y"],
                             pose["X"] + (mw[0] - vcx),
                             pose["Y"] + (mw[1] - vcy), pose["Z"])
        if plan is None:
            return _abort(run, "cannot center the marker in view — the "
                               "required camera position is outside the "
                               "reachable/allowed area. Move the object "
                               "inward and press Find ArUco again.")
        err = _move(run, svc, plan["x"], plan["y"], pose["Z"], pose["Rz"],
                    TRAVEL_SPEED, f"iter {it}: centering the marker "
                                  f"({off:.0f} mm off)")
        if err:
            return err
    else:
        return _abort(run, f"marker position did not stabilize in "
                           f"{ARUCO_MAX_ITERS} iterations (solve scatter "
                           "> 2 mm) — check lighting / marker flatness.")

    # multi-viewpoint verification: repeat captures from ONE viewpoint
    # share the same systematic bias (live lesson: X still off after a
    # single-view find) — solve from two shifted viewpoints, average, and
    # flag disagreement as a camera-model problem
    views = [list(sol["marker_world"][:2])]
    vp = svc.pose_mm()
    for dx, dy in ((18.0, 0.0), (-18.0, 18.0)):
        if run.stopped():
            return _halt(run)
        nx, ny = vp["X"] + dx, vp["Y"] + dy
        if not _feasible(svc, nx, ny, vp["Z"]):
            continue
        err = _move(run, svc, nx, ny, vp["Z"], vp["Rz"], TRAVEL_SPEED,
                    f"viewpoint hop ({dx:+g},{dy:+g})")
        if err:
            return err
        vp = svc.pose_mm()
        s2 = None
        for _ in range(DETECT_RETRIES):
            frame = cam.snap()
            pth = cam.save(frame, prefix="aruco")
            s2 = aruco.solve(pth, vp["X"], vp["Y"], vp["Z"], vp["Rz"])
            if s2.get("detected"):
                break
            s2 = None
        if s2 is not None:
            views.append(list(s2["marker_world"][:2]))
            z_samples.append(float(s2["marker_world"][2]))
            run.say(f"viewpoint {len(views)}: marker at "
                    f"({s2['marker_world'][0]}, {s2['marker_world'][1]})")
    if len(views) > 1:
        ax = sum(v[0] for v in views) / len(views)
        ay = sum(v[1] for v in views) / len(views)
        vspread = max(math.hypot(v[0] - ax, v[1] - ay) for v in views) * 2
        run.say(f"{len(views)} viewpoints, averaged marker ({ax:.2f}, "
                f"{ay:.2f}), spread {vspread:.1f} mm"
                + (" — HIGH: camera-model bias, run Calibrate camera"
                   if vspread > 3.0 else ""),
                "warn" if vspread > 3.0 else "info")
        ddx, ddy = ax - views[0][0], ay - views[0][1]
        sol["marker_world"][0] = round(ax, 2)
        sol["marker_world"][1] = round(ay, 2)
        for c in sol["grab_candidates"]:
            c["tcp"][0] = round(c["tcp"][0] + ddx, 2)
            c["tcp"][1] = round(c["tcp"][1] + ddy, 2)
            c["reach"] = round(math.hypot(c["tcp"][0], c["tcp"][1]), 1)

    # pick the claw-arm-compensated grab candidate. Feasibility is the
    # EXACT kinematic check when the fitted model is configured (extension
    # circle around the base + predicted J2 vs its measured soft limit —
    # both faults were hit live before this existed); the legacy flat
    # radius guards otherwise. NOTE the marker itself may sit beyond TCP
    # reach — the claw extends ~191 mm past the TCP, so only the TCP's own
    # position decides feasibility (claw-overhang placements are valid).
    pose = svc.pose_mm()
    cands = []
    for c in sol["grab_candidates"]:
        tcp = c["tcp"]
        why = _reach_block(tcp[0], tcp[1])
        # NOTE: span-vs-claw-window is NOT a gate (operator decision
        # 2026-07-28: "remove the claw guard, I will take care of that")
        # — it is logged per way and warned on the pick, nothing more.
        if why is None and not _kinematics_on() \
                and c["reach"] < ARUCO_INNER_REACH:
            why = (f"reach {c['reach']} inside the legacy inner guard "
                   f"{ARUCO_INNER_REACH:g} (no kinematic model configured)")
        env_ok = _feasible(svc, tcp[0], tcp[1], pose["Z"])
        ok = why is None and env_ok
        c["feasible"] = ok
        cands.append((ok, c))
        ik = _ik_j2j3(tcp[0], tcp[1])
        span_txt = (f" span {c['span_mm']}" if c.get("span_mm") is not None
                    else " span ?")
        run.say(f"way {c.get('axis', '?')}{span_txt} Rz {c['rz']}: TCP "
                f"({tcp[0]}, {tcp[1]}), reach {c['reach']}"
                + (f", predicted J2 {ik[0]:.1f} J3 {ik[1]:.1f}" if ik else "")
                + " -> "
                + ("OK" if ok else (why or "outside envelope")))
    good = [c for ok, c in cands if ok]
    if not good:
        return _abort(run, "no arm-reachable grab approach at this marker "
                           "pose — all 4 ways rejected (reach/J2-limit/"
                           "envelope, reasons above). Rotate or move the "
                           "object, then press Find ArUco again.")
    best = min(good, key=lambda c: abs(_wrap180(c["rz"] - pose["Rz"])))
    if best.get("clampable") is False:
        run.say(f"NOTE: picked way's {best.get('axis')} span "
                f"{best.get('span_mm')} mm is outside the claw window "
                f"[{_RP['claw_gap_min_mm']:g}, {_RP['claw_gap_max_mm']:g}]"
                " — claw guard removed per operator; clamping is YOUR "
                "call (the descent guard still protects)", "warn")
    elif best.get("clampable") is None:
        run.say("picked way has UNKNOWN span (id not disk-calibrated) — "
                "verify the object fits the 88 mm gap before Grip", "warn")

    # MEDIAN, not mean: a single-viewpoint Z outlier (3.5 mm seen live
    # 2026-07-28) must not drag the grip depth
    z_sorted = sorted(z_samples)
    mid = len(z_sorted) // 2
    z_med = (z_sorted[mid] if len(z_sorted) % 2
             else (z_sorted[mid - 1] + z_sorted[mid]) / 2.0)
    spread = max(z_samples) - min(z_samples)
    gx, gy = best["tcp"]
    grz = best["rz"]
    # per-object grip depth when the id's calibration stores one (recessed
    # markers — e.g. a tray whose marker sits 13 mm below the grip plane,
    # measured live by the torque guard 2026-07-28), else the global touch
    z_off = aruco.grip_z_offset(int(sol["id"]))
    z_cal = round(z_med + z_off, 2)
    run.target = {
        "x": gx, "y": gy, "z": round(z_med, 2), "rz": grz,
        "z_calibrated": z_cal,
        "config": f"ArUco id {sol['id']}",
        "found_at": time.strftime("%H:%M:%S"),
        "marker_id": int(sol["id"]),
        "marker_world": sol["marker_world"],
        "marker_yaw": sol["marker_yaw_deg"],
        "axis": best.get("axis"),
        "span_mm": best.get("span_mm"),
        "z_detail": {"samples": [round(v, 2) for v in z_samples],
                     "spread": round(spread, 2),
                     "vision_z": round(z_med, 2),
                     "touch_offset": z_off},
    }
    off = sol.get("grasp_offset_applied", [0.0, 0.0])
    if off[0] or off[1]:
        run.say(f"learned grasp offset for id {sol['id']} applied: "
                f"({off[0]}, {off[1]}) mm in the marker frame", "info")
    run.say(f"GRAB TARGET: marker ({sol['marker_world'][0]}, "
            f"{sol['marker_world'][1]}) - claw arm -> TCP ({gx}, {gy}) "
            f"Rz {grz}", "good")
    run.say(f"Z math: marker top {z_med:.2f} (median of samples "
            f"{run.target['z_detail']['samples']}, spread {spread:.2f}) + "
            f"touch offset {z_off:g}"
            + (" (per-id grip depth)" if z_off != aruco.Z_TOUCH else "")
            + f" = grip Z {z_cal}", "good")
    if spread > 3.0:
        run.say(f"height samples disagree by {spread:.1f} mm — consider "
                "re-running Find ArUco", "warn")
    run.say("review the target, then Align when ready (open claw 28 "
            "before Descend)")
    return {"ok": True, "target": run.target}


# -------------------------------------------------------- generate anchor

ANCHOR_CONV_XY = 0.3     # vendor-flow convergence gates (detection noise
ANCHOR_CONV_RZ = 0.2     # floor — same values the proven Find disk uses)
ANCHOR_CONV_Z = 0.3
ANCHOR_MAX_ITERS = 15


def seq_generate_anchor(run: Runner, svc, cam, teach, aruco) -> dict:
    """One-time ground-truth generation: converge to the vendor's taught
    view of the CALIBRATION DISK using the vendor's exact solve + values,
    then persist the anchor triplet (mark pixel + capture pose + the
    demonstrated-trigger grasp TCP) to grab_skill/anchors.json — twice:
    the live converged capture AND the pure taught-constants variant, so
    later derivations get a two-anchor agreement check. Once anchors
    exist, Calibrate camera auto-re-derives the claw arm + wrist relation
    after every refit (software only, no jogging) — a camera recal then
    yields a grab-ready robot with no extra steps."""
    ok, out = teach.selftest()
    tail = out.splitlines()[-1] if out else ""
    if not ok:
        return _abort(run, "mcp_teach selftest FAILED — refusing to drive "
                           f"motion from unvalidated vendor math:\n{out}")
    run.say(f"teach selftest: {tail}")
    refusal = svc._preflight()
    if refusal:
        return _abort(run, refusal)

    sol = None
    path = ""
    for it in range(1, ANCHOR_MAX_ITERS + 1):
        if run.stopped():
            return _halt(run)
        pose = svc.pose_mm()
        sol = None
        for attempt in range(1, DETECT_RETRIES + 1):
            frame = cam.snap()
            path = cam.save(frame, prefix="anchor")
            s = teach.solve(path, pose["X"], pose["Y"], pose["Z"],
                            pose["Rz"])
            if s.get("detected"):
                sol = s
                break
            run.say(f"iter {it}: no detection (attempt {attempt}/"
                    f"{DETECT_RETRIES})", "warn")
        if sol is None:
            return _abort(run, "calibration disk not detected — place it "
                               "under the eye camera (~205-240 mm) and "
                               "rerun. No anchor was saved.")
        xy_e, rz_e, z_e = (sol["xy_err_mm"], sol["rz_err_deg"],
                          sol["z_err_mm"])
        run.say(f"iter {it}: {os.path.basename(path)} @ pose "
                f"({pose['X']}, {pose['Y']}, {pose['Z']}, {pose['Rz']}) "
                f"cfg {sol['selected']}  xy_err {xy_e}  rz_err {rz_e}  "
                f"z_err {z_e}")
        if (xy_e < ANCHOR_CONV_XY and rz_e < ANCHOR_CONV_RZ
                and z_e < ANCHOR_CONV_Z):
            run.say("converged to the taught view", "good")
            break
        # VENDOR-EXACT correction (operator's order 2026-07-28): apply the
        # solve's FULL move_xyrz target, then the FULL move_z target, every
        # iteration — exactly the vendor demo's loop, no capped/partial
        # steps. The only non-vendor additions are hard REFUSALS
        # (reach/J2/J4/envelope) that stop the run cleanly instead of
        # letting the controller fault mid-calibration.
        tx, ty, t_rz = (float(sol["move_xyrz"][0]),
                        float(sol["move_xyrz"][1]),
                        float(sol["move_xyrz"][3]))
        t_z = float(sol["move_z"][2])
        why = _reach_block(tx, ty)
        if why:
            return _abort(run, "vendor convergence target "
                               f"({tx:.1f}, {ty:.1f}) is outside the "
                               f"arm's limits: {why} — move the disk and "
                               "rerun. No anchor was saved.")
        delta, note = _j4_safe_delta(svc, _wrap180(t_rz - pose["Rz"]))
        if note:
            run.say(note, "warn")
        if delta is None:
            return _abort(run, "no safe J4 winding for the taught "
                               "convergence angle — rotate the disk and "
                               "rerun. No anchor was saved.")
        if abs(delta) > 0.05:
            res = svc.rotate_to_rz(t_rz, TRAVEL_SPEED, force_delta=delta)
            if not res.get("ok"):
                return _abort(run, f"rotation failed — {res.get('error')}")
        err = _move(run, svc, tx, ty, pose["Z"], t_rz, TRAVEL_SPEED,
                    f"iter {it}: vendor move_xyrz (full correction)")
        if err:
            return err
        err = _move(run, svc, tx, ty, t_z, t_rz, TRAVEL_SPEED,
                    f"iter {it}: vendor move_z (full correction)")
        if err:
            return err
    else:
        return _abort(run, f"did not converge in {ANCHOR_MAX_ITERS} "
                           "iterations — check disk placement/lighting. "
                           "No anchor was saved.")

    pose = svc.pose_mm()
    grasp = sol["grasp_if_converged"]          # vendor trigger from HERE
    geo = teach.cfg_geometry(sol["selected"])
    h_live = geo["dis_mm"] * geo["model_radius"] / float(sol["big_r"])
    stamp = time.strftime("%Y-%m-%d %H:%M")
    common = {"pose": [pose["X"], pose["Y"], pose["Rz"]],
              "grab_tcp": [float(grasp[0]), float(grasp[1])],
              "grab_rz": float(grasp[3]), "config": sol["selected"],
              "date": stamp}
    # NOT saved yet — the operator judges the run first (the browser asks
    # "was the run successful — save as anchor?"; /anchor_confirm saves)
    pending = [
        {"name": f"vendor-converged-capture {stamp}",
         "kind": "vendor-converged-capture",
         "image": path,
         "mark_px": [float(sol["mark"][0]), float(sol["mark"][1])],
         "H_mm": round(h_live, 3),
         "note": "vendor solve converged live; grasp = demonstrated "
                 "trigger from the converged pose", **common},
        {"name": f"vendor-taught-constants {stamp}",
         "kind": "vendor-taught-constants",
         "mark_px": geo["model_mark_img"][:2],
         "H_mm": round(geo["dis_mm"], 3),
         "note": "taught pixel at taught optical distance + trigger",
         **common},
    ]
    run.say(f"CONVERGED: mark px ({sol['mark'][0]:.1f}, "
            f"{sol['mark'][1]:.1f}), vendor grasp TCP ({grasp[0]}, "
            f"{grasp[1]}) Rz {grasp[3]}", "good")
    run.say("anchor is PENDING — confirm in the dialog to save it "
            "(after saving, Calibrate camera auto-re-derives the claw "
            "arm on every refit).", "warn")
    z_cal = sol.get("grasp_z_calibrated")
    run.target = {
        "x": float(grasp[0]), "y": float(grasp[1]),
        "z": float(grasp[2]), "rz": float(grasp[3]),
        "z_calibrated": (float(z_cal) if z_cal is not None
                         else float(grasp[2])),
        "config": f"anchor {sol['selected']}",
        "found_at": time.strftime("%H:%M:%S"),
    }
    return {"ok": True, "anchor_pending": True, "stamp": stamp,
            "pending_rows": pending}


# ------------------------------------------------- calibrate camera mount

CAMCAL_ROT_STEPS = (0.0, 30.0, -30.0, 60.0, -60.0, 90.0)
CAMCAL_XY_HOPS = ((40.0, 0.0), (-40.0, 0.0), (0.0, 40.0), (0.0, -40.0))
CAMCAL_Z_HOP = 30.0
CAMCAL_MAX_RMS = 4.0


def seq_calibrate_camera(run: Runner, svc, cam, aruco) -> dict:
    """Automated eye-camera mount calibration: drives through wrist
    rotations, XY hops and a second height over a FIXED marker, collects
    (pose, pnp) rows, least-squares fits the mount INCLUDING the axis
    tilt term, and saves it. This defines the model's validity everywhere
    — run it whenever solves show position-dependent bias."""
    refusal = svc._preflight()
    if refusal:
        return _abort(run, refusal)
    base = svc.pose_mm()
    run.say(f"start pose: X {base['X']} Y {base['Y']} Z {base['Z']} "
            f"Rz {base['Rz']} — the marker must stay FIXED during the "
            "whole calibration")

    rows = []

    def _capture_row(tag):
        pose = svc.pose_mm()
        for _ in range(DETECT_RETRIES):
            frame = cam.snap()
            path = cam.save(frame, prefix="camcal")
            m = aruco.detect_raw(path)
            if m is not None:
                rows.append({"x": pose["X"], "y": pose["Y"],
                             "z": pose["Z"], "rz": pose["Rz"],
                             "ux": float(m["cam_xyz_mm"][0]),
                             "uy": float(m["cam_xyz_mm"][1]),
                             "H": float(m["cam_xyz_mm"][2])})
                run.say(f"row {len(rows)} [{tag}]: u=({m['cam_xyz_mm'][0]}, "
                        f"{m['cam_xyz_mm'][1]}) H={m['cam_xyz_mm'][2]}")
                return True
        run.say(f"[{tag}] marker not detected — row skipped", "warn")
        return False

    def _recenter():
        """Keep the marker near the view center after a rotation (uses the
        current, possibly imperfect model — only needs FOV accuracy)."""
        pose = svc.pose_mm()
        for _ in range(2):
            frame = cam.snap()
            path = cam.save(frame, prefix="camcal")
            s = aruco.solve(path, pose["X"], pose["Y"], pose["Z"],
                            pose["Rz"])
            if not s.get("detected"):
                return False
            mw = s["marker_world"]
            vcx, vcy = aruco.view_center_world(pose["X"], pose["Y"],
                                               pose["Rz"])
            if math.hypot(mw[0] - vcx, mw[1] - vcy) < 25.0:
                return True
            plan = _plan_xy_step(svc, pose["X"], pose["Y"],
                                 pose["X"] + (mw[0] - vcx),
                                 pose["Y"] + (mw[1] - vcy), pose["Z"])
            if plan is None:
                return False
            err = _move(run, svc, plan["x"], plan["y"], pose["Z"],
                        pose["Rz"], TRAVEL_SPEED, "recenter")
            if err is not None:
                return False
            pose = svc.pose_mm()
        return True

    if not _capture_row("base"):
        return _abort(run, "marker not visible at the start pose — center "
                           "the camera over it first, then run Calibrate "
                           "camera again. No motion was made.")

    # XY hops at the base wrist angle
    for dx, dy in CAMCAL_XY_HOPS:
        if run.stopped():
            return _halt(run)
        err = _move(run, svc, base["X"] + dx, base["Y"] + dy, base["Z"],
                    base["Rz"], TRAVEL_SPEED, f"hop ({dx:+g},{dy:+g})")
        if err:
            return err
        _capture_row(f"hop {dx:+g},{dy:+g}")
    err = _move(run, svc, base["X"], base["Y"], base["Z"], base["Rz"],
                TRAVEL_SPEED, "back to base")
    if err:
        return err

    # second height
    err = _move(run, svc, base["X"], base["Y"], base["Z"] + CAMCAL_Z_HOP,
                base["Rz"], TRAVEL_SPEED, f"height +{CAMCAL_Z_HOP:g}")
    if err:
        return err
    _capture_row("height+")
    err = _move(run, svc, base["X"], base["Y"], base["Z"], base["Rz"],
                TRAVEL_SPEED, "back down")
    if err:
        return err

    # wrist rotations (J4-aware), re-centering after each
    for rot in CAMCAL_ROT_STEPS[1:]:
        if run.stopped():
            return _halt(run)
        target_rz = _wrap180(base["Rz"] + rot)
        pose = svc.pose_mm()
        delta, note = _j4_safe_delta(svc, _wrap180(target_rz - pose["Rz"]))
        if note:
            run.say(note, "warn")
        if delta is None:
            run.say(f"rotation {rot:+g} skipped — no safe J4 winding",
                    "warn")
            continue
        res = svc.rotate_to_rz(target_rz, TRAVEL_SPEED, force_delta=delta)
        if not res.get("ok"):
            return _abort(run, f"rotation failed — {res.get('error')}")
        if not _recenter():
            run.say(f"could not re-center after {rot:+g} deg — skipping "
                    "this angle", "warn")
            continue
        _capture_row(f"rot {rot:+g}")
        pose = svc.pose_mm()
        if abs(rot) >= 60.0:            # extra height row at a far angle
            err = _move(run, svc, pose["X"], pose["Y"],
                        pose["Z"] + CAMCAL_Z_HOP, pose["Rz"],
                        TRAVEL_SPEED, "height hop")
            if err:
                return err
            _capture_row(f"rot {rot:+g} height+")
            err = _move(run, svc, pose["X"], pose["Y"], base["Z"],
                        pose["Rz"], TRAVEL_SPEED, "back down")
            if err:
                return err

    if len(rows) < 8:
        return _abort(run, f"only {len(rows)} usable rows (need >= 8) — "
                           "improve marker visibility and rerun.")
    rzs = [r["rz"] for r in rows]
    span = max(rzs) - min(rzs)
    fit = aruco.fit_mount(rows)
    run.say(f"fit over {fit['n']} rows (wrist span {span:.0f} deg): "
            f"lever arm {fit['lever_arm_mm']}, yaw "
            f"{fit['yaw_offset_deg']}, tilt {fit['tilt_per_mm']}/mm, "
            f"RMS {fit['rms_mm']} mm")
    if fit["rms_mm"] > CAMCAL_MAX_RMS:
        return _abort(run, f"fit RMS {fit['rms_mm']} mm > "
                           f"{CAMCAL_MAX_RMS} — NOT saved. The marker "
                           "probably moved during calibration; fix it "
                           "down and rerun.")
    saved = aruco.save_mount(fit)
    run.say(f"SAVED camera mount calibration (RMS {fit['rms_mm']} mm, "
            f"valid across the sampled wrist/height range)", "good")
    # the claw arm was derived THROUGH the old model — auto-refresh it
    # from the stored ground-truth anchors (Generate anchor button), so a
    # camera recal alone yields a grab-ready robot
    res = aruco.derive_arm_from_anchors()
    if res.get("ok"):
        run.say(f"claw arm AUTO-re-derived from {res['n']} stored "
                f"anchor(s): arm {res['arm']}, wrist_rel "
                f"{res['wrist_rel']} (max disagreement "
                f"{res['max_disagreement_mm']} mm) — saved, model stamps "
                "match, grabs are trustworthy again", "good")
        if res.get("single_anchor"):
            run.say("only ONE anchor stored — no cross-check was "
                    "possible; consider running Generate anchor again "
                    "or verifying with a grip", "warn")
    else:
        run.say("claw-arm auto-derivation did not run: "
                f"{res.get('error')} — THE CLAW ARM IS STALE (a stale arm "
                "missed by 7.7 mm live). Run Generate anchor + rerun this "
                "calibration, or use the two-press jog flow + Save wrist "
                "relation. The standalone grabber refuses until stamps "
                "match.", "warn")
    run.say("re-run Calibrate disk ID for your markers if their offsets "
            "were learned under the old model.")
    return {"ok": True, "fit": saved, "arm_rederive": res}


# ---------------------------------------------------- calibrate disk id


def seq_calibrate_aruco(run: Runner, svc, cam, aruco) -> dict:
    """One-time per-ID disk calibration: the operator places the marker-
    tagged disk on a CONTRASTING background; this centers the marker,
    edge-detects the actual disk, measures the marker->disk-center offset
    (marker frame), relative yaw and true spans, and saves them for the id.
    Afterwards Find ArUco needs one image from ANY background."""
    refusal = svc._preflight()
    if refusal:
        return _abort(run, refusal)
    pose = svc.pose_mm()
    run.say(f"start pose: X {pose['X']} Y {pose['Y']} Z {pose['Z']} "
            f"Rz {pose['Rz']}")

    path = None
    for it in range(1, 5):
        if run.stopped():
            return _halt(run)
        pose = svc.pose_mm()
        s = None
        for attempt in range(1, DETECT_RETRIES + 1):
            frame = cam.snap()
            path = cam.save(frame, prefix="acal")
            s = aruco.solve(path, pose["X"], pose["Y"], pose["Z"],
                            pose["Rz"])
            if s.get("detected"):
                break
            s = None
        if s is None:
            return _abort(run, "no ArUco marker in view — place the tagged "
                               "disk on the contrast background under the "
                               "camera and press Calibrate again."
                          if it == 1 else
                          "marker lost while centering — press Calibrate "
                          "again.")
        mw = s["marker_world"]
        vcx, vcy = aruco.view_center_world(pose["X"], pose["Y"], pose["Rz"])
        off = math.hypot(mw[0] - vcx, mw[1] - vcy)
        run.say(f"iter {it}: id {s['id']} — {off:.1f} mm from view center")
        if off <= ARUCO_CENTER_MM:
            break
        plan = _plan_xy_step(svc, pose["X"], pose["Y"],
                             pose["X"] + (mw[0] - vcx),
                             pose["Y"] + (mw[1] - vcy), pose["Z"])
        if plan is None:
            return _abort(run, "cannot center the marker — object outside "
                               "the reachable/allowed area.")
        err = _move(run, svc, plan["x"], plan["y"], pose["Z"], pose["Rz"],
                    TRAVEL_SPEED, f"iter {it}: centering")
        if err:
            return err
    else:
        return _abort(run, "could not center the marker in 4 iterations.")

    pose = svc.pose_mm()
    cal = aruco.calibrate(path, pose["X"], pose["Y"], pose["Z"],
                          pose["Rz"])
    if not cal.get("ok"):
        return _abort(run, f"disk edge detection failed: {cal.get('error')}")
    try:
        run.detection_path = aruco.annotate_calibration(path, cal)
        run.detection_ts = time.time()
        run.say("edge detection highlighted in the panel — CHECK the green "
                "rectangle hugs the disk before trusting this", "good")
    except Exception as ex:  # noqa: BLE001
        run.say(f"could not annotate: {ex}", "warn")

    e = cal["entry"]
    sane = (10.0 <= e["width_mm"] <= 200.0
            and e["width_mm"] <= e["length_mm"] <= 400.0
            and math.hypot(e["dx_mm"], e["dy_mm"]) < 150.0)
    if not sane:
        return _abort(run, f"measured geometry looks wrong (disk "
                           f"{e['length_mm']}x{e['width_mm']} mm, offset "
                           f"({e['dx_mm']}, {e['dy_mm']})) — check the "
                           "detection panel; improve contrast and retry. "
                           "NOT saved.")
    saved = aruco.save_disk(cal["id"], e)
    run.say(f"SAVED for id {cal['id']}: disk center offset "
            f"({e['dx_mm']}, {e['dy_mm']}) mm in the marker frame, disk "
            f"yaw {e['rel_yaw_deg']} deg vs marker, spans "
            f"{e['length_mm']} x {e['width_mm']} mm", "good")
    gmin, gmax = _RP["claw_gap_min_mm"], _RP["claw_gap_max_mm"]
    clampable = [s_ for s_ in (e["length_mm"], e["width_mm"])
                 if gmin < s_ < gmax]
    run.say(f"clampable spans (claw gap {gmin:g}-{gmax:g} mm): "
            + (str(clampable) if clampable else
               "NONE — this object cannot be gripped by span!"),
            "info" if clampable else "warn")
    run.say("done — future Find ArUco of this id lands on the DISK center "
            "from any background. Press Find ArUco to grab now.")
    return {"ok": True, "id": cal["id"], "saved": saved}


# ----------------------------------------------------------------- align


def seq_align(run: Runner, svc, target: dict, hover_z: float) -> dict:
    refusal = svc._preflight()
    if refusal:
        return _abort(run, refusal)
    pose = svc.pose_mm()
    hover = float(hover_z) if hover_z else pose["Z"]
    if hover < float(target["z_calibrated"]) + 10:
        return _abort(run, f"hover Z {hover} is within 10 mm of grip Z "
                           f"{target['z_calibrated']} — align happens at "
                           "safe height; raise hover Z")

    run.say(f"align to X {target['x']} Y {target['y']} Rz {target['rz']} "
            f"at hover Z {hover}")
    pose = svc.pose_mm()
    delta, note = _j4_safe_delta(svc, _wrap180(float(target["rz"])
                                               - pose["Rz"]))
    if note:
        run.say(note, "warn")
    if delta is None:
        alt_rz = target.get("rz_alt")
        return _abort(run, "cannot rotate to the target Rz without hitting "
                           "the J4 soft limit from this arm configuration"
                           + (f" — try the opposite-side grab: put Rz "
                              f"{alt_rz} into the target's Rz field and "
                              "Align again" if alt_rz is not None else ""))
    res = svc.rotate_to_rz(float(target["rz"]), TRAVEL_SPEED,
                           force_delta=delta)
    if not res.get("ok"):
        return _abort(run, f"rotation failed — {res.get('error')}")
    if run.stopped():
        return _halt(run)

    if abs(pose["Z"] - hover) > 0.5:
        err = _move(run, svc, pose["X"], pose["Y"], hover, float(target["rz"]),
                    TRAVEL_SPEED, "move to hover height")
        if err:
            return err
        if run.stopped():
            return _halt(run)

    err = _move(run, svc, float(target["x"]), float(target["y"]), hover,
                float(target["rz"]), TRAVEL_SPEED, "translate to target XY")
    if err:
        return err
    pose = svc.pose_mm()
    run.say(f"aligned at X {pose['X']} Y {pose['Y']} Z {pose['Z']} "
            f"Rz {pose['Rz']} — set the claw opening, then Descend", "good")
    return {"ok": True, "pose": pose}


# --------------------------------------------------------------- descend


def _read_torque(run: Runner, svc) -> dict | None:
    r = svc.torque_report()
    if not r.get("ok"):
        _abort(run, f"torque report failed — {r.get('error')}")
        return None
    return r


def seq_descend(run: Runner, svc, target: dict) -> dict:
    refusal = svc._preflight()
    if refusal:
        return _abort(run, refusal)
    grip_z = float(target["z_calibrated"])
    pose = svc.pose_mm()

    if math.hypot(pose["X"] - float(target["x"]),
                  pose["Y"] - float(target["y"])) > 1.0:
        return _abort(run, f"tool is at X {pose['X']} Y {pose['Y']} but the "
                           f"target is X {target['x']} Y {target['y']} — run "
                           "Align first")

    r = _read_torque(run, svc)
    if r is None:
        return {"ok": False}
    if not r["telemetry_live"]:
        return _abort(run, "J1-J4 torque slots read ZERO — "
                           "controller/main_hostpoint_trq.bin is not the running "
                           "program; torque-guarded descent unavailable")

    approach_z = grip_z + APPROACH_OFFSET
    if pose["Z"] > approach_z + 0.5:
        err = _move(run, svc, pose["X"], pose["Y"], approach_z, pose["Rz"],
                    DESCEND_SPEED, "approach")
        if err:
            return err
    if run.stopped():
        return _halt(run)

    run.say(f"taking torque baseline ({BASELINE_N} stationary reads)...")
    samples = []
    for _ in range(BASELINE_N):
        r = _read_torque(run, svc)
        if r is None:
            return {"ok": False}
        samples.append([r["joints"][f"J{i}"] for i in (1, 2, 3, 4)])
        if run.stopped():
            return _halt(run)
    n = len(samples)
    mean = [sum(s[i] for s in samples) / n for i in range(4)]
    std = [(sum((s[i] - mean[i]) ** 2 for s in samples) / n) ** 0.5
           for i in range(4)]
    floor = band_floor()
    band = [max(3.0 * sd, floor) for sd in std]
    run.say("baseline mean " + str([round(m) for m in mean])
            + " band " + str([round(b) for b in band])
            + (f" (operator-set floor ±{floor:g} from the torque tab)"
               if floor != MIN_BAND else ""))

    # J1's stationary hold torque is NOT comparable to its post-step
    # readings (observed live: 493 stationary -> 384 right after a free
    # 1 mm step — a false CONTACT stop). Per the skill, J1 is judged ONLY
    # against the local trend of previous post-step readings; the first
    # step seeds that trend and is guarded by J2-J4 alone.
    j1_trend = []
    pose = svc.pose_mm()
    cur_z = pose["Z"]
    run.say(f"stepping down from Z {cur_z:.2f} to grip Z {grip_z:.2f} "
            f"at speed {PROBE_SPEED:g} (1.0 mm steps, 0.5 mm within "
            f"{FINE_ZONE:g} mm)")

    while cur_z > grip_z + 1e-6:
        if run.stopped():
            return _halt(run)
        step = STEP_FINE if cur_z - grip_z <= FINE_ZONE else STEP_COARSE
        next_z = max(grip_z, cur_z - step)
        res = svc.move_cartesian(pose["X"], pose["Y"], next_z, pose["Rz"],
                                 PROBE_SPEED, "linear")
        if not res.get("ok"):
            return _abort(run, f"step refused/failed — {res.get('error')}")
        cur_z = next_z

        r = _read_torque(run, svc)
        if r is None:
            return {"ok": False}
        j = [r["joints"][f"J{i}"] for i in (1, 2, 3, 4)]
        # J1 (Z ram, gravity-loaded) drifts with Z and reads differently
        # right after a move: judge vs the local trend of POST-STEP reads
        # only; J2-J4 idle near zero: judge vs the static baseline
        if j1_trend:
            j1_ref = sum(j1_trend) / len(j1_trend)
            devs = [j[0] - j1_ref] + [j[i] - mean[i] for i in (1, 2, 3)]
            hit = [i for i in range(4) if abs(devs[i]) > band[i]]
        else:
            j1_ref = j[0]     # first post-step read seeds the J1 trend
            devs = [0.0] + [j[i] - mean[i] for i in (1, 2, 3)]
            hit = [i for i in range(1, 4) if abs(devs[i]) > band[i]]
            run.say(f"first step: J1 {j[0]} seeds the local trend "
                    "(stationary baseline is not comparable to post-step "
                    "reads) — J2-J4 guard this step")
        run.say(f"Z {cur_z:7.2f}  J " + str([round(v) for v in j])
                + "  dev " + str([round(d) for d in devs])
                + ("  BREACH " + str([f"J{i+1}" for i in hit]) if hit else ""))

        if hit:
            breach_devs = list(devs)
            run.say("torque band breach — STOP. Retreating 1 mm to "
                    "discriminate contact vs drift", "warn")
            res = svc.move_cartesian(pose["X"], pose["Y"], cur_z + 1.0,
                                     pose["Rz"], PROBE_SPEED, "linear")
            if not res.get("ok"):
                return _abort(run, f"retreat failed — {res.get('error')} — "
                                   "physical state must be checked")
            # read twice and judge on the settled second read — a report
            # taken right after the up-move carries the same post-move
            # artifact that motivated the J1 trend rule
            r2 = _read_torque(run, svc)
            if r2 is not None:
                r2 = _read_torque(run, svc)
            if r2 is None:
                return {"ok": False}
            j2v = [r2["joints"][f"J{i}"] for i in (1, 2, 3, 4)]
            devs2 = [j2v[0] - j1_ref] + [j2v[i] - mean[i] for i in (1, 2, 3)]
            verdicts = {}
            for i in hit:
                unloaded = abs(devs2[i]) < 0.5 * abs(breach_devs[i])
                verdicts[f"J{i+1}"] = "CONTACT (unloaded on retreat)" \
                    if unloaded else "drift (deviation persists)"
            contact = any("CONTACT" in v for v in verdicts.values())
            for jn, v in verdicts.items():
                run.say(f"{jn}: {v}", "warn" if contact else "info")
            above = cur_z - grip_z
            if contact and above > 0.5:
                run.say(f"CONTACT {above:.1f} mm ABOVE grip depth — do NOT "
                        "grip here. Check the camera: what was touched? "
                        "Re-find or reseat the object.", "err")
            elif contact:
                run.say("contact at grip depth — the surface/backstop was "
                        "reached; you may grip from the retreated height",
                        "warn")
            else:
                run.say("looks like sensor drift, not contact. You may "
                        "re-run Descend to continue from here.", "info")
            return {"ok": True, "breach": True, "contact": contact,
                    "verdicts": verdicts, "stopped_z": cur_z,
                    "retreated_to": cur_z + 1.0}

        j1_trend.append(j[0])
        del j1_trend[:-J1_TREND_LEN]

    run.say(f"reached calibrated grip Z {grip_z:.2f} with no torque breach "
            "— ready to Grip", "good")
    return {"ok": True, "breach": False, "at_z": grip_z}


# -------------------------------------------------------------- workflow

WF_APPROACH_MM = 20.0   # the claw opens (pick) / closes (after release)
                        # this far above the point's Z — operator's spec

WF_ORDER_DEFAULT = "z,rz,xy"   # travel-leg motion order between points:
                               # rise first, rotate at height, then slide

def _parse_order(s: str):
    """Operator-tunable travel-leg order: comma list of z / rz / xy / x /
    y tokens ("z,rz,xy" default; "z,x,y,rz" = fully split). Unknown
    tokens are an error; axes the operator omitted are auto-appended in
    the default order so a leg always ENDS at the target pose."""
    toks = [t.strip().lower() for t in str(s or "").split(",")
            if t.strip()]
    valid = {"z", "rz", "xy", "x", "y"}
    for t in toks:
        if t not in valid:
            return None, (f"unknown motion token '{t}' "
                          "(use z, rz, xy, x, y)")
    has = {"z": "z" in toks, "rz": "rz" in toks,
           "x": "x" in toks or "xy" in toks,
           "y": "y" in toks or "xy" in toks}
    if not has["z"]:
        toks.append("z")
    if not has["rz"]:
        toks.append("rz")
    if not has["x"] and not has["y"]:
        toks.append("xy")
    elif not has["x"]:
        toks.append("x")
    elif not has["y"]:
        toks.append("y")
    return toks, ""


def seq_workflow(run: Runner, svc, points: dict, params: dict) -> dict:
    """Pick -> place -> home over three SAVED points (operator-designed
    automation, 2026-07-28):

      start: travel closed at travel_z (J4-aware rotation), descend to
             z+20, OPEN the claw there, torque-guarded descend to z,
             torque-stalled grip, slow lift;
      end:   travel over, descend to z+20, guarded descend to z (a
             touchdown contact near z is the SUCCESS case when placing),
             open to release, rise 20 mm, CLOSE the claw;
      home:  travel back to the saved home pose.

    Every move is envelope+kinematics checked and arrival-verified; the
    descent guard runs at both ends; STOP halts between steps."""
    refusal = svc._preflight()
    if refusal:
        return _abort(run, refusal)
    for role in ("start", "end", "home"):
        if not points.get(role):
            return _abort(run, f"no '{role}' point assigned — save points "
                               "and pick roles in the Workflow card")
    ps, pe, ph = points["start"], points["end"], points["home"]
    travel_z = float(params.get("travel_z", 300.0))
    open_e1 = float(params.get("open_e1", 28.0))
    order, oerr = _parse_order(params.get("motion_order",
                                          WF_ORDER_DEFAULT))
    if order is None:
        return _abort(run, f"bad motion order: {oerr}")
    run.say("travel-leg motion order: " + " -> ".join(order))
    for role, p in (("start", ps), ("end", pe), ("home", ph)):
        why = _reach_block(float(p["x"]), float(p["y"]))
        if why:
            return _abort(run, f"'{role}' point unreachable: {why}")
    for role, p in (("start", ps), ("end", pe)):
        if travel_z < float(p["z_grip"]) + WF_APPROACH_MM + 5.0:
            return _abort(run, f"travel Z {travel_z:g} leaves less than "
                               f"5 mm over '{role}' +{WF_APPROACH_MM:g} — "
                               "raise it")

    def _goto(p, label):
        """One travel leg to (p.x, p.y, travel_z, p.rz), axis by axis in
        the operator-tuned order. Rotation is J4-winding planned; every
        translation is a checked linear move."""
        for tok in order:
            if run.stopped():
                return _halt(run)
            pose = svc.pose_mm()
            if tok == "z":
                if abs(pose["Z"] - travel_z) > 0.5:
                    err = _move(run, svc, pose["X"], pose["Y"], travel_z,
                                pose["Rz"], LIFT_SPEED,
                                f"{label}: Z to travel {travel_z:g}")
                    if err:
                        return err
            elif tok == "rz":
                delta, note = _j4_safe_delta(
                    svc, _wrap180(float(p["rz"]) - pose["Rz"]))
                if note:
                    run.say(note, "warn")
                if delta is None:
                    return _abort(run, f"{label}: no safe J4 winding to "
                                       f"Rz {p['rz']}")
                if abs(delta) > 0.05:
                    res = svc.rotate_to_rz(float(p["rz"]), TRAVEL_SPEED,
                                           force_delta=delta)
                    if not res.get("ok"):
                        return _abort(run, f"{label}: rotation failed — "
                                           f"{res.get('error')}")
            else:
                tx = float(p["x"]) if tok in ("x", "xy") else pose["X"]
                ty = float(p["y"]) if tok in ("y", "xy") else pose["Y"]
                if (abs(tx - pose["X"]) > 0.05
                        or abs(ty - pose["Y"]) > 0.05):
                    err = _move(run, svc, tx, ty, pose["Z"], pose["Rz"],
                                TRAVEL_SPEED, f"{label}: {tok.upper()}")
                    if err:
                        return err
        return None

    def _claw(e1, label):
        g = svc.move_gripper(e1)
        if not g.get("ok"):
            return _abort(run, f"{label}: gripper failed — "
                               f"{g.get('error')}")
        run.say(f"{label}: claw at {e1:g}")
        return None

    err = _claw(0.0, "travel prep")          # claw travels CLOSED
    if err:
        return err

    # ---------------- PICK at start
    zs = float(ps["z_grip"])
    err = _goto(ps, "start")
    if err:
        return err
    if run.stopped():
        return _halt(run)
    err = _move(run, svc, float(ps["x"]), float(ps["y"]),
                zs + WF_APPROACH_MM, float(ps["rz"]), DESCEND_SPEED,
                "start: descend to +20")
    if err:
        return err
    err = _claw(open_e1, "start: open at +20")
    if err:
        return err
    if run.stopped():
        return _halt(run)
    d = seq_descend(run, svc, {"x": ps["x"], "y": ps["y"],
                               "z_calibrated": zs})
    if not d.get("ok"):
        return d
    if d.get("breach") and d.get("contact"):
        return _abort(run, "start: CONTACT above grip depth — object "
                           "misplaced or stale Z; workflow stopped "
                           "before gripping")
    g = seq_grip(run, svc, {"start": open_e1, "threshold": -100.0,
                            "floor": 0.5, "step": 0.1, "coarse_step": 0.5,
                            "fine_from": 6.0})
    if not g.get("ok") or not g.get("gripped"):
        return _abort(run, "start: grip found nothing (or failed) — "
                           "workflow stopped at the pick")
    if run.stopped():
        return _halt(run)
    err = _move(run, svc, float(ps["x"]), float(ps["y"]), travel_z,
                float(ps["rz"]), LIFT_SPEED, "start: lift with load")
    if err:
        return err

    # ---------------- PLACE at end
    ze = float(pe["z_grip"])
    err = _goto(pe, "end")
    if err:
        return err
    if run.stopped():
        return _halt(run)
    err = _move(run, svc, float(pe["x"]), float(pe["y"]),
                ze + WF_APPROACH_MM, float(pe["rz"]), LIFT_SPEED,
                "end: descend to +20 (loaded)")
    if err:
        return err
    d = seq_descend(run, svc, {"x": pe["x"], "y": pe["y"],
                               "z_calibrated": ze})
    if not d.get("ok"):
        return d
    if d.get("breach") and d.get("contact"):
        run.say("end: touchdown contact — placing here", "good")
    err = _claw(open_e1, "end: release")
    if err:
        return err
    pose = svc.pose_mm()
    err = _move(run, svc, pose["X"], pose["Y"],
                pose["Z"] + WF_APPROACH_MM, pose["Rz"], LIFT_SPEED,
                "end: rise 20 after release")
    if err:
        return err
    err = _claw(0.0, "end: close claw")
    if err:
        return err

    # ---------------- HOME
    err = _goto(ph, "home")
    if err:
        return err
    zh = float(ph.get("z_grip", travel_z))
    if abs(zh - travel_z) > 0.5:
        err = _move(run, svc, float(ph["x"]), float(ph["y"]), zh,
                    float(ph["rz"]), TRAVEL_SPEED, "home: settle to "
                                                   "saved Z")
        if err:
            return err
    run.say("WORKFLOW COMPLETE: picked at start, placed at end, parked "
            "home (claw closed)", "good")
    return {"ok": True, "picked": True, "placed": True,
            "grip": g.get("grip")}


# ------------------------------------------------------------------ grip


def seq_grip(run: Runner, svc, params: dict) -> dict:
    """Legacy entry point; closing implementation was removed."""
    from pick_and_hold.Grip.motion import seq_grip as unavailable
    return unavailable(run, svc, params)
