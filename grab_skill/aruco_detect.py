"""ArUco marker -> robot-frame pose AND grasp solve for the S4 eye-in-hand camera.

Mirrors the calibration-disk teach (mcp_teach.cmd_solve) so a marker grab runs the
same way a board grab does. Two geometries, both loaded from the SDK configs — nothing
guessed:

  * Eye-camera geometry: IPPE-square PnP on the 4 corners with the known side length,
    using CamParam intrinsics + distortion, then CamInTool (hand-eye) to reach the tool
    frame. PnP gives full metric 6-DOF in one shot, replacing the board's circle-pair
    plane back-projection + radius-scale Z.
  * Grabbing-handle geometry: the gripper offset the board teach stores as
    ModelMarkInRobot (mark-in-tool at the grip anchor) + TeachInTrigger (sighting ->
    grasp descent). Composed once into a fixed marker->grasp transform
    G = compose(invert(ModelMarkInRobot), TeachInTrigger) (verified to reproduce the
    run-6 grasp to 0 mm). This is what turns a marker CENTROID into a pose the comb
    plates can actually straddle at grip depth.

So the output is a grasp-ready solve — marker_robot pose, move_xyrz (center + wrist at
sighting height), grasp_if_converged, grasp_z_calibrated, and convergence errors — the
same schema Phase 2/3 of the grab skill consumes, not just the marker's location.

Grip-geometry caveat: G comes from the calibration board's taught anchors, so the grasp
assumes the marker sits where the board's circle-pair mark sat. If the marker is mounted
elsewhere on the part, pass a mark_offset (marker->mark, mm/deg) — default identity.

Usage:
  py aruco_detect.py detect IMG [size_mm]                   # detection only
  py aruco_detect.py solve  IMG X Y Z RZ [size_mm] [cfg]    # full grasp solve
  py aruco_detect.py test                                   # offline validation

Frames MUST be captured with gige_capture(grid=false): the coordinate-grid overlay
crosses the marker quad and blocks detection.
"""
import json
import math
import os
import sys

import cv2
import numpy as np

from mcp_teach import load_configs, _swap
from sdk_pose import compose, invert, wrap180

DEFAULT_SIZE_MM = 20.0
IDENTITY = np.zeros(6)
REACH_MAX_MM = 480.0          # fault 3570 beyond this (matches the skill radius guard)
ENV_Z = (35.0, 420.0)         # working Z envelope used for the nest/deck area
CAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")


def intrinsics(cfg=None):
    """K, distortion and CamInTool from a config (both configs share these)."""
    cfg = cfg or load_configs()[0]
    p = cfg["cam_param"]
    f = p[0] * 1000.0
    sx, sy = p[6] * 1000.0, p[7] * 1000.0
    K = np.array([[f / sx, 0, p[8]], [0, f / sy, p[9]], [0, 0, 1.0]])
    dist = np.array([p[1] * f**2, p[2] * f**4, p[5] * f, p[4] * f, p[3] * f**6])
    cam_in_tool = _swap(cfg["cam_in_tool_raw"].copy())
    return K, dist, cam_in_tool


def grip_transform(cfg, mark_offset=None):
    """Fixed marker->grasp transform G (the grabbing-handle geometry).

    G = compose(invert(ModelMarkInRobot), TeachInTrigger): apply it to the marker's
    robot-frame pose and you get the TCP grasp pose. compose(marker, G) reproduces the
    board's validated run-6 grasp exactly (see cmd_test). mark_offset (marker->mark)
    shifts the anchor when the marker is not where the board's mark was.
    """
    G = compose(invert(cfg["model_mark_robot"]), cfg["teach_in_trigger"])
    if mark_offset is not None and np.any(mark_offset):
        G = compose(np.asarray(mark_offset, float), G)
    return G


def detect(img_path, size_mm=DEFAULT_SIZE_MM):
    """ArUco detect + IPPE-square PnP -> marker pose in the CAMERA frame."""
    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return []
    mean = float(img.mean())
    if 1.0 < mean < 100.0:                    # match the teach detector's normalization
        img = np.clip(img.astype(np.float32) * (150.0 / mean), 0, 255).astype(np.uint8)
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    params = cv2.aruco.DetectorParameters()
    # A marker filling ~400 px on this 3072-wide sensor needs larger adaptive-threshold
    # windows than the default max (23): the marker cells are big, so a small window sees
    # only one shade and never separates border from quiet zone. 53 was needed live to
    # detect id 3 on the glossy deck plate; the finer step keeps small markers working.
    params.adaptiveThreshWinSizeMin = 3
    params.adaptiveThreshWinSizeMax = 53
    params.adaptiveThreshWinSizeStep = 4
    det = cv2.aruco.ArucoDetector(d, params)
    corners, ids, _ = det.detectMarkers(img)
    if ids is None:
        return []
    K, dist, _ = intrinsics()
    half = size_mm / 2.0
    obj = np.array([[-half, half, 0], [half, half, 0],
                    [half, -half, 0], [-half, -half, 0]], np.float32)
    out = []
    for c, mid in zip(corners, ids.flatten()):
        # Undistort corners with the SDK's validated intrinsics (the same undistortPoints
        # call the teach's TransImgPos2World uses), then PnP on the normalized points with
        # identity K. The SDK distortion coefficients are metric-scaled (k1~3e4) and blow
        # up cv2's *forward* model, so they must never be handed to solvePnP directly.
        und = cv2.undistortPoints(c[0].reshape(-1, 1, 2).astype(np.float32), K, dist)
        ok, rvec, tvec = cv2.solvePnP(obj, und.reshape(-1, 1, 2), np.eye(3), None,
                                      flags=cv2.SOLVEPNP_IPPE_SQUARE)
        if not ok:
            continue
        R, _ = cv2.Rodrigues(rvec)
        yaw_cam = float(np.degrees(np.arctan2(R[1, 0], R[0, 0])))
        out.append({
            "id": int(mid),
            "center_px": [round(float(c[0][:, 0].mean()), 1),
                          round(float(c[0][:, 1].mean()), 1)],
            "corners_px": [[round(float(x), 1), round(float(y), 1)] for x, y in c[0]],
            "cam_xyz_mm": [round(float(v), 2) for v in tvec.flatten()],
            "cam_yaw_deg": round(yaw_cam, 3),
            "side_px": round(float(np.mean([np.linalg.norm(c[0][i] - c[0][(i + 1) % 4])
                                            for i in range(4)])), 1),
        })
    return out


def marker_robot_pose(marker, robot_pose, cam_in_tool):
    """Marker pose in the ROBOT frame: robot_pose x CamInTool x (marker-in-cam)."""
    x, y, z = marker["cam_xyz_mm"]
    marker_in_cam = np.array([x, y, z, 0.0, 0.0, marker["cam_yaw_deg"]])
    return compose(np.asarray(robot_pose, float), compose(cam_in_tool, marker_in_cam))


def _reach(pose):
    return math.hypot(pose[0], pose[1])


def _candidate(cfg, marker_robot, cur_pose, mark_offset):
    """Grasp pose for one grip approach + reachability/wrist metrics (like the board's
    Wide/Long straddle choice)."""
    grasp = compose(marker_robot, grip_transform(cfg, mark_offset))
    aligned = compose(marker_robot, invert(cfg["model_mark_robot"]))   # sighting align
    reach = _reach(grasp)
    return {
        "cfg": cfg["name"],
        "grasp": grasp,
        "aligned": aligned,
        "reach_mm": round(reach, 1),
        "in_reach": bool(reach < REACH_MAX_MM),
        "z_in_envelope": bool(ENV_Z[0] <= grasp[2] <= ENV_Z[1]),
        "wrist_travel_deg": round(abs(wrap180(grasp[5] - cur_pose[5])), 1),
    }


def select(cands, force_cfg=None):
    """Pick the grip approach: forced, else reachable + in-envelope with least wrist
    travel; falls back to least out-of-reach so the caller still sees a best effort."""
    if force_cfg:
        return next(c for c in cands if c["cfg"] == force_cfg)
    valid = [c for c in cands if c["in_reach"] and c["z_in_envelope"]]
    pool = valid or cands
    return min(pool, key=lambda c: (not (c["in_reach"] and c["z_in_envelope"]),
                                    c["wrist_travel_deg"]))


def _read_cal():
    if not os.path.exists(CAL_PATH):
        return None
    c = json.load(open(CAL_PATH, encoding="utf-8-sig"))
    return c["z_touch_offset_mm"] + c["safety_margin_mm"]


def solve(img_path, x, y, z, rz, size_mm=DEFAULT_SIZE_MM, force_cfg=None,
          target_id=None, mark_offset=None):
    cfgs = load_configs()
    _, _, cam_in_tool = intrinsics(cfgs[0])
    cur_pose = np.array([x, y, z, 0.0, 0.0, rz])
    markers = detect(img_path, size_mm)
    out = {"detected": len(markers) > 0, "n": len(markers),
           "ids": [m["id"] for m in markers]}
    if not markers:
        print(json.dumps(out, indent=1))
        return out
    m = (next((mm for mm in markers if mm["id"] == target_id), markers[0])
         if target_id is not None else markers[0])
    marker_robot = marker_robot_pose(m, cur_pose, cam_in_tool)

    cands = [_candidate(c, marker_robot, cur_pose, mark_offset) for c in cfgs]
    sel = select(cands, force_cfg)
    aligned, grasp = sel["aligned"], sel["grasp"]
    move_xyrz = [round(float(aligned[0]), 3), round(float(aligned[1]), 3),
                 round(float(z), 3), round(wrap180(aligned[5]), 3)]   # hold sighting Z
    cal = _read_cal()
    out.update({
        "target_id": m["id"],
        "center_px": m["center_px"], "side_px": m["side_px"],
        "cam_xyz_mm": m["cam_xyz_mm"], "cam_yaw_deg": m["cam_yaw_deg"],
        # the plain position estimate (marker centroid in the robot frame)
        "marker_robot_xyz_mm": [round(float(v), 2) for v in marker_robot[:3]],
        "marker_robot_yaw_deg": round(wrap180(marker_robot[5]), 3),
        # grip-approach selection (Wide/Long straddle), mirrors the board's selection
        "selection": [{"cfg": c["cfg"], "reach_mm": c["reach_mm"],
                       "in_reach": c["in_reach"], "z_in_envelope": c["z_in_envelope"],
                       "wrist_travel_deg": c["wrist_travel_deg"],
                       "grasp_z_mm": round(float(c["grasp"][2]), 2)} for c in cands],
        "selected": sel["cfg"],
        # go here first (center marker under the grip anchor + set wrist at safe Z),
        # then descend to the grasp — same convergence loop as the board teach
        "move_xyrz": move_xyrz,
        "xy_err_mm": round(float(math.hypot(aligned[0] - x, aligned[1] - y)), 3),
        "rz_err_deg": round(abs(wrap180(aligned[5] - rz)), 3),
        "grasp_if_converged": [round(float(grasp[0]), 3), round(float(grasp[1]), 3),
                               round(float(grasp[2]), 3), round(wrap180(grasp[5]), 3)],
        "z_calibration_applied": cal,
        "grasp_z_calibrated": (round(float(grasp[2]) + cal, 3) if cal is not None else None),
        "reach_mm": sel["reach_mm"],
        "reachable": bool(sel["in_reach"] and sel["z_in_envelope"]),
        "grasp_assumes": "marker at the board's taught mark location; pass mark_offset if not",
    })
    print(json.dumps(out, indent=1))
    return out


def cmd_test():
    """Offline validation: grip geometry vs run-6 ground truth + PnP round-trip."""
    ok = True
    cfgs = {c["name"]: c for c in load_configs()}
    wide = cfgs["Wide"]

    # GT1: G reproduces the validated run-6 grasp (the grabbing-handle geometry).
    grasp_run6 = np.array([217.081721556673, -321.412455335999, 41.863, 0, 0, 0.3476])
    C = compose(grasp_run6, invert(wide["teach_in_trigger"]))      # implied sighting pose
    marker_robot = compose(C, wide["model_mark_robot"])            # mark in robot frame
    grasp = compose(marker_robot, grip_transform(wide))
    e1 = max(np.abs(grasp[:3] - grasp_run6[:3]).max(), abs(wrap180(grasp[5]) - grasp_run6[5]))
    print(f"GT1 grip geometry: grasp {np.round(grasp[:3],3)} Rz {wrap180(grasp[5]):.4f} "
          f"vs run-6 {np.round(grasp_run6[:3],3)} Rz {grasp_run6[5]:.4f} "
          f"err {e1:.2e} {'PASS' if e1 < 1e-6 else 'FAIL'}")
    ok &= e1 < 1e-6

    # GT2: aligned-sighting + TeachInTrigger == grasp (the two-step move is consistent).
    aligned = compose(marker_robot, invert(wide["model_mark_robot"]))
    grasp2 = compose(aligned, wide["teach_in_trigger"])
    e2 = np.abs(grasp2 - grasp).max()
    print(f"GT2 move_xyrz->grasp consistency: err {e2:.2e} {'PASS' if e2 < 1e-6 else 'FAIL'}")
    ok &= e2 < 1e-6

    # GT3: PnP path round-trip. Project known corners through a pure pinhole to the
    # normalized plane (the space detect() runs PnP in after undistortion) and recover
    # the pose -> cam_xyz within the noise floor.
    half = DEFAULT_SIZE_MM / 2.0
    obj = np.array([[-half, half, 0], [half, half, 0],
                    [half, -half, 0], [-half, -half, 0]], np.float32)
    Rt, _ = cv2.Rodrigues(np.array([0.02, -0.03, 0.3]))
    tvec_t = np.array([12.0, -8.0, 205.0])
    cam = (Rt @ obj.T).T + tvec_t
    norm = (cam[:, :2] / cam[:, 2:3]).reshape(-1, 1, 2).astype(np.float32)
    ok3, rvec, tvec = cv2.solvePnP(obj, norm, np.eye(3), None,
                                   flags=cv2.SOLVEPNP_IPPE_SQUARE)
    e3 = np.abs(tvec.flatten() - tvec_t).max()
    print(f"GT3 PnP round-trip: cam_xyz {np.round(tvec.flatten(),3)} vs "
          f"{tvec_t} err {e3:.4f} mm {'PASS' if ok3 and e3 < 0.05 else 'FAIL'}")
    ok &= ok3 and e3 < 0.05

    # GT4: detector recovers ids from the reference marker PNGs.
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    adet = cv2.aruco.ArucoDetector(d, cv2.aruco.DetectorParameters())
    mdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "markers")
    found = []
    for i in range(4):
        p = os.path.join(mdir, f"aruco_4x4_50_id{i}.png")
        if not os.path.exists(p):
            continue
        im = cv2.copyMakeBorder(cv2.imread(p, cv2.IMREAD_GRAYSCALE), 60, 60, 60, 60,
                                cv2.BORDER_CONSTANT, value=255)
        _, ids, _ = adet.detectMarkers(im)
        found.append(None if ids is None else int(ids.flatten()[0]))
    e4 = found == list(range(len(found))) and len(found) > 0
    print(f"GT4 marker detection: ids {found} {'PASS' if e4 else 'FAIL'}")
    ok &= e4

    print("ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "test":
        sys.exit(cmd_test())
    elif cmd == "detect":
        size = float(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_SIZE_MM
        ms = detect(sys.argv[2], size)
        print(json.dumps({"markers": ms, "n": len(ms)}, indent=1))
    elif cmd == "solve":
        size = float(sys.argv[7]) if len(sys.argv) > 7 else DEFAULT_SIZE_MM
        fcfg = sys.argv[8] if len(sys.argv) > 8 else None
        solve(sys.argv[2], *[float(v) for v in sys.argv[3:7]], size_mm=size, force_cfg=fcfg)
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        sys.exit(2)
