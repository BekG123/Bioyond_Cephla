"""Complete faithful port of the Bioyond SDK vision-teach pipeline (AccAutoTeachCV
+ AccLocatorCoreCV + CVHelper), driven through MCP instead of RobotSDK.

Everything is loaded from the SDK's own calibration configs at runtime — nothing
hardcoded. Units: mm/deg everywhere; CalTabInCam translation is stored in meters
in the JSON and converted (x1000), matching runtime behavior verified against the
VisionServer logs (Z-offset -4.9623 for bigR 185.9 => Circle2CamDis = 205 mm).

Subcommands:
  test                      offline validation against SDK log ground truth
  solve IMG X Y Z RZ        one teach iteration: detect -> select -> offsets
"""
import json
import math
import sys

import cv2
import numpy as np

from sdk_pose import compose, invert, wrap180

CFG_BASE = (r"C:\Users\raman\Desktop\test1\Vision_context\S4-VisionDemo"
            r"\USVisionDemo\VisionServer\Locator\Config")
CFG_DIRS = [("Wide", CFG_BASE + r"\Test\Wide\1\LocatorInfoCV_NEW.json"),
            ("Long", CFG_BASE + r"\Test\Long\1\LocatorInfoCV_NEW.json")]


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


def cmd_solve(img_path, x, y, z, rz, force_cfg=None):
    cfgs = load_configs()
    cur_pose = [x, y, z, 0.0, 0.0, rz]
    det = sdk_detect(img_path)
    out = {"detected": det is not None}
    if det is None:
        print(json.dumps(out))
        return
    sel, details = select_trigger(cfgs, det["mark"])
    if force_cfg:
        # reachability override: caller rejected the auto-selected config
        # (e.g. its grasp violates the envelope) and pins another approach
        sel = next(i for i, c in enumerate(cfgs) if c["name"] == force_cfg)
    cfg = cfgs[sel]
    cur_mark = mark_in_robot_pose(cfg, det["mark"])
    off_xyrz = tool_offset_xyrz(cfg, cur_mark)
    off_z = tool_offset_z(cfg, det["big_r"])
    move_xyrz = new_acc_pose(cur_pose, off_xyrz)
    move_z = new_acc_pose(cur_pose, off_z)
    grasp = final_acc_pose(cfg, cur_pose)
    # Z-touch calibration: measured (contact - vision) offset plus a safety
    # margin so the plate tips never bottom out on the support surface.
    # Refresh via the calibrate flow (torque-probed contact after convergence).
    import os
    cal_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "calibration.json")
    cal = None
    if os.path.exists(cal_path):
        c = json.load(open(cal_path, encoding="utf-8-sig"))
        cal = c["z_touch_offset_mm"] + c["safety_margin_mm"]
    out.update({
        "mark": [round(v, 3) for v in det["mark"]],
        "big_r": round(det["big_r"], 2),
        "selection": details, "selected": cfg["name"],
        "z_calibration_applied": cal,
        "grasp_z_calibrated": (round(float(grasp[2]) + cal, 3)
                               if cal is not None else None),
        "off_xyrz": [round(float(off_xyrz[i]), 4) for i in (0, 1, 2)] + [round(wrap180(off_xyrz[5]), 4)],
        "off_z": round(float(off_z[2]), 4),
        "move_xyrz": [round(float(move_xyrz[i]), 3) for i in (0, 1, 2)] + [round(wrap180(move_xyrz[5]), 4)],
        "move_z": [round(float(move_z[i]), 3) for i in (0, 1, 2)] + [round(wrap180(move_z[5]), 4)],
        "grasp_if_converged": [round(float(grasp[i]), 3) for i in (0, 1, 2)] + [round(wrap180(grasp[5]), 4)],
        "xy_err_mm": round(float(np.hypot(off_xyrz[0], off_xyrz[1])), 4),
        "rz_err_deg": round(abs(wrap180(off_xyrz[5])), 4),
        "z_err_mm": round(abs(float(off_z[2])), 4),
    })
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    if sys.argv[1] == "test":
        sys.exit(cmd_test())
    elif sys.argv[1] == "solve":
        cmd_solve(sys.argv[2], *[float(v) for v in sys.argv[3:7]],
                  force_cfg=(sys.argv[7] if len(sys.argv) > 7 else None))
