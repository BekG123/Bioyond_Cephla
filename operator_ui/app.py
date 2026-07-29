"""S4 Operator Console — human-in-the-loop control panel.

Live eye-in-hand (GigE) camera view + every robot capability as a button:
state control, jog, gripper, and the vision pipeline broken into operator-
triggered stages (Find disk -> Align -> Descend -> Grip -> Lift), each of
which reports back and waits for the human's next decision.

Run:  py operator_ui/app.py   ->  http://127.0.0.1:5002

Exclusivity (one owner at a time, both links):
 - robot TCP: disconnect the MCP server / Bioyond Works first
 - GigE camera: close the MVS client's live view first
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import deque

from flask import Flask, jsonify, request, Response, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import aruco  # noqa: E402
import teach  # noqa: E402
from camera_service import CameraService  # noqa: E402
from robot_service import RobotService  # noqa: E402
from sequences import (  # noqa: E402
    Runner,
    seq_align,
    seq_calibrate_aruco,
    seq_calibrate_camera,
    seq_descend,
    seq_find_aruco,
    seq_find_disk,
    seq_generate_anchor,
    seq_grip,
    seq_workflow,
)

app = Flask(__name__, static_folder="static")
svc = RobotService()
cam = CameraService()
runner = Runner()

CAL_PATH = os.path.join(os.path.dirname(HERE), "grab_skill",
                        "calibration.json")


class TorqueRecorder:
    """Continuous J1-J4/E1 torque sampler for the operator's threshold
    tuning: the human jogs Z manually while this streams readings; the UI
    plots them and the human clicks the deviation value that should trip
    the descent guard. Sampling goes through the same service lock as jog
    commands, so they interleave safely (~1-2 samples/s)."""

    def __init__(self, service) -> None:
        self.svc = service
        self.samples: deque = deque(maxlen=3000)
        self.baseline = None
        self.error = ""
        self._run = False
        self._thread: threading.Thread | None = None

    def start(self) -> dict:
        if self._run:
            return {"ok": True, "note": "already recording"}
        self.samples.clear()
        self.baseline = None
        self.error = ""
        self._run = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return {"ok": True, "note": "recording — jog Z manually; readings "
                                    "stream to the chart"}

    def stop(self) -> dict:
        self._run = False
        return {"ok": True, "n": len(self.samples)}

    def _loop(self) -> None:
        t0 = time.time()
        warmup = []
        while self._run:
            r = self.svc.torque_report()
            if not r.get("ok"):
                self.error = r.get("error", "torque read failed")
                time.sleep(1.0)
                continue
            self.error = ""
            try:
                z = self.svc.pose_mm()["Z"]
            except Exception:  # noqa: BLE001
                z = None
            j = [r["joints"][f"J{i}"] for i in (1, 2, 3, 4)]
            if self.baseline is None:
                warmup.append(j)
                if len(warmup) >= 3:
                    self.baseline = [sum(v[i] for v in warmup) / len(warmup)
                                     for i in range(4)]
            self.samples.append({"t": round(time.time() - t0, 2), "z": z,
                                 "j": j, "e1t": r.get("e1_torque")})

    def data(self) -> dict:
        return {"ok": True, "recording": self._run, "error": self.error,
                "baseline": self.baseline, "samples": list(self.samples)}


recorder = TorqueRecorder(svc)


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _refuse_if_sequencing() -> Response | None:
    if runner.active:
        return jsonify({"ok": False, "error":
                        f"sequence '{runner.name}' is running — Stop it "
                        "before manual commands"})
    return None


# ------------------------------------------------------------------ pages

@app.get("/")
def index():
    return send_from_directory(os.path.join(HERE, "static"), "index.html")


# ----------------------------------------------------------------- camera

@app.get("/frame")
def frame():
    jpeg, err = cam.frame_jpeg()
    if jpeg is None:
        return jsonify({"error": err or "no frame yet"}), 503
    resp = Response(jpeg, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Error"] = err
    return resp

@app.get("/crop")
def crop():
    cx = int(request.args.get("cx", 0))
    cy = int(request.args.get("cy", 0))
    size = max(60, min(800, int(request.args.get("size", 240))))
    jpeg = cam.crop_jpeg(cx, cy, size)
    if jpeg is None:
        return jsonify({"error": "no frame captured yet"}), 503
    resp = Response(jpeg, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.post("/camera/release")
def camera_release():
    cam.release()
    return jsonify({"ok": True, "note": "camera released for MVS/other apps"})

@app.post("/camera/resume")
def camera_resume():
    cam.resume()
    return jsonify({"ok": True})

@app.post("/camera/snapshot")
def camera_snapshot():
    try:
        path = cam.save(prefix="snap")
        return jsonify({"ok": True, "path": path})
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})


# ------------------------------------------------------------------ state

@app.get("/state")
def state():
    return jsonify({
        "robot": svc.status(),
        "envelope": svc.envelope_dict(),
        "camera": cam.info(),
        "sequence": {"state": runner.state, "name": runner.name,
                     "active": runner.active},
        "target": runner.target,
        "ts": time.time(),
    })

@app.get("/seq")
def seq():
    return jsonify(runner.snapshot())

@app.get("/teach_view")
def teach_view():
    p = runner.detection_path
    if not p or not os.path.exists(p):
        return jsonify({"error": "no detection image"}), 404
    with open(p, "rb") as f:
        resp = Response(f.read(), mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ------------------------------------------------------------- connection

@app.post("/connect")
def connect():
    return jsonify(svc.connect(_body().get("ip", "")))

@app.post("/disconnect")
def disconnect():
    return jsonify(svc.disconnect())


# ------------------------------------------------------------ state ctrl

@app.post("/mode")
def mode():
    return jsonify(svc.switch_mode(_body().get("mode", "auto")))

@app.post("/enable")
def enable():
    b = _body()
    return jsonify(svc.set_enable(True, bool(b.get("confirm"))))

@app.post("/disable")
def disable():
    return jsonify(svc.set_enable(False, True))

@app.post("/clear_errors")
def clear_errors():
    return jsonify(svc.clear_errors(bool(_body().get("confirm"))))

@app.post("/program")
def program():
    b = _body()
    return jsonify(svc.program(b.get("action", ""), bool(b.get("force"))))

@app.post("/envelope/enable")
def envelope_enable():
    return jsonify(svc.set_envelope_enabled(bool(_body().get("enabled"))))

@app.post("/envelope")
def envelope():
    b = _body()
    try:
        return jsonify(svc.set_envelope(
            float(b["x_min"]), float(b["x_max"]),
            float(b["y_min"]), float(b["y_max"]),
            float(b["z_min"]), float(b["z_max"])))
    except (KeyError, ValueError) as ex:
        return jsonify({"ok": False, "error": f"bad envelope values: {ex}"})


# ----------------------------------------------------------------- motion

@app.post("/jog")
def jog():
    r = _refuse_if_sequencing()
    if r:
        return r
    b = _body()
    try:
        return jsonify(svc.jog(str(b["axis"]), float(b["delta"]),
                               float(b.get("speed", 0))))
    except (KeyError, ValueError) as ex:
        return jsonify({"ok": False, "error": f"bad jog request: {ex}"})

@app.post("/move")
def move():
    r = _refuse_if_sequencing()
    if r:
        return r
    b = _body()
    try:
        return jsonify(svc.move_cartesian(
            float(b["x"]), float(b["y"]), float(b["z"]), float(b["rz"]),
            float(b.get("speed", 0)), b.get("interpolation", "linear")))
    except (KeyError, ValueError) as ex:
        return jsonify({"ok": False, "error": f"bad move request: {ex}"})

@app.post("/lift")
def lift():
    r = _refuse_if_sequencing()
    if r:
        return r
    b = _body()
    try:
        pose = svc.pose_mm()
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})
    z = float(b.get("z", 150.0))
    if z <= pose["Z"]:
        return jsonify({"ok": False, "error":
                        f"lift target Z {z} is not above current Z "
                        f"{pose['Z']}"})
    res = svc.move_cartesian(pose["X"], pose["Y"], z, pose["Rz"],
                             10.0, "linear")
    if res.get("ok"):
        res["gripper_after"] = svc.gripper_status()
    return jsonify(res)


# ---------------------------------------------------------------- gripper

@app.post("/gripper")
def gripper():
    r = _refuse_if_sequencing()
    if r:
        return r
    b = _body()
    action = b.get("action", "")
    if action == "status":
        return jsonify(svc.gripper_status())
    if action == "torque":
        return jsonify(svc.torque_report())
    if action == "move":
        try:
            return jsonify(svc.move_gripper(float(b["e1"]),
                                            float(b.get("speed", 0))))
        except (KeyError, ValueError) as ex:
            return jsonify({"ok": False, "error": f"bad gripper move: {ex}"})
    return jsonify({"ok": False, "error": f"unknown gripper action "
                    f"'{action}'"})


# ----------------------------------------------------- z-cal + torque tab

@app.get("/zcal")
def zcal_get():
    try:
        c = json.load(open(CAL_PATH, encoding="utf-8-sig"))
        return jsonify({"ok": True,
                        "z_touch_offset_mm": c["z_touch_offset_mm"],
                        "safety_margin_mm": c["safety_margin_mm"],
                        "grip_extra_mm": c["z_touch_offset_mm"]
                        + c["safety_margin_mm"]})
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})


@app.post("/zcal")
def zcal_set():
    b = _body()
    try:
        off = float(b["z_touch_offset_mm"])
        mar = float(b.get("safety_margin_mm", 0.0))
    except (KeyError, ValueError) as ex:
        return jsonify({"ok": False, "error": f"bad values: {ex}"})
    try:
        c = json.load(open(CAL_PATH, encoding="utf-8-sig"))
        c.setdefault("history", []).append(
            {"date": time.strftime("%Y-%m-%d %H:%M"),
             "source": "operator UI edit",
             "offset": off, "margin": mar})
        c["z_touch_offset_mm"] = off
        c["safety_margin_mm"] = mar
        with open(CAL_PATH, "w", encoding="utf-8") as f:
            json.dump(c, f, indent=1)
        # keep the running solvers in sync (they cached the value at import)
        aruco.Z_TOUCH = off + mar
        aruco.W.Z_TOUCH = off + mar
        return jsonify({"ok": True, "z_touch_offset_mm": off,
                        "safety_margin_mm": mar, "grip_extra_mm": off + mar,
                        "note": "saved to grab_skill/calibration.json — "
                                "used by the NEXT Find; an already-published "
                                "target keeps its old grip Z"})
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})


@app.post("/marker_offset")
def marker_offset_save():
    """Learn the per-marker grasp correction from the CURRENT claw
    position: the operator aligns/jogs until the claw is visually perfect
    over the object, then presses Save. offset = claw_world − marker_world
    rotated into the MARKER frame, so it holds at any object rotation."""
    import math as _m
    t = runner.target or {}
    if "marker_world" not in t or "marker_yaw" not in t:
        return jsonify({"ok": False, "error": "no ArUco target with marker "
                        "pose — run Find ArUco first"})
    try:
        pose = svc.pose_mm()
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})
    a = _m.radians(pose["Rz"])
    arm = aruco.CLAW_ARM
    claw_x = pose["X"] + arm[0] * _m.cos(a) - arm[1] * _m.sin(a)
    claw_y = pose["Y"] + arm[0] * _m.sin(a) + arm[1] * _m.cos(a)
    mw = t["marker_world"]
    dxw, dyw = claw_x - float(mw[0]), claw_y - float(mw[1])
    if _m.hypot(dxw, dyw) > 40.0:
        return jsonify({"ok": False, "error":
                        f"claw is {_m.hypot(dxw, dyw):.0f} mm from the "
                        "marker — that is not a small correction; re-run "
                        "Find ArUco instead"})
    y = _m.radians(float(t["marker_yaw"]))
    dx = dxw * _m.cos(-y) - dyw * _m.sin(-y)
    dy = dxw * _m.sin(-y) + dyw * _m.cos(-y)
    mid = str(t.get("marker_id", "?"))
    try:
        c = json.load(open(CAL_PATH, encoding="utf-8-sig"))
        c.setdefault("marker_offsets", {})[mid] = {
            "dx_mm": round(dx, 2), "dy_mm": round(dy, 2),
            "date": time.strftime("%Y-%m-%d %H:%M"),
            "note": "learned from operator jog in the UI"}
        with open(CAL_PATH, "w", encoding="utf-8") as f:
            json.dump(c, f, indent=1)
        aruco.W.CAL.setdefault("marker_offsets", {})[mid] = \
            c["marker_offsets"][mid]
        return jsonify({"ok": True, "marker_id": mid,
                        "offset_marker_frame_mm": [round(dx, 2),
                                                   round(dy, 2)],
                        "note": "every future Find ArUco applies this "
                                "automatically (any object rotation)"})
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})


_claw_arm_pending: dict | None = None


@app.post("/claw_arm_save")
def claw_arm_save():
    """TWO-SIDED claw calibration (bias-immune). Press once with the claw
    midpoint jogged exactly onto the last Find's marker; ROTATE the wrist
    ~180 deg, jog the claw onto the marker again, press again — the two
    measurements separate the true arm from the camera-solve bias (one
    measurement alone bakes the bias in, and a grab at the flipped wrist
    side then misses by twice the error — observed live 2026-07-25)."""
    global _claw_arm_pending
    import math as _m
    t = runner.target or {}
    if "marker_world" not in t:
        return jsonify({"ok": False, "error": "no ArUco target with marker "
                        "pose — run Find ArUco first"})
    try:
        pose = svc.pose_mm()
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})
    mw = t["marker_world"]
    dxw, dyw = float(mw[0]) - pose["X"], float(mw[1]) - pose["Y"]
    a = _m.radians(-pose["Rz"])
    meas = [dxw * _m.cos(a) - dyw * _m.sin(a),
            dxw * _m.sin(a) + dyw * _m.cos(a)]
    if _claw_arm_pending is None or _claw_arm_pending.get(
            "marker") != list(mw):
        _claw_arm_pending = {"meas": meas, "rz": pose["Rz"],
                             "marker": list(mw)}
        return jsonify({"ok": True, "step": "1 of 2",
                        "measurement": [round(v, 2) for v in meas],
                        "rz": pose["Rz"],
                        "note": "measurement 1 stored. Now ROTATE the "
                                "wrist ~180 deg (any >=30), jog the claw "
                                "back onto the SAME marker, press again."})
    dth = abs((pose["Rz"] - _claw_arm_pending["rz"] + 180.0) % 360.0
              - 180.0)
    if dth < 30.0:
        _claw_arm_pending = {"meas": meas, "rz": pose["Rz"],
                             "marker": list(mw)}
        return jsonify({"ok": True, "step": "1 of 2 (replaced)",
                        "note": f"wrist only moved {dth:.0f} deg since "
                                "measurement 1 — need >= 30 (ideally "
                                "~180). Measurement replaced; rotate and "
                                "press again."})
    arm, cbias = aruco.W.solve_claw_arm_two(
        _claw_arm_pending["meas"], _claw_arm_pending["rz"],
        meas, pose["Rz"])
    old = list(aruco.CLAW_ARM)
    saved = aruco.save_claw_arm(list(arm),
                                f"two-sided jog calibration (dth "
                                f"{dth:.0f} deg)")
    _claw_arm_pending = None
    return jsonify({"ok": True, "step": "2 of 2 — SAVED",
                    "claw_arm_tool_mm": saved,
                    "previous": [round(v, 2) for v in old],
                    "camera_bias_measured_mm": [round(float(cbias[0]), 2),
                                                round(float(cbias[1]), 2)],
                    "note": "arm updated (bias-separated). CLEAR any "
                            "jog-saved marker offsets recorded under the "
                            "old arm and re-trim/1c if needed."})


@app.post("/anchor_confirm")
def anchor_confirm():
    """Operator verdict on a finished Generate-anchor run: save the
    pending anchor rows, or discard them. The sequence itself never
    writes — a bad convergence must not become ground truth."""
    b = _body()
    res = runner.result or {}
    if not res.get("anchor_pending"):
        return jsonify({"ok": False, "error": "no pending anchor — run "
                        "Generate anchor first"})
    if not b.get("save"):
        res["anchor_pending"] = False
        res["anchor_discarded"] = True
        return jsonify({"ok": True, "note": "anchor DISCARDED — nothing "
                        "was written; rerun Generate anchor when ready"})
    n = 0
    for row in res.get("pending_rows", []):
        n = aruco.save_anchor(row)
    res["anchor_pending"] = False
    res["anchor_saved_total"] = n
    return jsonify({"ok": True, "anchors_total": n,
                    "note": "anchor saved (2 rows) — Calibrate camera now "
                            "auto-re-derives the claw arm from stored "
                            "anchors after every refit"})


@app.post("/marker_offset_clear")
def marker_offset_clear():
    """Remove the learned offset for the last Find's marker id (or a
    given id) — use after recalibrating the claw arm, since jog-saved
    offsets recorded under a wrong arm are contaminated."""
    b = _body()
    t = runner.target or {}
    mid = str(b.get("marker_id", t.get("marker_id", "")))
    if not mid:
        return jsonify({"ok": False, "error": "no marker id — run Find "
                        "ArUco first or pass marker_id"})
    try:
        c = json.load(open(CAL_PATH, encoding="utf-8-sig"))
        entry = c.get("marker_offsets", {}).pop(mid, None)
        with open(CAL_PATH, "w", encoding="utf-8") as f:
            json.dump(c, f, indent=1)
        aruco.W.CAL.get("marker_offsets", {}).pop(mid, None)
        return jsonify({"ok": True, "marker_id": mid,
                        "removed": entry,
                        "note": "offset cleared — grabs now target the "
                                "marker itself; re-run 1c Calibrate disk "
                                "ID (or jog-trim) to relearn"})
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})


@app.post("/wrist_rel_save")
def wrist_rel_save():
    """New-arm clamp-orientation calibration: with the plates visually
    parallel to the object's long edges, save rz - marker_yaw."""
    import math as _m  # noqa: F401
    t = runner.target or {}
    if "marker_yaw" not in t:
        return jsonify({"ok": False, "error": "no ArUco target with marker "
                        "yaw — run Find ArUco first"})
    try:
        pose = svc.pose_mm()
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})
    rel = (pose["Rz"] - float(t["marker_yaw"]) + 180.0) % 360.0 - 180.0
    saved = aruco.save_wrist_rel(rel)
    return jsonify({"ok": True, **saved,
                    "note": "grab candidates now use this relation "
                            "(mod 180 — claw is symmetric)"})


@app.post("/torque_rec/start")
def torque_rec_start():
    r = _refuse_if_sequencing()
    if r:
        return r
    return jsonify(recorder.start())


@app.post("/torque_rec/stop")
def torque_rec_stop():
    return jsonify(recorder.stop())


@app.get("/torque_rec/data")
def torque_rec_data():
    return jsonify(recorder.data())


@app.get("/torque_threshold")
def torque_threshold_get():
    from sequences import band_floor
    return jsonify({"ok": True, "band_counts": band_floor()})


@app.post("/torque_threshold")
def torque_threshold_set():
    b = _body()
    try:
        v = float(b["band_counts"])
        if not (5.0 <= v <= 500.0):
            return jsonify({"ok": False, "error": "threshold must be "
                            "5..500 counts"})
    except (KeyError, ValueError) as ex:
        return jsonify({"ok": False, "error": f"bad threshold: {ex}"})
    from sequences import TORQUE_CFG_PATH
    with open(TORQUE_CFG_PATH, "w", encoding="utf-8") as f:
        json.dump({"band_counts": v,
                   "set_at": time.strftime("%Y-%m-%d %H:%M"),
                   "source": "operator torque-feedback tab"}, f, indent=1)
    return jsonify({"ok": True, "band_counts": v,
                    "note": "descent guard now trips at this deviation "
                            "(per joint, replacing the default ±25 floor)"})


# -------------------------------------------------------------- sequences

@app.post("/seq/find_disk")
def seq_find():
    return jsonify(runner.start("find_disk", seq_find_disk, svc, cam, teach))


@app.post("/seq/find_aruco")
def seq_find_aruco_route():
    return jsonify(runner.start("find_aruco", seq_find_aruco, svc, cam,
                                aruco))


@app.post("/seq/calibrate_aruco")
def seq_calibrate_aruco_route():
    return jsonify(runner.start("calibrate_aruco", seq_calibrate_aruco,
                                svc, cam, aruco))


@app.post("/seq/calibrate_camera")
def seq_calibrate_camera_route():
    return jsonify(runner.start("calibrate_camera", seq_calibrate_camera,
                                svc, cam, aruco))


@app.post("/seq/generate_anchor")
def seq_generate_anchor_route():
    return jsonify(runner.start("generate_anchor", seq_generate_anchor,
                                svc, cam, teach, aruco))


# ------------------------------------------------- saved points + workflow

POINTS_PATH = os.path.join(HERE, "points.json")


def _points_load() -> dict:
    try:
        d = json.load(open(POINTS_PATH, encoding="utf-8-sig"))
        d.setdefault("points", {})
        d.setdefault("roles", {})
        return d
    except Exception:  # noqa: BLE001
        return {"points": {}, "roles": {}}


def _points_store(d: dict) -> None:
    with open(POINTS_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


@app.get("/points")
def points_get():
    return jsonify({"ok": True, **_points_load()})


@app.post("/points/save")
def points_save():
    """Save a named point from EXPLICIT values — the browser sends the
    grasp-target fields (x, y, rz, z_grip), so whatever Find published
    (or the operator typed into the fields) is exactly what is stored.
    Falls back to the current pose when no values are sent."""
    b = _body()
    name = str(b.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "error": "give the point a name"})
    try:
        if all(b.get(k) is not None for k in ("x", "y", "rz", "z_grip")):
            pt = {"x": float(b["x"]), "y": float(b["y"]),
                  "rz": float(b["rz"]), "z_grip": float(b["z_grip"])}
            src = "target fields"
        else:
            pose = svc.pose_mm()
            pt = {"x": pose["X"], "y": pose["Y"], "rz": pose["Rz"],
                  "z_grip": pose["Z"]}
            src = "current pose"
    except (TypeError, ValueError) as ex:
        return jsonify({"ok": False, "error": f"bad values: {ex}"})
    except Exception as ex:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(ex)})
    pt = {k: round(float(v), 3) for k, v in pt.items()}
    pt["saved_at"] = time.strftime("%H:%M:%S")
    d = _points_load()
    d["points"][name] = pt
    _points_store(d)
    return jsonify({"ok": True, "point": pt, "name": name,
                    "z_source": src, "count": len(d["points"])})


@app.post("/points/order")
def points_order():
    """Persist the operator's travel-leg motion order (z / rz / xy / x /
    y tokens). Validated by the same parser the workflow uses."""
    from sequences import _parse_order
    b = _body()
    s = str(b.get("order", "")).strip()
    toks, err = _parse_order(s or "z,rz,xy")
    if toks is None:
        return jsonify({"ok": False, "error": err})
    d = _points_load()
    d["motion_order"] = s or "z,rz,xy"
    _points_store(d)
    return jsonify({"ok": True, "motion_order": d["motion_order"],
                    "resolved": toks})


@app.post("/points/delete")
def points_delete():
    b = _body()
    name = str(b.get("name", "")).strip()
    d = _points_load()
    if name not in d["points"]:
        return jsonify({"ok": False, "error": f"no point named '{name}'"})
    del d["points"][name]
    d["roles"] = {r: n for r, n in d["roles"].items() if n != name}
    _points_store(d)
    return jsonify({"ok": True, "count": len(d["points"])})


@app.post("/points/role")
def points_role():
    b = _body()
    role = str(b.get("role", "")).strip()
    name = str(b.get("name", "")).strip()
    if role not in ("start", "end", "home"):
        return jsonify({"ok": False, "error": "role must be "
                                              "start/end/home"})
    d = _points_load()
    if name and name not in d["points"]:
        return jsonify({"ok": False, "error": f"no point named '{name}'"})
    if name:
        d["roles"][role] = name
    else:
        d["roles"].pop(role, None)
    _points_store(d)
    return jsonify({"ok": True, "roles": d["roles"]})


@app.post("/seq/workflow")
def seq_workflow_route():
    b = _body()
    d = _points_load()
    pts = {}
    for role in ("start", "end", "home"):
        n = d["roles"].get(role)
        pts[role] = d["points"].get(n) if n else None
    params = {"travel_z": b.get("travel_z", 300.0),
              "open_e1": b.get("open_e1", 28.0),
              "motion_order": b.get("motion_order",
                                    d.get("motion_order", "z,rz,xy"))}
    return jsonify(runner.start("workflow", seq_workflow, svc, pts,
                                params))

@app.post("/seq/align")
def seq_align_route():
    b = _body()
    tgt = _target_from(b)
    if tgt is None:
        return jsonify({"ok": False, "error": "no grasp target — run Find "
                        "disk first (or fill the target fields)"})
    return jsonify(runner.start("align", seq_align, svc, tgt,
                                float(b.get("hover_z", 0) or 0)))

@app.post("/seq/descend")
def seq_descend_route():
    tgt = _target_from(_body())
    if tgt is None:
        return jsonify({"ok": False, "error": "no grasp target — run Find "
                        "disk first (or fill the target fields)"})
    return jsonify(runner.start("descend", seq_descend, svc, tgt))

@app.post("/seq/grip")
def seq_grip_route():
    return jsonify(runner.start("grip", seq_grip, svc, _body()))

@app.post("/seq/stop")
def seq_stop():
    return jsonify(runner.request_stop())

@app.post("/target")
def set_target():
    b = _body()
    try:
        runner.target = {
            "x": float(b["x"]), "y": float(b["y"]), "z": float(b["z"]),
            "rz": float(b["rz"]),
            "z_calibrated": float(b.get("z_calibrated", b["z"])),
            "config": b.get("config", "manual"),
            "found_at": time.strftime("%H:%M:%S"),
        }
        return jsonify({"ok": True, "target": runner.target})
    except (KeyError, ValueError) as ex:
        return jsonify({"ok": False, "error": f"bad target: {ex}"})


def _target_from(b: dict) -> dict | None:
    """Target sent by the UI (possibly operator-edited), else the stored one."""
    if all(k in b for k in ("x", "y", "z", "rz")):
        try:
            tgt = {"x": float(b["x"]), "y": float(b["y"]), "z": float(b["z"]),
                   "rz": float(b["rz"]),
                   "z_calibrated": float(b.get("z_calibrated", b["z"]))}
            runner.target = {**(runner.target or {}), **tgt}
            return tgt
        except ValueError:
            return None
    return runner.target


if __name__ == "__main__":
    print("S4 Operator Console -> http://127.0.0.1:5002")
    print("Reminders: only ONE robot TCP client (stop MCP/Bioyond Works), "
          "only ONE GigE owner (close MVS live view).")
    app.run(host="127.0.0.1", port=5002, threaded=True)
