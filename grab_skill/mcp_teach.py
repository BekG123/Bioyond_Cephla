"""Historical vendor CLI; active calibration and math live in fast_disk.py."""
import json
import math
from pathlib import Path
import sys
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "operator_ui"))
from pick_and_hold.Calibration.fast_disk import (
    CFG_BASE, CFG_DIRS, compose, invert, wrap180,
    _arr, load_configs, _swap, sdk_detect, _detect_pair, image_points_to_world_plane, _rot_euler, trans_img_pos_2_world, mark_in_robot_pose, calc_image_offset, select_trigger, tool_offset_xyrz, tool_offset_z, new_acc_pose, final_acc_pose, cmd_test,
)


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
