"""Persistent ground-truth ANCHORS for claw-arm derivation.

An anchor is one moment where the claw's world position was TRUTH — a
vendor-converged grasp (the demonstrated trigger IS the vendor's ground
truth) or any physically verified grip — recorded as the triplet the
software refresh needs:

    mark_px   the calibration mark's pixel in the capture
    H_mm      the camera optical distance at that capture (geometric —
              vendor dis * model_radius / big_r — model-independent)
    pose      [X, Y, Rz] the capture was taken from
    grab_tcp  [X, Y] + grab_rz : where the TCP stood when the claw was
              provably ON the object (vendor trigger / verified grip)

Only the pixel->world half of  arm = R(-Rz)@(marker_world - TCP)  depends
on the camera model, so after every camera recalibration the claw arm is
re-derived from these stored rows with zero motion: re-solve mark_px
through the CURRENT model, re-pair with the never-stale grab TCP. Live
validation 2026-07-28: this procedure fixed a 7.7 mm clamp-axis miss.

Created by the operator console's "Generate anchor" button (vendor
convergence, saves a live-capture row AND a taught-constants row) and
consumed automatically by "Calibrate camera" via derive_and_save().
"""

from __future__ import annotations

import json
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "anchors.json")

import aruco_world as W  # noqa: E402
import aruco_detect as A  # noqa: E402


def load() -> dict:
    if os.path.exists(PATH):
        return json.load(open(PATH, encoding="utf-8-sig"))
    return {"anchors": []}


def count() -> int:
    return len(load()["anchors"])


def save_anchor(entry: dict) -> int:
    """Append one anchor row; returns the new count."""
    for k in ("mark_px", "H_mm", "pose", "grab_tcp", "grab_rz"):
        if k not in entry:
            raise ValueError(f"anchor entry missing '{k}'")
    d = load()
    d["anchors"].append(entry)
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    return len(d["anchors"])


def _cam_u(px: float, py: float, H: float) -> np.ndarray:
    K, dist, _ = A.intrinsics()
    n = cv2.undistortPoints(np.array([[[px, py]]], np.float32), K, dist)
    return np.array([float(n[0, 0, 0]) * H, float(n[0, 0, 1]) * H])


def _world_from_u(tcp_xy, rz: float, u: np.ndarray, H: float) -> np.ndarray:
    """Full CURRENT camera model (live constants — refit-safe)."""
    raw = W.USCALE * np.asarray(u, float) + W.TILT * H
    v = np.array([raw[0], W.MIRROR * raw[1]])
    return (np.asarray(tcp_xy, float) + W.R(rz) @ W.CAM_ARM
            + W.R(rz + W.BPSI) @ v)


def derive(rows: list | None = None) -> list:
    """Per-anchor claw arm under the CURRENT camera model."""
    rows = load()["anchors"] if rows is None else rows
    out = []
    for a in rows:
        u = _cam_u(a["mark_px"][0], a["mark_px"][1], a["H_mm"])
        mw = _world_from_u(a["pose"][:2], a["pose"][2], u, a["H_mm"])
        arm = W.R(-float(a["grab_rz"])) @ (mw - np.asarray(a["grab_tcp"],
                                                          float))
        out.append({"name": a.get("name", "?"),
                    "marker_world": [round(float(mw[0]), 2),
                                     round(float(mw[1]), 2)],
                    "arm": [round(float(arm[0]), 2),
                            round(float(arm[1]), 2)]})
    return out


def derive_and_save(max_disagree_mm: float = 1.0) -> dict:
    """Re-derive the claw arm + wrist relation from all stored anchors and
    persist them (which restamps the model version). Refuses when anchors
    disagree beyond the gate — that means bad anchor data or a bad camera
    model, and the physical two-angle jog flow should arbitrate."""
    rows = derive()
    if not rows:
        return {"ok": False,
                "error": "no anchors stored — run Generate anchor (vendor "
                         "convergence) or the two-press jog flow first"}
    arms = np.array([r["arm"] for r in rows], float)
    mean = arms.mean(axis=0)
    dis = 0.0
    for i in range(len(arms)):
        for j in range(i + 1, len(arms)):
            dis = max(dis, float(np.hypot(*(arms[i] - arms[j]))))
    if len(rows) >= 2 and dis > max_disagree_mm:
        return {"ok": False, "rows": rows,
                "error": f"anchors disagree {dis:.2f} mm "
                         f"(> {max_disagree_mm:g}) — anchor data or camera "
                         "model suspect; use the two-angle jog derivation"}
    W.save_claw_arm([float(mean[0]), float(mean[1])],
                    note=f"auto-derived from {len(rows)} stored anchor(s), "
                         f"max disagreement {dis:.2f} mm")
    wrist_rel = W.wrap180(90.0 - float(np.degrees(
        np.arctan2(mean[1], mean[0]))))
    W.save_wrist_rel(wrist_rel)
    return {"ok": True, "n": len(rows), "rows": rows,
            "arm": [round(float(mean[0]), 2), round(float(mean[1]), 2)],
            "wrist_rel": round(float(wrist_rel), 2),
            "max_disagreement_mm": round(dis, 2),
            "single_anchor": len(rows) == 1}
