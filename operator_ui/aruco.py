"""ArUco solve for the operator console.

Thin wrapper around grab_skill/aruco_world.py — the anchor-free pipeline
validated live 2026-07-24 (three blind placements, torque-saturated grips):
marker world pose through the FITTED eye-camera model, grab TCP through the
measured 184 mm claw lever arm. All constants live in
grab_skill/calibration.json (eye_cam_fit + claw_arm_tool_mm); nothing here
is hardcoded to any object position.
"""

from __future__ import annotations

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GRAB_DIR = os.path.join(os.path.dirname(HERE), "grab_skill")
if GRAB_DIR not in sys.path:
    sys.path.insert(0, GRAB_DIR)

import anchors as ANC  # noqa: E402
import aruco_world as W  # noqa: E402

CAM_ARM = W.CAM_ARM            # camera lever arm in the tool frame
CLAW_ARM = W.CLAW_ARM          # claw lever arm in the tool frame (~184 mm)
Z_TOUCH = W.Z_TOUCH            # grip Z = marker Z + this (no safety margin)
MARKER_SIZE_MM = W.SIZE_MM


def solve(img_path: str, x: float, y: float, z: float, rz: float) -> dict:
    """One anchor-free solve at the given pose (mm/deg). Returns the
    aruco_world dict: marker_world, marker_yaw_deg, grab_candidates
    (claw-arm-compensated TCP + wrist Rz, reach/feasibility), grip_z."""
    return W.solve(img_path, x, y, z, rz)


def view_center_world(x: float, y: float, rz: float, h_mm: float = None):
    """World XY the camera looks at (its optical-axis ground point) — used
    to CENTER the marker in view before trusting a solve (off-center /
    off-range views showed a +12 mm bias live). When the camera height H
    is known (any solve's H_mm), the fitted axis-tilt term is included —
    at H~230 it shifts the true view center ~10 mm, which previously left
    a systematic centering residual."""
    c = np.array([x, y]) + W.R(rz) @ W.CAM_ARM   # live constants (refit-safe)
    if h_mm:
        t = np.array([1.0, W.MIRROR]) * (W.TILT * float(h_mm))
        c = c + W.R(rz + W.BPSI) @ t
    return float(c[0]), float(c[1])


def grip_z_offset(marker_id: int) -> float:
    """Marker->grip-TCP height for this id: the per-object value when the
    disk calibration stores one (recessed markers), else the global
    z-touch. Live constants — refit/save-safe."""
    return W.grip_z_offset(marker_id)


def model_stamps():
    """(camera_fit_version, claw_arm_version). A mismatch means the claw
    arm was derived under an OLDER camera model — the stale-constant trap
    that cost a 7.7 mm miss live; re-derive the arm after every refit."""
    return ((W.CAL.get("eye_cam_fit") or {}).get("fitted"),
            W.CAL.get("claw_arm_model_version"))


def save_anchor(entry: dict) -> int:
    """Persist one ground-truth anchor row (Generate anchor button)."""
    return ANC.save_anchor(entry)


def anchors_count() -> int:
    return ANC.count()


def derive_arm_from_anchors() -> dict:
    """Re-derive + save claw arm and wrist relation from the stored
    anchors under the CURRENT camera model (restamps the model version).
    Called automatically at the end of Calibrate camera."""
    return ANC.derive_and_save()


def detect_raw(img_path: str):
    """First detected marker's raw measurement (pnp u, H, cam yaw, id) —
    the calibrate-camera sequence's data row source."""
    ms = W.A.detect(img_path, W.SIZE_MM)
    return ms[0] if ms else None


def fit_mount(rows):
    return W.fit_mount(rows)


def save_mount(fitres: dict) -> dict:
    return W.save_mount(fitres)


def save_claw_arm(arm_xy, note: str = ""):
    return W.save_claw_arm(arm_xy, note)


def save_wrist_rel(rel_deg: float) -> dict:
    return W.save_wrist_rel(rel_deg)


def calibrate(img_path: str, x: float, y: float, z: float,
              rz: float) -> dict:
    """Edge-detect the disk carrying the marker (contrast background) and
    measure the marker->disk relation; see aruco_world.calibrate_disk."""
    return W.calibrate_disk(img_path, x, y, z, rz)


def save_disk(marker_id: int, entry: dict, note: str = "") -> dict:
    return W.save_disk_cal(marker_id, entry, note)


def annotate_calibration(img_path: str, cal: dict,
                         max_edge: int = 1400) -> str:
    """Draw the detected disk rectangle + marker/disk centers on the
    capture for the operator's detection panel."""
    import cv2
    img = cv2.imread(img_path)
    if img is None:
        raise RuntimeError(f"cannot read {img_path}")
    box = np.array(cal["rect"]["box"], np.int32)
    cv2.polylines(img, [box], True, (0, 230, 0), 4)
    mc = tuple(int(round(v)) for v in cal["marker"]["center_px"])
    dc = tuple(int(round(v)) for v in cal["rect"]["center_px"])
    cv2.drawMarker(img, mc, (0, 0, 255), cv2.MARKER_CROSS, 60, 3)
    cv2.drawMarker(img, dc, (0, 220, 255), cv2.MARKER_CROSS, 80, 3)
    cv2.line(img, mc, dc, (0, 220, 255), 2)
    e = cal["entry"]
    cv2.putText(img, f"disk {e['length_mm']}x{e['width_mm']}mm  offset "
                     f"({e['dx_mm']},{e['dy_mm']})mm  relyaw "
                     f"{e['rel_yaw_deg']}deg",
                (dc[0] - 200, dc[1] - 60), cv2.FONT_HERSHEY_SIMPLEX,
                1.2, (0, 220, 255), 3)
    h, w = img.shape[:2]
    scale = max_edge / max(h, w)
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)),
                         interpolation=cv2.INTER_AREA)
    out = os.path.splitext(img_path)[0] + "_det.jpg"
    cv2.imwrite(out, img)
    return out
