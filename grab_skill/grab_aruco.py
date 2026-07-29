"""Standalone ArUco-disk pickup for the Bioyond S4 — the distilled program.

This is the end-to-end pipeline the operator console runs, packaged as one
CLI so a plain Python process can reliably pick up an ArUco-marked disk
with no browser and no MCP server. It reuses the exact same tested layers:

    robot_service.RobotService   hardened BRCAPI client + envelope +
                                 arrival-verified moves (stale-ack guard)
    camera_service.CameraService GigE eye-in-hand frames (MVS SDK)
    aruco_world                  fitted-camera solve + claw-arm math
    sequences                    find / align / descend / grip sequences

Run:  py grab_aruco.py [--ip 192.168.201.220] [--hold] [--hover 300]
                       [--open 28] [--no-lift]
  --hold   pause 20 mm above grip depth for a human verdict (the
           commissioning protocol) before the torque-guarded descent.

======================= ALGORITHM NOTES (distilled) =======================
Every rule below was paid for with a real failure on the live arm.

GEOMETRY — three levers, none at the TCP:
  claw_world   = TCP + R(Rz) @ claw_arm            (~191 mm! the founding bug)
  marker_world = TCP + R(Rz)@cam_arm + R(Rz+yaw_off)@diag(1,mirror)
                     @ (u_scale*pnp_u + tilt*H)
  arm kinematics: P = base + L1*e^i(J2+a) + L2*e^i(J2+J3+b) — on this arm
  base=(126,0), L1=L2=200 EXACTLY (fitted 0.00 mm residual on 8 live poses).
  The world origin is NOT the arm's rotation center: reach limits are
  circles around BASE, not the origin.

CONSTANT HYGIENE:
  * claw_arm and wrist_rel are extracted THROUGH the camera model — any
    camera refit silently invalidates them (a stale arm cost a 7.7 mm
    clamp-axis miss). Re-derive both after every eye_cam_fit change; the
    program refuses to run when calibration.json says the camera fit is
    newer than the claw-arm derivation (model-version stamp).
  * Nothing arm- or object-specific lives in code: calibration.json
    (camera fit, claw arm, wrist_rel, z-touch, per-id disk offsets) +
    robot_params.json (kinematics, joint limits, claw gap window).

VISION — one capture is never trusted:
  * CENTER-VIEW RULE: solves are trusted only with the marker near the
    image center (off-center at off-fit wrist angles biased +12 mm live).
    Centering must include the tilt*H term of the view center (~10 mm).
  * Two centered solves must agree < 2 mm, then two more viewpoints
    (~18 mm hops): XY = mean, Z = MEDIAN (a single-view Z outlier of
    3.5 mm was seen live; the median ignores it), spread > 3 mm means the
    camera model is stale -> recalibrate, do not grab.
  * grip_z = marker_z + z_touch_offset (measured, +9.0 here) + NO margin
    (operator's standing order — margin trades engagement depth).

CANDIDATES — exact feasibility, no radius folklore:
  * Rz_grab = disk_axis + wrist_rel (+-180 twin), disk_axis = marker_yaw
    + per-id rel_yaw from the one-time disk calibration (print rotation
    cancels; spans must fit the claw gap window 60-88 mm).
  * TCP = grab_point - R(Rz_grab)@claw_arm. Feasibility per candidate:
    extension |TCP-base| <= L1+L2-margin (fault 3570 was 3.6 mm past full
    stretch), predicted J2 >= j2_min+margin via exact IK (fault 3571
    froze J2 at -95.10 live — the IK reproduces that stop to the
    decimal), envelope box. The DISK may sit beyond TCP reach entirely —
    the claw overhang makes reach-536 objects grabbable (single side).

MOTION — the controller lies sometimes:
  * ARRIVAL VERIFICATION on every move: after connection drops the
    completion ack can be STALE — value 1 arrived while the controller
    had faulted mid-path, 16 mm and 47 deg away. pose_after must match
    the command (1 mm / 0.5 deg) or the move FAILED (RobotService does
    this; never bypass it).
  * J4 winding: in-place rotation moves J4 by exactly the delta;
    translation shifts it by -delta(J2+J3). Plan the END-state J4 inside
    +-150 preferred / +-205 hard, rotate in <=30 deg chunks at safe Z.
  * joint interpolation ONLY for zero-translation rotations (its
    Cartesian arc is unpredictable); all translations linear.
  * Speeds: travel <=30, approach <=20, torque probe 5, lift 8-10 (slow
    for trays of loose parts).

CONTACT — the torque band is a tripwire, not a debate:
  * Descent guard: 5-read stationary baseline; 1.0 mm steps (0.5 within
    6 mm) at speed 5; J1 judged vs the trend of PREVIOUS POST-STEP reads
    only (stationary J1 is not comparable — a 493->384 artifact caused a
    false stop); J2-J4 vs baseline +-band. FIRST breach: stop, retreat
    1 mm, re-read settled — contact unloads, drift persists. Never press
    deeper to confirm.
  * Grip: stepped close (0.5 coarse / 0.1 fine) until torque < -100 with
    position stall (free is +150..+195, saturation ~ -187). stall_E1 + 60
    = clamped span — compare against the disk's calibrated width; a
    surprise span means the wrong object or orientation.
  * Verify the hold after lifting (torque still strongly negative), and
    report honestly.
===========================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UI_DIR = os.path.join(ROOT, "operator_ui")
for p in (HERE, UI_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import aruco as aruco_mod              # noqa: E402  (operator_ui wrapper)
import sequences as seq                # noqa: E402
from camera_service import CameraService  # noqa: E402
from robot_service import RobotService     # noqa: E402


class ConsoleRun(seq.Runner):
    """Runner whose log goes to stdout — the sequences stay unchanged."""

    def __init__(self) -> None:
        super().__init__()
        self._t0 = time.time()
        self.state = "running"

    def say(self, msg: str, level: str = "info") -> None:
        super().say(msg, level)
        tag = {"info": " ", "good": "+", "warn": "!", "err": "X"}.get(
            level, " ")
        print(f" [{tag}] {msg}", flush=True)

    # sequences run inline here (no thread) — start() is not used
    def run_inline(self, name, fn, *args) -> dict:
        self.state, self.name = "running", name
        self.stop_event.clear()
        out = fn(self, *args)
        if self.state == "running":
            self.state = "done"
        return out or {}


def _fail(msg: str) -> int:
    print(f"\nFAILED: {msg}", flush=True)
    return 1


def _claw_arm_stamp_ok() -> tuple[bool, str]:
    """Refuse to grab with a claw arm derived under an older camera model
    (the stale-constant trap). The stamp is written by save_claw_arm /
    save_mount; missing stamps only warn (pre-stamp calibrations)."""
    cal = json.load(open(os.path.join(HERE, "calibration.json"),
                         encoding="utf-8-sig"))
    cam_v = (cal.get("eye_cam_fit") or {}).get("fitted")
    arm_v = cal.get("claw_arm_model_version")
    if not cam_v or not arm_v:
        return True, ("calibration stamps missing (older files) — cannot "
                      "prove the claw arm matches the camera model; if the "
                      "camera was refit since the arm derivation, re-derive "
                      "the arm first")
    if str(arm_v) != str(cam_v):
        return False, (f"claw arm was derived under camera model "
                       f"'{arm_v}' but the current fit is '{cam_v}' — "
                       "re-derive the claw arm (and wrist_rel) before "
                       "grabbing; a stale arm missed by 7.7 mm live")
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Standalone ArUco-disk pickup (S4)")
    ap.add_argument("--ip", default="")
    ap.add_argument("--hold", action="store_true",
                    help="pause 20 mm above grip depth for a human verdict")
    ap.add_argument("--hover", type=float, default=300.0,
                    help="safe travel/align height (mm)")
    ap.add_argument("--open", type=float, default=28.0,
                    help="claw opening before descend (28 = 88 mm gap)")
    ap.add_argument("--no-lift", action="store_true",
                    help="stop after the grip, do not lift")
    args = ap.parse_args()

    ok, note = _claw_arm_stamp_ok()
    if not ok:
        return _fail(note)
    if note:
        print(f" [!] {note}")

    svc = RobotService()
    cam = CameraService()
    run = ConsoleRun()

    # ---- bring-up: connect + hard preconditions (no motion, no enabling —
    # error clearing and enabling stay HUMAN actions on the pendant/console)
    r = svc.connect(args.ip)
    if not r.get("ok"):
        return _fail(f"connect: {r.get('error')}")
    print(f" [+] connected {r.get('endpoint')}")
    refusal = svc._preflight()
    if refusal:
        return _fail(refusal)
    tr = svc.torque_report()
    if not tr.get("ok"):
        return _fail(f"torque report: {tr.get('error')}")
    if not tr.get("telemetry_live"):
        return _fail("J1-J4 torque slots read zero — publish "
                     "main_hostpoint_trq.bin; the descent guard is blind "
                     "without it")
    if not svc.envelope_enabled:
        return _fail("envelope is disarmed — arm it (with the task-area "
                     "box) before autonomous motion")

    # ---- find: center-view solve, 2-agree, multi-viewpoint average,
    # exact-IK candidate pick (all inside seq_find_aruco)
    print("\n== FIND ==")
    out = run.run_inline("find_aruco", seq.seq_find_aruco, svc, cam,
                         aruco_mod)
    if not out.get("ok"):
        return _fail(out.get("error", "find failed"))
    tgt = dict(run.target)
    grip_z = float(tgt["z_calibrated"])
    hold_z = grip_z + seq.APPROACH_OFFSET

    # ---- align: J4-planned rotation + translation at hover height
    print("\n== ALIGN ==")
    out = run.run_inline("align", seq.seq_align, svc, tgt, args.hover)
    if not out.get("ok"):
        return _fail(out.get("error", "align failed"))

    g = svc.move_gripper(args.open)
    if not g.get("ok"):
        return _fail(f"claw open: {g.get('error')}")
    print(f" [+] claw open at {args.open:g}")

    # ---- optional hold checkpoint (commissioning protocol): descend fast
    # to grip+20 and wait for the human verdict before going lower
    if args.hold:
        print(f"\n== HOLD at Z {hold_z:.2f} (grip {grip_z:.2f} + 20) ==")
        res = svc.move_cartesian(float(tgt["x"]), float(tgt["y"]), hold_z,
                                 float(tgt["rz"]), seq.DESCEND_SPEED,
                                 "linear")
        if not res.get("ok"):
            return _fail(f"descend to hold: {res.get('error')}")
        ans = input("claw is 20 mm above grip depth — centered? "
                    "[yes = continue / anything else = abort] ").strip()
        if ans.lower() not in ("y", "yes", "descend", "go"):
            print(" [!] aborted at the hold — arm left in place")
            return 2

    # ---- torque-guarded descent to grip depth
    print("\n== DESCEND (torque-guarded) ==")
    out = run.run_inline("descend", seq.seq_descend, svc, tgt)
    if not out.get("ok"):
        return _fail(out.get("error", "descend failed"))
    if out.get("breach") and not out.get("contact"):
        print(" [!] drift breach — re-running descend once from here")
        out = run.run_inline("descend", seq.seq_descend, svc, tgt)
        if not out.get("ok"):
            return _fail(out.get("error", "descend failed"))
    if out.get("breach") and out.get("contact"):
        return _fail("contact above grip depth — something is in the way "
                     "(nest rim / wrong Z): re-check the placement")

    # ---- grip: torque-stalled close + span sanity
    print("\n== GRIP ==")
    out = run.run_inline("grip", seq.seq_grip, svc,
                         {"start": args.open, "threshold": -100.0,
                          "floor": 0.5, "step": 0.1, "coarse_step": 0.5,
                          "fine_from": 6.0})
    if not out.get("ok") or not out.get("gripped"):
        return _fail("no grip — nothing between the plates (see log): "
                     "lower the floor for narrow objects, or re-run find")
    grip = out.get("grip", {})
    span = grip.get("e1_position", 0) + 60.0
    print(f" [+] gripped: E1 {grip.get('e1_position')} torque "
          f"{grip.get('e1_torque')} -> clamped span ~{span:.1f} mm")
    mid = str(tgt.get("marker_id"))
    try:
        cal = json.load(open(os.path.join(HERE, "calibration.json"),
                             encoding="utf-8-sig"))
        width = float(cal["marker_offsets"][mid]["width_mm"])
        if abs(span - width) > 4.0:
            print(f" [!] span {span:.1f} vs calibrated width {width:g} — "
                  "possibly gripping the wrong object/orientation")
    except (KeyError, OSError, ValueError):
        pass

    # ---- lift + verify the hold
    if args.no_lift:
        print("\ndone (no-lift requested) — object held at grip depth")
        return 0
    print("\n== LIFT ==")
    pose = svc.pose_mm()
    res = svc.move_cartesian(pose["X"], pose["Y"], max(120.0, grip_z + 80),
                             pose["Rz"], seq.LIFT_SPEED, "linear")
    if not res.get("ok"):
        return _fail(f"lift: {res.get('error')} — object may be held; "
                     "check before anything else")
    chk = svc.torque_report()
    held = chk.get("ok") and chk.get("e1_torque", 0) < -100
    print(f" [{'+' if held else 'X'}] after lift: E1 torque "
          f"{chk.get('e1_torque')} -> {'HELD' if held else 'NOT HELD'}")
    return 0 if held else _fail("object not held after lift")


if __name__ == "__main__":
    sys.exit(main())
