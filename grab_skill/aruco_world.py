"""Anchor-free ArUco -> world -> grab-TCP solve for the S4.

Uses the constants measured 2026-07-24 (stored in calibration.json):
  - eye_cam_fit: camera lever arm / yaw offset / mirror in the TOOL frame
    (6-view least-squares fit, RMS 2.35 mm, model selection over mounting
    frames — the camera rotates with Rz)
  - claw_arm_tool_mm: physical claw midpoint vs the reported TCP
    (two independent anchor-free derivations agreeing to 0.4 mm)

Math:
  marker_world = TCP + R(Rz) @ cam_arm + R(Rz + yaw_off) @ diag(1, f) @ u_pnp
  grab_TCP     = marker_world - R(Rz_grab) @ claw_arm
  Rz_grab      = marker_world_yaw + WRIST_REL   (demo wrist-vs-mark relation;
                 the ±180 twin is reported too — claw is symmetric)

Usage:
  py aruco_world.py solve IMG X Y Z RZ [size_mm]
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aruco_detect as A  # noqa: E402

CAL = json.load(open(os.path.join(HERE, "calibration.json"),
                     encoding="utf-8-sig"))
FIT = CAL["eye_cam_fit"]
CAM_ARM = np.array(FIT["lever_arm_mm"], float)
BPSI = float(FIT["yaw_offset_deg"])
MIRROR = float(FIT["mirror_f"])
CLAW_ARM = np.array(CAL["claw_arm_tool_mm"], float)
SIZE_MM = float(FIT["aruco_marker_size_mm"])
TILT = np.array(FIT.get("tilt_per_mm", [0.0, 0.0]), float)
USCALE = float(FIT.get("u_scale", 1.0))
HSCALE = float(FIT.get("h_scale", 1.0))
# ALL arm-specific values live in calibration.json (portable to other
# arms — recalibrate there, never edit code).
# WRIST_REL is a PURE CLAW constant: the grab wrist angle relative to the
# DISK'S LONG AXIS (per-id rel_yaw supplies the marker-print orientation).
# Geometric default: 90 - claw-arm angle makes the two opposite approach
# TCPs exactly perpendicular to the plate edge; a stored value may add a
# small clamp-plane trim on top.
_ARM_ANG = float(np.degrees(np.arctan2(CLAW_ARM[1], CLAW_ARM[0])))
WRIST_REL = float(CAL.get("wrist_rel_deg", 90.0 - _ARM_ANG))
CAM_Z_OFF = float(CAL.get("cam_z_offset_mm", 32.1))
Z_TOUCH = float(CAL["z_touch_offset_mm"]) + float(CAL["safety_margin_mm"])


def _arm_limits():
    # arm feasibility params from robot_params.json. With the fitted
    # planar model (base offset + links, EXACT fit 2026-07-28) the guard
    # is the extension circle around the ARM BASE — the world origin is
    # NOT the rotation center (base sits at (126, 0) on this arm; the
    # 3570 fault target was 3.6 mm past true full stretch). Legacy
    # origin-circle fallback when the kinematic block is absent.
    d = {"reach_hard_mm": 480.0, "base_x_mm": 0.0, "base_y_mm": 0.0,
         "link1_mm": 0.0, "link2_mm": 0.0, "extension_margin_mm": 15.0,
         "claw_gap_min_mm": 60.0, "claw_gap_max_mm": 88.0}
    for p in (os.path.join(HERE, "robot_params.json"),
              os.path.join(os.path.dirname(HERE), "operator_ui",
                           "robot_params.json")):
        try:
            j = json.load(open(p, encoding="utf-8-sig"))
            d.update({k: float(v) for k, v in j.items() if k in d})
            break
        except (OSError, ValueError):
            continue
    return d


_LIM = _arm_limits()


def _tcp_reachable(tcp) -> bool:
    if _LIM["link1_mm"] > 0 and _LIM["link2_mm"] > 0:
        ext = float(np.hypot(tcp[0] - _LIM["base_x_mm"],
                             tcp[1] - _LIM["base_y_mm"]))
        return ext <= (_LIM["link1_mm"] + _LIM["link2_mm"]
                       - _LIM["extension_margin_mm"])
    return float(np.hypot(*tcp)) < _LIM["reach_hard_mm"]


def R(deg):
    a = np.radians(deg)
    return np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])


def wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


def marker_offset(marker_id: int):
    """Learned grasp correction for this marker id, in the MARKER frame
    (rotates with the object). Written by calibrate_disk (edge-detected
    disk center vs marker) or by the operator-jog save; applied to every
    later solve."""
    offs = CAL.get("marker_offsets", {})
    o = offs.get(str(marker_id))
    if not o:
        return np.zeros(2)
    return np.array([float(o.get("dx_mm", 0.0)), float(o.get("dy_mm", 0.0))])


def grip_z_offset(marker_id: int) -> float:
    """Per-object marker->grip-TCP height delta. The flat z_touch (+9)
    assumes the marker lies flush on the object's top; objects whose
    marker sits RECESSED (e.g. inside a parts tray on its contents) need
    their own value — live 2026-07-28 a ring tray's marker sat ~13 mm
    below the grip plane and the torque guard's contact stop measured
    the true depth (stored as marker_offsets[id].grip_z_offset_mm)."""
    o = CAL.get("marker_offsets", {}).get(str(marker_id)) or {}
    v = o.get("grip_z_offset_mm")
    return float(v) if v is not None else Z_TOUCH


def find_disk_rect(img_path, marker):
    """Edge-detect the actual disk/tray carrying the marker on a CONTRASTED
    background: Otsu threshold (both polarities tried), pick the contour
    that CONTAINS the marker center and has a plausible area, fit a
    min-area rectangle. Returns dict with center px, size px, long-axis
    image angle (deg, y-down pixel frame) and the contour, or None."""
    import cv2
    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    mean = float(img.mean())
    if 1.0 < mean < 100.0:
        img = np.clip(img.astype(np.float32) * (150.0 / mean),
                      0, 255).astype(np.uint8)
    blur = cv2.GaussianBlur(img, (9, 9), 0)
    mcx, mcy = marker["center_px"]
    side = marker["side_px"]
    best = None
    for inv in (cv2.THRESH_BINARY_INV, cv2.THRESH_BINARY):
        _, bw = cv2.threshold(blur, 0, 255, inv + cv2.THRESH_OTSU)
        bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE,
                              np.ones((15, 15), np.uint8))
        cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            area = cv2.contourArea(c)
            # bigger than the marker, smaller than most of the frame
            if not (2.5 * side * side < area
                    < 0.6 * img.shape[0] * img.shape[1]):
                continue
            if cv2.pointPolygonTest(c, (float(mcx), float(mcy)),
                                    False) < 0:
                continue
            if best is None or area < best[0]:
                best = (area, c)          # smallest qualifying = the disk,
                                          # not a merged background blob
    if best is None:
        return None
    rect = cv2.minAreaRect(best[1])
    (rcx, rcy), (w, h), ang = rect
    # long-axis direction in image coords (y down)
    if w >= h:
        long_px, short_px, axis_deg = w, h, ang
    else:
        long_px, short_px, axis_deg = h, w, ang + 90.0
    return {"center_px": [round(float(rcx), 1), round(float(rcy), 1)],
            "long_px": round(float(long_px), 1),
            "short_px": round(float(short_px), 1),
            "axis_img_deg": round(float(axis_deg), 2),
            "box": cv2.boxPoints(rect).tolist(),
            "contour": best[1]}


def detect_sized(img_path, size_mm=None):
    """Keep the camera fit intact; apply each sticker's actual metric size.

    PnP translation scales linearly with square size; image corners and rotation
    do not. Explicit size overrides the registry (legacy CLI support).
    """
    base = SIZE_MM if size_mm is None else float(size_mm)
    if not math.isfinite(base) or base <= 0:
        raise ValueError('marker size must be positive and finite')
    markers = A.detect(img_path, base)
    result = []
    for marker in markers:
        actual = float(CAL.get('marker_sizes_mm', {}).get(str(int(marker['id'])), base)) if size_mm is None else base
        if not math.isfinite(actual) or actual <= 0:
            raise ValueError('registered marker size must be positive and finite')
        row = dict(marker)
        row['cam_xyz_mm'] = [float(v)*actual/base for v in marker['cam_xyz_mm']]
        row['marker_size_mm'] = actual
        result.append(row)
    return result


def calibrate_disk(img_path, x, y, z, rz, size_mm=None, marker_id=None):
    """One-time per-ID calibration on a contrasting background: measure the
    marker AND the disk's edges; return the marker->disk-center offset in
    the MARKER frame, the disk yaw relative to the marker, and the true
    spans in mm. Save with save_disk_cal() — afterwards a single image of
    the marker on ANY background yields the correct grab."""
    ms = detect_sized(img_path, size_mm)
    if marker_id is not None:
        ms = [m for m in ms if int(m['id']) == marker_id]
    if not ms:
        return {"ok": False, "error": "no marker detected"}
    if len(ms) != 1:
        return {'ok':False,'error':'Multiple markers detected; select one marker ID explicitly for calibration'}
    m = ms[0]
    size_mm = m['marker_size_mm']
    rect = find_disk_rect(img_path, m)
    if rect is None:
        return {"ok": False, "error": "disk edges not found — increase the "
                "background contrast (plain light/dark sheet under the "
                "disk) and retry"}
    import cv2
    image = cv2.imread(img_path)
    if image is None:
        return {"ok": False, "error": "calibration image unavailable"}
    height, width = image.shape[:2]
    if any(not (2 < px < width-3 and 2 < py < height-3) for px, py in rect["box"]):
        return {"ok": False, "error": "plate outline clipped; calibration not saved"}
    K, dist, _ = A.intrinsics()
    H = float(m["cam_xyz_mm"][2])
    if not 205 <= H <= 240:
        return {"ok": False, "error": "camera distance outside commissioned 205-240 mm range"}
    pts = np.array([[m["center_px"]], [rect["center_px"]]], np.float32)
    n = cv2.undistortPoints(pts, K, dist).reshape(2, 2)
    # camera-frame mm at the marker plane (disk top == marker plane)
    d_cam = (n[1] - n[0]) * H
    d_world = R(rz + BPSI) @ np.array([d_cam[0], MIRROR * d_cam[1]])
    marker_yaw = wrap180(rz + BPSI + MIRROR * m["cam_yaw_deg"])
    off_marker = R(-marker_yaw) @ d_world
    # disk long-axis: image direction -> world (same rotation chain)
    a = np.radians(rect["axis_img_deg"])
    img_dir = np.array([np.cos(a), np.sin(a)])
    wd = R(rz + BPSI) @ np.array([img_dir[0], MIRROR * img_dir[1]])
    disk_yaw = wrap180(float(np.degrees(np.arctan2(wd[1], wd[0]))))
    mm_per_px = size_mm / float(m["side_px"])
    entry = {
        "dx_mm": round(float(off_marker[0]), 2),
        "dy_mm": round(float(off_marker[1]), 2),
        "rel_yaw_deg": round(wrap180(disk_yaw - marker_yaw), 2),
        "length_mm": round(rect["long_px"] * mm_per_px, 1),
        "width_mm": round(rect["short_px"] * mm_per_px, 1),
    }
    return {"ok": True, "id": int(m["id"]), "entry": entry,
            "marker_yaw_deg": round(float(marker_yaw), 2),
            "disk_yaw_deg": round(float(disk_yaw), 2),
            "offset_world_mm": [round(float(d_world[0]), 2),
                                round(float(d_world[1]), 2)],
            "rect": {k: rect[k] for k in ("center_px", "long_px",
                                          "short_px", "axis_img_deg",
                                          "box")},
            "marker": {"center_px": m["center_px"],
                       "side_px": m["side_px"]}}


def save_disk_cal(marker_id: int, entry: dict, note: str = "") -> dict:
    """Persist a calibrate_disk entry for this id (and refresh the loaded
    CAL so the running process uses it immediately)."""
    path = os.path.join(HERE, "calibration.json")
    c = json.load(open(path, encoding="utf-8-sig"))
    e = dict(entry)
    e["note"] = note or "calibrate_disk (edge-detected on contrast bg)"
    import time as _t
    e["date"] = _t.strftime("%Y-%m-%d %H:%M")
    c.setdefault("marker_offsets", {})[str(marker_id)] = e
    with open(path, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=1)
    CAL.setdefault("marker_offsets", {})[str(marker_id)] = e
    return e


def solve(img_path, x, y, z, rz, size_mm=None, marker_id=None):
    ms = detect_sized(img_path, size_mm)
    if marker_id is not None:
        ms = [m for m in ms if int(m["id"]) == marker_id]
        if len(ms) != 1:  # duplicate IDs / reflections are ambiguous
            return {"detected": False, "reason": "requested marker missing or ambiguous"}
    if not ms:
        return {"detected": False}
    if len(ms) != 1:
        return {"detected": False, "reason": "multiple markers; select a unique marker ID"}
    m = ms[0]
    H = float(m["cam_xyz_mm"][2])
    # u_scale: parallax-scale correction (spread-test 2026-07-25 showed a
    # ~15% residual); tilt: non-vertical camera axis shifts the reading
    # proportionally to the optical distance. Both fitted by calibrate-camera.
    raw = USCALE * np.array(m["cam_xyz_mm"][:2], float) + TILT * H
    u = np.array([raw[0], MIRROR * raw[1]])
    mw = (np.array([x, y]) + R(rz) @ CAM_ARM + R(rz + BPSI) @ u)
    yaw = wrap180(rz + BPSI + MIRROR * m["cam_yaw_deg"])
    # apply the learned per-marker grasp correction (marker frame -> world)
    off = marker_offset(int(m["id"]))
    grab_point = mw + R(yaw) @ off
    # marker plane world Z: camera optical distance along -Z, with the
    # calibrated camera z-offset and H-scale (both in calibration.json)
    mz = z - CAM_Z_OFF - HSCALE * H
    out = {"detected": True, "id": m["id"], "center_px": m["center_px"],
           "side_px": m["side_px"], "H_mm": m["cam_xyz_mm"][2],
           "marker_size_mm": m['marker_size_mm'],
           "marker_world": [round(float(mw[0]), 2), round(float(mw[1]), 2),
                            round(float(mz), 2)],
           "marker_yaw_deg": round(float(yaw), 2),
           "grasp_offset_applied": [round(float(off[0]), 2),
                                    round(float(off[1]), 2)],
           "grab_point": [round(float(grab_point[0]), 2),
                          round(float(grab_point[1]), 2)]}
    # grab orientation from the DISK'S OWN AXES when the id is calibrated
    # (marker print orientation cancels via rel_yaw); marker yaw is only
    # the fallback proxy for uncalibrated ids
    entry = CAL.get("marker_offsets", {}).get(str(int(m["id"])), {})
    rel = entry.get("rel_yaw_deg")
    grab_base = wrap180(yaw + float(rel)) if rel is not None else yaw
    gmin = _LIM.get("claw_gap_min_mm", 60.0)
    gmax = _LIM.get("claw_gap_max_mm", 88.0)

    def _clampable(span):
        # can the open plates straddle this span AND still close on it?
        # (85.1 clamped live at max gap 88 with ~1.4 mm/side clearance)
        if span is None:
            return None                    # uncalibrated id: unknown
        return bool(gmin + 0.5 <= float(span) <= gmax - 1.0)

    # ALL FOUR approaches. Plates parallel to the LONG edges clamp the
    # WIDTH (wrist at disk_axis + WRIST_REL, and its 180 twin); wrist
    # +90 deg turns the plates parallel to the short edges and clamps
    # the LENGTH. Span data comes from the id's disk calibration.
    cands = []
    for axis, axis_off, span in (
            ("width", 0.0, entry.get("width_mm")),
            ("length", 90.0, entry.get("length_mm"))):
        ok_span = _clampable(span)
        for side in (0.0, 180.0):
            rz_g = wrap180(grab_base + axis_off + WRIST_REL + side)
            tcp = grab_point - R(rz_g) @ CLAW_ARM
            # feasible = ARM reachability only; clampable is informational
            # (operator-owned judgment — the claw guard was removed from
            # the UI by operator decision 2026-07-28)
            cands.append({"rz": round(float(rz_g), 2),
                          "tcp": [round(float(tcp[0]), 2),
                                  round(float(tcp[1]), 2)],
                          "reach": round(float(np.hypot(*tcp)), 1),
                          "axis": axis,
                          "span_mm": (round(float(span), 1)
                                      if span is not None else None),
                          "clampable": ok_span,
                          "feasible": _tcp_reachable(tcp)})
    out["grab_candidates"] = cands
    out["grip_z"] = round(float(mz) + grip_z_offset(int(m["id"])), 2)
    return out


def fit_mount(rows, bpsi_step=0.25):
    """Least-squares camera-mount fit INCLUDING axis tilt, from capture
    rows {x, y, rz, ux, uy, H} over a FIXED marker.

    Model (tool frame; MIRROR is selected by the fit, not assumed —
    portable to arms with the camera mounted either way):
      m = T + R(rz)@c + R(rz+bpsi)@F@(s*u + t*H),  F = diag(1, mirror)
    Linear in (c, t, s, m) for a given (bpsi, mirror) -> scan both, LSQ.
    If rows carry 'z' (TCP height) with >= 15 mm of H spread, the Z scale
    h_scale (true-distance per PnP-H, i.e. the marker-size correction) is
    regressed too. Returns {lever_arm_mm, yaw_offset_deg, tilt_per_mm,
    u_scale, mirror_f, h_scale, marker_world, rms_mm, n}. Needs
    diversity: >= 8 rows, >= 60 deg wrist spread, >= 2 heights, and
    TRANSLATION hops >= 30 mm (they make the parallax scale observable)."""
    best = None
    for mirror in (-1.0, 1.0):
        F = np.diag([1.0, mirror])
        for bpsi in np.arange(0.0, 360.0, bpsi_step):
            Ab, bb = [], []
            for r in rows:
                Rt = R(r["rz"])
                Rc = R(r["rz"] + bpsi) @ F
                u = np.array([r["ux"], r["uy"]])
                # m - R(rz)c - Rc t H - s Rc u = T
                M = np.hstack([-Rt, -Rc * r["H"],
                               (-(Rc @ u)).reshape(2, 1), np.eye(2)])
                Ab.append(M)
                bb.append(np.array([r["x"], r["y"]]))
            Ab = np.vstack(Ab)
            bb = np.hstack(bb)
            p, *_ = np.linalg.lstsq(Ab, bb, rcond=None)
            res = Ab @ p - bb
            rms = float(np.sqrt(np.mean(res ** 2)))
            if best is None or rms < best["rms_mm"]:
                best = {"lever_arm_mm": [round(float(v), 2)
                                         for v in p[0:2]],
                        "tilt_per_mm": [round(float(v), 5)
                                        for v in p[2:4]],
                        "u_scale": round(float(p[4]), 4),
                        "mirror_f": mirror,
                        "marker_world": [round(float(v), 2)
                                         for v in p[5:7]],
                        "yaw_offset_deg": round(float(bpsi), 2),
                        "rms_mm": round(rms, 3), "n": len(rows)}
    # Z scale: TCP_z = const + h_scale * H over a fixed marker
    zs = [r for r in rows if "z" in r]
    if len(zs) >= 3:
        Hs = np.array([r["H"] for r in zs])
        Zs = np.array([r["z"] for r in zs])
        if float(Hs.max() - Hs.min()) >= 15.0:
            dh = Hs - Hs.mean()
            hs = float((Zs - Zs.mean()) @ dh / (dh @ dh))
            best["h_scale"] = round(hs, 4)
    return best


def save_mount(fitres: dict) -> dict:
    """Write a fit_mount result into calibration.json -> eye_cam_fit
    (keeping the marker size) and refresh the loaded constants."""
    global CAM_ARM, BPSI, TILT, USCALE, MIRROR, HSCALE
    path = os.path.join(HERE, "calibration.json")
    c = json.load(open(path, encoding="utf-8-sig"))
    e = c["eye_cam_fit"]
    e["lever_arm_mm"] = fitres["lever_arm_mm"]
    e["yaw_offset_deg"] = fitres["yaw_offset_deg"]
    e["tilt_per_mm"] = fitres["tilt_per_mm"]
    e["u_scale"] = fitres.get("u_scale", 1.0)
    e["rms_mm"] = fitres["rms_mm"]
    e["mirror_f"] = fitres.get("mirror_f", MIRROR)
    if "h_scale" in fitres:
        e["h_scale"] = fitres["h_scale"]
    import time as _t
    e["comment"] = (f"auto-calibrated {_t.strftime('%Y-%m-%d %H:%M')} from "
                    f"{fitres['n']} poses (incl. tilt term); "
                    "marker_world = TCP + R(Rz)@lever_arm + "
                    "R(Rz+yaw_offset)@diag(1,f)@(u + tilt*H)")
    # model-version stamp: the claw arm / wrist_rel are derived THROUGH
    # this model — a refit invalidates them (a stale arm missed 7.7 mm
    # live 2026-07-28). Consumers compare eye_cam_fit.fitted against
    # claw_arm_model_version and refuse absolute grabs on mismatch.
    e["fitted"] = _t.strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=1)
    CAL["eye_cam_fit"] = e
    CAM_ARM = np.array(e["lever_arm_mm"], float)
    BPSI = float(e["yaw_offset_deg"])
    TILT = np.array(e["tilt_per_mm"], float)
    USCALE = float(e.get("u_scale", 1.0))
    MIRROR = float(e.get("mirror_f", -1.0))
    HSCALE = float(e.get("h_scale", 1.0))
    return e


def save_claw_arm(arm_xy, note: str = "") -> dict:
    """Persist a measured claw lever arm (tool frame) — the portable
    calibration for a new arm: jog the claw midpoint exactly over a solved
    marker, then arm = R(-Rz) @ (marker_world - TCP)."""
    global CLAW_ARM
    path = os.path.join(HERE, "calibration.json")
    c = json.load(open(path, encoding="utf-8-sig"))
    c["claw_arm_tool_mm"] = [round(float(arm_xy[0]), 2),
                             round(float(arm_xy[1]), 2)]
    import time as _t
    c["claw_arm_comment"] = (note or "measured via UI jog-on-marker "
                             + _t.strftime("%Y-%m-%d %H:%M"))
    # stamp which camera model this arm was derived under (see save_mount)
    c["claw_arm_model_version"] = (c.get("eye_cam_fit") or {}).get(
        "fitted", "unstamped")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=1)
    CLAW_ARM = np.array(c["claw_arm_tool_mm"], float)
    CAL["claw_arm_tool_mm"] = c["claw_arm_tool_mm"]
    CAL["claw_arm_model_version"] = c["claw_arm_model_version"]
    return c["claw_arm_tool_mm"]


def solve_claw_arm_two(m1, th1, m2, th2):
    """TRUE claw arm from TWO jog-on-marker measurements at different
    wrist angles, separating the camera-solve bias.

    Each single measurement m_i = R(-th_i)@(marker_est - TCP_i) equals
    arm_true + R(-th_i)@c, where c is the (unknown, constant) world-frame
    bias of the marker estimate. One measurement conflates the two — a
    grab at the flipped wrist side then misses by 2*|arm error| (observed
    live). Two angles solve both:
        (R(-th1) - R(-th2)) @ c = m1 - m2   ->  c, then arm.
    Conditioning ~ (1 - cos(dth)): use dth >= 30 deg, ideally 180.
    Returns (arm, camera_bias_world)."""
    A = R(-th1) - R(-th2)
    d = np.asarray(m1, float) - np.asarray(m2, float)
    c = np.linalg.solve(A, d)
    arm = np.asarray(m1, float) - R(-th1) @ c
    return arm, c


def save_wrist_rel(rel_deg: float) -> dict:
    """Persist the wrist-vs-marker-yaw grab relation (claw clamp
    orientation) — set on a new arm by aligning the plates parallel to the
    object's long edges once and recording rz - marker_yaw."""
    global WRIST_REL
    path = os.path.join(HERE, "calibration.json")
    c = json.load(open(path, encoding="utf-8-sig"))
    c["wrist_rel_deg"] = round(float(rel_deg), 2)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=1)
    WRIST_REL = float(c["wrist_rel_deg"])
    CAL["wrist_rel_deg"] = c["wrist_rel_deg"]
    return {"wrist_rel_deg": c["wrist_rel_deg"]}


if __name__ == "__main__":
    if sys.argv[1] != "solve":
        print("usage: py aruco_world.py solve IMG X Y Z RZ [size_mm]",
              file=sys.stderr)
        sys.exit(2)
    size = float(sys.argv[7]) if len(sys.argv) > 7 else None
    r = solve(sys.argv[2], *[float(v) for v in sys.argv[3:7]], size_mm=size)
    print(json.dumps(r, indent=1))
