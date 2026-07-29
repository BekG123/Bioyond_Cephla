"""Re-derive the claw arm under the CURRENT camera model (Path B — no
motion, no jogging; run after EVERY camera recalibration on this arm).

The claw arm is extracted from moments where the claw's world position is
GROUND TRUTH (physically verified grabs); only the marker_world half of
the identity  arm = R(-Rz) @ (marker_world - TCP)  depends on the camera
model. Re-deriving = re-solving the stored anchor pixels through the NEW
model and reusing the never-stale TCP pairings. Live validation
2026-07-28: this exact procedure fixed a 7.7 mm clamp-axis miss; the next
blind placement held dead-center first try.

Anchors (all image/config only, vendor-rooted):
  A) disk-day converged capture cap0035: the mark's pixel through the
     CURRENT model vs the demonstrated grab TCP (299.46,-317.15 @ 87.45).
  B) pure vendor constants (Vision_context calibration): taught mark pixel
     at taught optical distance + teach_in_trigger, evaluated at the same
     convergence pose, CURRENT model.
  C) validation: the 2026-07-24 well-plate grab that physically succeeded
     with +-1.5 mm clamp clearance at Rz -0.66 (cap0064 pre-grab capture
     re-solved under the CURRENT model vs its grab TCP (291.68,-70.45)).

Usage:
  py rederive_claw_arm.py           # print A/B arms + agreement + check C
  py rederive_claw_arm.py --save    # additionally save_claw_arm(mean) +
                                    # save_wrist_rel(90 - arm angle) so the
                                    # model-version stamps match again

Accept the result only when A and B agree within ~1 mm; a bigger gap
means an anchor capture/config path is wrong — do the UI two-angle jog
derivation instead. (Anchors are THIS arm's history: on a NEW arm there
are no anchors yet — use the UI 'Calibrate claw arm' two-press flow.)
"""
import sys
import json
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import cv2
import mcp_teach as T
import aruco_world as W
import aruco_detect as A
from sdk_pose import compose, wrap180


def cam_u_from_pixel(px, py, H):
    K, dist, _ = A.intrinsics()
    n = cv2.undistortPoints(np.array([[[px, py]]], np.float32), K, dist)
    return np.array([float(n[0, 0, 0]) * H, float(n[0, 0, 1]) * H])


def world_from_u(tcp_xy, rz, u, H):
    """CURRENT full model: TCP + R@cam_arm + R'@F@(s*u + tilt*H)."""
    raw = W.USCALE * np.asarray(u, float) + W.TILT * H
    v = np.array([raw[0], W.MIRROR * raw[1]])
    return (np.asarray(tcp_xy, float) + W.R(rz) @ W.CAM_ARM
            + W.R(rz + W.BPSI) @ v)


cfgs = T.load_configs()
cfg = next(c for c in cfgs if c["name"] == "Long")
dis = cfg["cal_tab_raw"][5] * 1000.0
model_radius = cfg["model_radius"]
TCP_DEMO = np.array([299.46, -317.15])
RZ_DEMO = 87.45

# ---- Path A: cap0035 mark pixel (1592.25, 1237.5), big_r 195.05
H035 = dis * model_radius / 195.05
uA = cam_u_from_pixel(1592.25, 1237.5, H035)
markA = world_from_u([357.557, -176.465], 68.187, uA, H035)
armA = W.R(-RZ_DEMO) @ (markA - TCP_DEMO)

# ---- Path B: taught pixel at taught distance, trigger from conv pose
mm_img = cfg["model_mark_img"]
uB = cam_u_from_pixel(mm_img[0], mm_img[1], dis)
markB = world_from_u([357.557, -176.465], 68.187, uB, dis)
conv = np.array([357.557, -176.465, 262.55, 0.0, 0.0, 68.187])
grabB = compose(conv, np.asarray(cfg["teach_in_trigger"], float))
armB = W.R(-float(grabB[5])) @ (markB - grabB[:2])

print("markA (current model):", np.round(markA, 2),
      " armA:", np.round(armA, 2))
print("markB (current model):", np.round(markB, 2),
      " armB:", np.round(armB, 2), " grabB TCP:",
      [round(float(grabB[0]), 2), round(float(grabB[1]), 2),
       round(wrap180(float(grabB[5])), 2)])
print("A-B disagreement:", np.round(armA - armB, 2))

# ---- Validation C: well-plate grab (clamp axis ~X at Rz -0.66)
s64 = W.solve(r"C:\Users\raman\Desktop\test1\bioyond-s4-mcp\captures"
              r"\cap0064_gige_raw.jpg", 447.9, -106.5, 306.0, -30.0)
mw64 = np.array(s64["marker_world"][:2])
tcpC = np.array([291.68, -70.45])
rzC = -0.66
arm_mean = (armA + armB) / 2.0
claw_pred = tcpC + W.R(rzC) @ arm_mean
print("cap0064 marker (current model):", np.round(mw64, 2))
print("grab-C claw with NEW arm:", np.round(claw_pred, 2),
      " clamp-axis (X) miss vs marker:",
      round(float(claw_pred[0] - mw64[0]), 2),
      "mm (physical grip tolerated +-1.5)")

# ---- Compare with the stored arm and optionally save
print("stored arm in calibration.json:", W.CLAW_ARM.tolist())
print("delta new-mean vs stored:", np.round(arm_mean - W.CLAW_ARM, 2))
print("proposed arm:", np.round(arm_mean, 2))
agree = float(np.hypot(*(armA - armB)))
wrist_rel = wrap180(90.0 - float(np.degrees(
    np.arctan2(arm_mean[1], arm_mean[0]))))
print("proposed wrist_rel (90 - arm angle): %.2f" % wrist_rel)
if "--save" in sys.argv:
    if agree > 1.0:
        sys.exit("REFUSING to save: A-B anchors disagree %.2f mm (> 1.0) "
                 "— re-check anchors or use the UI two-angle jog flow."
                 % agree)
    W.save_claw_arm(arm_mean.tolist(),
                    note="rederive_claw_arm.py (vendor anchors A+B, "
                         "agreement %.2f mm)" % agree)
    W.save_wrist_rel(wrist_rel)
    print("SAVED claw_arm + wrist_rel; model-version stamps now match "
          "the current camera fit.")
