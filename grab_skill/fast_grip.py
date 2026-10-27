"""Standalone fast grip for the current plate — Bioyond S4.

Closes the E1 gripper directly to the operator feel-tested value for this
plate (grab_skill/calibration.json -> plate_grip_e1_mm), instead of the
retired adaptive torque-crawl grip, and confirms the grip from a single
torque + position-stall read. See calibration.json's plate_grip_comment
for how that value was measured (2026-10-17 feel-test at the parked grasp
pose: E1 4.1 -> torque +57.9, no resistance; E1 3.0 -> torque -186.9,
stalled at 3.307, full saturation; E1 3.8 chosen as a firm grip short of
saturation).

ASSUMES the arm is ALREADY at the grasp pose — this script does NOT align
or descend. Run Align + Descend first (the operator console, which already
has both working), then run this to close the claw.

Standalone only: this is deliberately NOT wired into the operator console,
any HTTP route, or sequences.py. The console's own Grip pipeline
(/seq/grip) was retired on 2026-10-17 pending a different replacement
(see operator_ui/reports/grip_migration/) — this script does not touch or
revive that path. It opens its OWN controller connection, so don't run it
at the same time as the console or Bioyond Works (one BRCAPI client at a
time) — disconnect the other one first.

Run:  py grab_skill/fast_grip.py [--ip 192.168.201.220] [--e1 3.8]
                                 [--open 28] [--yes]
  --e1    override the calibrated E1 target (mm); default: calibration.json
  --open  E1 to reopen to if the grip is not confirmed (default 28, open)
  --yes   skip the interactive confirmation prompt (still requires a
          human at the E-stop; use only when that was already confirmed
          out of band)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UI_DIR = os.path.join(ROOT, "operator_ui")
for p in (HERE, UI_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from robot_service import (  # noqa: E402
    RobotService, GRIP_TORQUE_THRESHOLD, GRIP_POS_ERROR,
)

CAL_PATH = os.path.join(HERE, "calibration.json")


def _fail(msg: str) -> int:
    print(f"\nFAILED: {msg}", flush=True)
    return 1


def _calibrated_e1() -> float:
    """Read the operator feel-tested grip E1 for this plate. Raises rather
    than silently falling back to a guessed number."""
    cal = json.load(open(CAL_PATH, encoding="utf-8-sig"))
    e1 = cal.get("plate_grip_e1_mm")
    if e1 is None:
        raise KeyError("no plate_grip_e1_mm in calibration.json — run the "
                       "feel-test and record it, or pass --e1")
    return float(e1)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Standalone fast grip for the current plate (S4)")
    ap.add_argument("--ip", default="")
    ap.add_argument("--e1", type=float, default=None,
                    help="override the calibrated grip E1 (mm)")
    ap.add_argument("--open", type=float, default=28.0,
                    help="E1 to reopen to if the grip is not confirmed")
    ap.add_argument("--yes", action="store_true",
                    help="skip the interactive confirmation prompt")
    args = ap.parse_args()

    try:
        target = args.e1 if args.e1 is not None else _calibrated_e1()
    except (KeyError, ValueError, TypeError) as ex:
        return _fail(str(ex))
    if not 0.0 <= target <= 28.0:
        return _fail(f"E1 {target} outside the gripper's 0-28 mm range")

    svc = RobotService()

    # ---- bring-up: connect + hard preconditions only (no motion, no
    # enabling — error clearing and enabling stay HUMAN actions)
    r = svc.connect(args.ip)
    if not r.get("ok"):
        return _fail(f"connect: {r.get('error')}")
    print(f" [+] connected {r.get('endpoint')}")

    refusal = svc._preflight()
    if refusal:
        return _fail(refusal)

    pose = svc.pose_mm()
    print(f" [i] arm at X {pose['X']:.2f} Y {pose['Y']:.2f} "
          f"Z {pose['Z']:.2f} Rz {pose['Rz']:.2f}")
    print(" [i] this script does NOT align or descend — it assumes the "
          "arm is already at the grasp pose from Align + Descend")

    before = svc.gripper_status()
    if before.get("ok"):
        print(f" [i] current E1 {before['e1_position']:.2f}, "
              f"torque {before['e1_torque']:.1f}")

    if not args.yes:
        ans = input(f"about to close the claw to E1 {target:.2f} at the "
                    "CURRENT arm position — human at the E-stop, jaws "
                    "clear? [yes = proceed / anything else = abort] "
                    ).strip()
        if ans.lower() not in ("y", "yes"):
            print(" [!] aborted — no motion sent")
            return 2

    print(f"\n== GRIP == closing to E1 {target:.2f}")
    result = svc.move_gripper(target)
    if (not result.get("ok") or result.get("recovered")
            or result.get("gripper_warning")):
        return _fail("gripper move failed — "
                     f"{result.get('error') or result.get('gripper_warning')}")

    g = result.get("gripper", {})
    pos = g.get("e1_position")
    torque = g.get("e1_torque")
    if pos is None or torque is None:
        return _fail("gripper report missing position/torque")
    position_error = pos - target
    confirmed = (position_error > GRIP_POS_ERROR
                and torque < GRIP_TORQUE_THRESHOLD)
    print(f" [i] E1 commanded {target:.2f} -> settled {pos:.3f} "
          f"(stall {position_error:+.3f} mm), torque {torque:.1f}")

    if confirmed:
        print(f" [+] grip confirmed at E1 {pos:.2f} (torque {torque:.1f})")
        return 0

    print(f" [!] no grip confirmed (torque {torque:.1f} did not cross "
          f"{GRIP_TORQUE_THRESHOLD:g}, stall {position_error:+.3f} mm) "
          f"— reopening to {args.open:g}")
    reopen = svc.move_gripper(args.open)
    if not reopen.get("ok"):
        return _fail("grip not confirmed AND reopen failed — "
                     f"{reopen.get('error')} — check E1 state manually "
                     "before anything else")
    print(" [i] reopened — is the plate actually there / at the "
          "calibrated depth?")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
