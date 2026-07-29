"""Vision-teach solve for the operator console.

Thin wrapper around grab_skill/mcp_teach.py — the SDK-exact port of
Bioyond's calibrated teach pipeline (detect -> select trigger config ->
image->robot transform -> convergence offsets -> grasp pose). All math and
calibration loading stays in mcp_teach; this module only adapts its
print-JSON CLI into a returned dict, and runs its offline selftest once
per process (the skill requires ALL PASS before any teach-driven motion).
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GRAB_DIR = os.path.join(os.path.dirname(HERE), "grab_skill")
if GRAB_DIR not in sys.path:
    sys.path.insert(0, GRAB_DIR)

import mcp_teach as T  # noqa: E402
from sdk_pose import wrap180  # noqa: E402

CAL_PATH = os.path.join(GRAB_DIR, "calibration.json")

_cfgs = None
_selftest: tuple[bool, str] | None = None


def selftest() -> tuple[bool, str]:
    """Run mcp_teach's offline validation (cached). Must print ALL PASS."""
    global _selftest
    if _selftest is None:
        proc = subprocess.run(
            [sys.executable, os.path.join(GRAB_DIR, "mcp_teach.py"), "test"],
            capture_output=True, text=True, timeout=120)
        out = (proc.stdout or "") + (proc.stderr or "")
        _selftest = ("ALL PASS" in out, out.strip())
    return _selftest


def _configs():
    global _cfgs
    if _cfgs is None:
        _cfgs = T.load_configs()
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


def solve(img_path: str, x: float, y: float, z: float, rz: float,
          force_cfg: str | None = None) -> dict:
    """One teach iteration at the given current pose (mm/deg).

    Same fields as mcp_teach cmd_solve: detection, selected config,
    move_xyrz / move_z correction targets, errors, and the grasp pose
    (raw + Z-touch-calibrated).
    """
    cfgs = _configs()
    det = T.sdk_detect(img_path)
    if det is None:
        return {"detected": False}
    sel, details = T.select_trigger(cfgs, det["mark"])
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
    det = T.sdk_detect(img_path)
    if det is None:
        return {"detected": False}
    _, details = T.select_trigger(cfgs, det["mark"])
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
    cur_mark = T.mark_in_robot_pose(cfg, det["mark"])
    off_xyrz = T.tool_offset_xyrz(cfg, cur_mark)
    off_z = T.tool_offset_z(cfg, det["big_r"])
    move_xyrz = T.new_acc_pose(cur_pose, off_xyrz)
    move_z = T.new_acc_pose(cur_pose, off_z)
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
    move_center = T.new_acc_pose(cur_pose, off_c)
    center_err = float(np.hypot(dcx, dcy))
    grasp = T.final_acc_pose(cfg, cur_pose)
    # where the grasp will land once converged: apply BOTH measured
    # corrections to the current pose — XY/Rz from the mark AND the height
    # from the circle radius — then compose the trigger from there. Without
    # the height term the estimate inherits the camera's full remaining
    # z_err (Find corrects Z only after XY converges, so an early publish
    # was XY-tight but Z-blind).
    conv_full = np.array(move_xyrz, float).copy()
    conv_full[2] += float(move_z[2]) - float(cur_pose[2])
    grasp_est = T.final_acc_pose(cfg, conv_full)
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
