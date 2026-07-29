"""Offline test of the operator console against the fake Bioyond controller.

No robot, no camera: robot_service + sequences run against
bioyond-s4-mcp/tests/fake_controller.py; find_disk uses a fake camera that
replays an archived eye-cam frame in which the disk is detectable.

Run:  py operator_ui/tests/test_offline.py
"""

from __future__ import annotations

import os
import sys

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
UI = os.path.dirname(HERE)
ROOT = os.path.dirname(UI)
sys.path.insert(0, UI)
sys.path.insert(0, os.path.join(ROOT, "bioyond-s4-mcp", "tests"))

# isolated envelope store — must NOT touch the console's real envelope.json
os.environ["BIOYOND_ENV_STORE"] = os.path.join(HERE, "_fake_envstore.json")
if os.path.exists(os.environ["BIOYOND_ENV_STORE"]):
    os.remove(os.environ["BIOYOND_ENV_STORE"])

import aruco  # noqa: E402
import teach  # noqa: E402
from fake_controller import FakeController  # noqa: E402
from robot_service import RobotService  # noqa: E402
from sequences import (  # noqa: E402
    Runner,
    seq_align,
    seq_calibrate_aruco,
    seq_descend,
    seq_find_aruco,
    seq_find_disk,
    seq_grip,
)

FRAME_WITH_DISK = os.path.join(ROOT, "bioyond-s4-mcp", "captures",
                               "cap0041_gige_grid.jpg")

PASS = FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    PASS += cond
    FAIL += not cond


class FakeCam:
    """Replays an archived frame; matches the CameraService API sequences use."""

    def __init__(self, path: str):
        self.frame = cv2.imread(path)
        self.n = 0

    def snap(self):
        return self.frame

    def save(self, frame, prefix="teach"):
        self.n += 1
        path = os.path.join(HERE, f"_fake_{prefix}_{self.n}.png")
        cv2.imwrite(path, frame)
        return path


def wait(run: Runner, timeout: float = 120.0) -> None:
    import time
    t0 = time.time()
    while run.active and time.time() - t0 < timeout:
        time.sleep(0.05)


def main() -> int:
    fake = FakeController()
    svc = RobotService()

    r = svc.connect("127.0.0.1", fake.port)
    check("connect", r.get("ok") is True, str(r))

    st = svc.status()
    check("status connected", st.get("connected") is True)
    p = st.get("pose_mm", {})
    check("pose meters->mm", p.get("X") == 300.0 and p.get("Z") == 370.0, str(p))
    check("pose radians->deg", p.get("Rz") == 90.0, str(p))

    svc.set_envelope(100, 500, -350, 100, 30, 420)

    r = svc.move_cartesian(305, -55, 365, 90)
    check("move ok", r.get("ok") is True, str(r.get("error")))
    check("move pose_after", r["pose_after"]["X"] == 305.0
          and r["pose_after"]["Z"] == 365.0, str(r.get("pose_after")))

    r = svc.move_cartesian(305, -55, 900, 90)
    check("envelope refusal", r.get("ok") is False and "outside" in r["error"])

    r = svc.move_cartesian(400, -300, 365, 0)
    check("reach refusal", r.get("ok") is False and "reach" in r["error"],
          str(r.get("error")))

    # stranded outside the reach limit: inward escape moves must be allowed,
    # outward ones still refused with the current radius in the message
    import math as _m
    fake.pose["X"], fake.pose["Y"] = 0.400, -0.300   # radius 500 (meters)
    r = svc.move_cartesian(395, -300, 365, 0)        # 495.6 < 500: inward
    check("inward escape allowed beyond limit", r.get("ok") is True,
          str(r.get("error")))
    r = svc.move_cartesian(400, -305, 365, 0)        # outward from 495.6
    check("outward refused with current radius", r.get("ok") is False
          and "current radius" in r["error"], str(r.get("error"))[:120])
    fake.pose["X"], fake.pose["Y"] = 0.305, -0.055   # back inside

    svc.set_envelope_enabled(False)
    r = svc.move_cartesian(305, -55, 900, 90)   # outside the box, in reach
    check("disabled box allows any target", r.get("ok") is True,
          str(r.get("error")))
    r = svc.move_cartesian(400, -300, 365, 0)   # reach 500
    check("disable turns the reach guard off too", r.get("ok") is True,
          str(r.get("error")))
    svc.set_envelope(100, 500, -350, 100, 30, 420)
    check("apply re-arms the box check", svc.envelope_enabled is True)

    # envelope state must survive a console restart (new service instance)
    svc2 = RobotService()
    check("envelope box persists across restart",
          svc2.envelope == svc.envelope and svc2.envelope_enabled is True)
    svc.set_envelope_enabled(False)
    svc3 = RobotService()
    check("disabled state persists across restart",
          svc3.envelope_enabled is False)
    svc.set_envelope_enabled(True)

    svc.move_cartesian(305, -55, 365, 90)       # restore pose for the rest

    r = svc.rotate_to_rz(180)
    check("rotate chunks", r.get("ok") is True
          and r["commanded"]["chunks"] == 3, str(r.get("commanded")))
    check("rotate pose", abs(r["pose_after"]["Rz"] - 180.0) < 0.01,
          str(r.get("pose_after")))

    r = svc.jog("Z", 5)
    check("jog Z+5", r.get("ok") is True
          and r["pose_after"]["Z"] == 370.0, str(r.get("pose_after")))

    r = svc.move_gripper(28)
    check("gripper open", r.get("ok") is True
          and r["gripper"]["e1_position"] == 28.0, str(r.get("gripper")))
    check("free torque positive", r["gripper"]["e1_torque"] > 100)

    r = svc.gripper_status()
    check("gripper status", r.get("ok") is True and r["e1_position"] == 28.0)

    r = svc.torque_report()
    check("torque report (no trq bin)", r.get("ok") is True
          and r["telemetry_live"] is False, str(r))

    # ---- grip sequence: fake object stalls E1 at 23.34, torque -> -187
    run = Runner()
    run.start("grip", seq_grip, svc, {"start": 28, "floor": 20})
    wait(run)
    check("grip seq state", run.state == "done", run.state)
    check("grip seq gripped", bool(run.result and run.result.get("gripped")),
          str(run.result))

    # ---- program start safety: refuse while holding; stop-then-start when
    # paused (a resume would continue the interrupted motion)
    r = svc.program("start")
    check("start refused while holding", r.get("ok") is False
          and "HELD" in r.get("error", ""), str(r.get("error"))[:80])

    svc.move_gripper(28)  # release for the next tests
    fake.prog_state = 2   # simulate a paused program
    r = svc.program("start")
    check("safe start stops paused first", r.get("ok") is True
          and any("PAUSED" in n for n in r.get("notes", []))
          and fake.prog_state == 1, str(r.get("notes")))
    check("start reports E1 state",
          "e1_position" in r.get("gripper_after_start", {}),
          str(r.get("gripper_after_start")))

    # ---- align sequence
    run = Runner()
    run.target = {"x": 310, "y": -60, "z": 41, "rz": 0, "z_calibrated": 50}
    run.start("align", seq_align, svc, run.target, 365)
    wait(run)
    check("align seq state", run.state == "done", run.state)
    pose = svc.pose_mm()
    check("align pose", pose["X"] == 310.0 and pose["Y"] == -60.0
          and pose["Z"] == 365.0 and abs(pose["Rz"]) < 0.01, str(pose))

    # ---- descend must REFUSE: fake controller has no J1-J4 torque slots
    run2 = Runner()
    run2.target = run.target
    run2.start("descend", seq_descend, svc, run2.target)
    wait(run2)
    check("descend refuses dead telemetry", run2.state == "error"
          and any("ZERO" in e["msg"] for e in run2.log), run2.state)

    # ---- descend with telemetry: patch fake to publish J1-J4 slots
    fake.var_i[13], fake.var_i[14] = 420000, 5000
    fake.var_i[15], fake.var_i[16] = -3000, 8000
    orig = fake._write_grip_report

    def write_with_joints():
        orig()
        fake.var_i[13] = 420000  # steady J1 -> no breach
        fake.var_i[14], fake.var_i[15], fake.var_i[16] = 5000, -3000, 8000

    fake._write_grip_report = write_with_joints
    run3 = Runner()
    run3.target = run.target
    run3.start("descend", seq_descend, svc, run3.target)
    wait(run3)
    check("descend completes", run3.state == "done", run3.state)
    check("descend reached grip Z", bool(run3.result
          and run3.result.get("breach") is False
          and svc.pose_mm()["Z"] == 50.0), str(svc.pose_mm()))

    # ---- descend detects a torque breach (J3 jumps mid-descent)
    svc.move_cartesian(310, -60, 80, 0)
    calls = {"n": 0}

    def write_breach():
        orig()
        calls["n"] += 1
        fake.var_i[13] = 420000
        fake.var_i[14], fake.var_i[16] = 5000, 8000
        # breach J3 after baseline (5 reads) + 3 descent steps
        fake.var_i[15] = -3000 if calls["n"] < 9 else -400000

    fake._write_grip_report = write_breach
    run4 = Runner()
    run4.target = run.target
    run4.start("descend", seq_descend, svc, run4.target)
    wait(run4)
    check("breach stops descent", run4.state == "done"
          and bool(run4.result and run4.result.get("breach")),
          f"state={run4.state} result={run4.result}")
    check("breach retreats 1mm", bool(run4.result) and
          abs(svc.pose_mm()["Z"] - run4.result["retreated_to"]) < 0.01,
          str(svc.pose_mm()))
    fake._write_grip_report = orig

    # ---- workflow: full pick -> place -> home cycle on the fake
    # controller (steady joint torque, E1 stalls at 23.34 = the object)
    from sequences import seq_workflow
    fake._write_grip_report = write_with_joints
    svc.move_gripper(28)                       # not "holding" beforehand
    pts = {"start": {"x": 310.0, "y": -60.0, "rz": 0.0, "z_grip": 50.0},
           "end": {"x": 330.0, "y": -80.0, "rz": 0.0, "z_grip": 50.0},
           "home": {"x": 305.0, "y": -55.0, "rz": 0.0, "z_grip": 365.0}}
    run8 = Runner()
    run8.start("workflow", seq_workflow, svc, pts,
               {"travel_z": 365.0, "open_e1": 28.0,
                "motion_order": "z,x,y,rz"})   # fully split custom order
    wait(run8, timeout=300)
    check("workflow completes", run8.state == "done"
          and bool(run8.result and run8.result.get("picked")
                   and run8.result.get("placed")),
          f"state={run8.state} result={str(run8.result)[:120]}")
    pose = svc.pose_mm()
    check("workflow parks at home",
          pose["X"] == 305.0 and pose["Y"] == -55.0
          and abs(pose["Z"] - 365.0) < 0.01, str(pose))
    # the fake's phantom object stalls every close at 23.34, so the final
    # claw position cannot be asserted offline — the choreography ORDER
    # can: open exactly at +20, release at END, rise, close, in sequence
    msgs = [e["msg"] for e in run8.log]

    def idx(sub):
        return next((i for i, m in enumerate(msgs) if sub in m), -1)

    i_open = idx("open at +20")
    i_rel = idx("end: release")
    i_rise = idx("rise 20 after release")
    i_close = idx("end: close claw")
    check("claw choreography in order (open@+20 -> release -> rise "
          "-> close)", -1 < i_open < i_rel < i_rise < i_close,
          f"open={i_open} release={i_rel} rise={i_rise} close={i_close}")
    i_x = idx("end: X")
    i_y = idx("end: Y")
    check("custom motion order executes X before Y on the leg",
          -1 < i_x < i_y, f"X={i_x} Y={i_y}")
    fake._write_grip_report = orig

    # ---- travel-leg motion order parser (operator-tunable trajectories)
    from sequences import _parse_order
    check("order default parses", _parse_order("z,rz,xy")[0]
          == ["z", "rz", "xy"], str(_parse_order("z,rz,xy")))
    check("order auto-completes omitted axes",
          _parse_order("rz")[0] == ["rz", "z", "xy"]
          and _parse_order("z,x")[0] == ["z", "x", "rz", "y"],
          str((_parse_order("rz")[0], _parse_order("z,x")[0])))
    check("order rejects unknown tokens", _parse_order("z,q")[0] is None,
          str(_parse_order("z,q")))

    # ---- step planner unit checks (pure geometry, no robot)
    import sequences as seqmod

    class _Env:
        envelope_enabled = False
        envelope = {"X": (0, 1000), "Y": (-1000, 1000), "Z": (0, 1000)}

    env = _Env()
    p = seqmod._plan_xy_step(env, 200, 0, 300, 0, 200)     # far: 100 mm
    check("planner far step bounded", p is not None
          and abs(p["step"] - seqmod.STEP_MAX_MM) < 1e-6, str(p))
    p = seqmod._plan_xy_step(env, 200, 0, 215, 0, 200)     # close: direct
    check("planner direct when close", p is not None
          and abs(p["step"] - 15.0) < 1e-6, str(p))
    # boundary = the extension circle around the ARM BASE (fitted model),
    # falling back to the legacy origin circle when kinematics are absent
    rp = seqmod._RP
    if seqmod._kinematics_on():
        bx = rp["base_x_mm"]
        blim = (rp["link1_mm"] + rp["link2_mm"]
                - rp["extension_margin_mm"] - seqmod.REACH_MARGIN_MM)
    else:
        bx, blim = 0.0, seqmod.REACH_HARD_MM - seqmod.REACH_MARGIN_MM
    edge = bx + blim                       # boundary crossing on the +X ray
    p = seqmod._plan_xy_step(env, edge - 10, 0, edge + 60, 0, 200)
    check("planner slides to reach boundary", p is not None
          and p["x"] <= edge + 0.01 and p["note"] != "", str(p))
    p = seqmod._plan_xy_step(env, edge, 0, edge + 60, 0, 200)
    check("planner reports no progress at boundary", p is None, str(p))

    # ---- exact arm kinematics regression: the planar model fitted
    # 2026-07-28 with 0.00 mm residual — IK must reproduce every live
    # (J2, J3) <-> (X, Y) pair logged that day, including the J2 pose
    # frozen BY the soft limit itself (-95.10)
    LIVE_PAIRS = [
        (-78.2467, -141.7703, 319.911, -324.410),
        (-62.2523, -176.4017, 323.157, -347.810),
        (-89.1159, -125.9920, 292.700, -315.000),
        (-95.1021, -118.6226, 274.557, -310.248),
        (-66.6172, -132.9601, 393.813, -250.591),
        (-72.4937, -121.7659, 380.000, -240.000),
        (-68.6593, -122.5016, 395.000, -225.000),
        (-56.3550, -111.9538, 432.660, -125.970),
    ]
    if seqmod._kinematics_on():
        worst = 0.0
        for j2, j3, x, y in LIVE_PAIRS:
            ik = seqmod._ik_j2j3(x, y)
            worst = max(worst, abs(ik[0] - j2), abs(ik[1] - j3))
        check("IK reproduces all live joint/pose pairs", worst < 0.15,
              f"worst joint error {worst:.3f} deg")
        stop = seqmod._ik_j2j3(274.557, -310.248)
        check("IK reproduces the J2 soft-limit stop",
              abs(stop[0] - (-95.10)) < 0.05, str(stop))
        # the 3570 fault target sat 3.6 mm past true full extension
        check("extension guard rejects the 3570 fault target",
              seqmod._reach_block(310.72, -358.8) is not None
              and "extension" in seqmod._reach_block(310.72, -358.8),
              str(seqmod._reach_block(310.72, -358.8)))
        # the probed near-side TCP needs J2 -126 -> J2-limit rejection
        check("J2 guard rejects the probed near-side TCP",
              seqmod._reach_block(207.6, -155.92) is not None
              and "J2" in seqmod._reach_block(207.6, -155.92),
              str(seqmod._reach_block(207.6, -155.92)))
        # the live claw-overhang grab TCP (disk itself at reach 536)
        check("guard accepts the live overhang grab TCP",
              seqmod._reach_block(432.66, -125.97) is None,
              str(seqmod._reach_block(432.66, -125.97)))
        # origin-far but base-near: valid zone the old origin circle
        # would have refused (base sits at +126 X on this arm)
        check("base-centred guard opens the far east zone",
              seqmod._reach_block(500.0, -20.0) is None,
              str(seqmod._reach_block(500.0, -20.0)))

    # ---- arrival verification: success requires pose_after == commanded
    # (stale acks after reconnects reported value 1 while the controller
    # had faulted mid-path 16 mm / 47 deg away, live 2026-07-28)
    good_pose = {"X": 300.0, "Y": -50.0, "Z": 100.0, "Rz": 90.0}
    check("arrival verify passes on match",
          svc._arrival_error(good_pose, 300.0, -50.0, 100.0, 90.0) is None)
    bad = svc._arrival_error(good_pose, 316.0, -50.0, 100.0, 90.0)
    check("arrival verify flags a position mismatch",
          bad is not None and "DID NOT ARRIVE" in bad, str(bad))
    bad = svc._arrival_error(good_pose, 300.0, -50.0, 100.0, 137.3)
    check("arrival verify flags an Rz mismatch",
          bad is not None and "Rz" in bad, str(bad))
    check("arrival verify wraps Rz (winding-equivalent angles pass)",
          svc._arrival_error({"X": 300.0, "Y": -50.0, "Z": 100.0,
                              "Rz": -179.9}, 300.0, -50.0, 100.0,
                             180.1) is None)

    # ---- standalone grabber: the model-version stamp gate must accept
    # the current (matching) calibration stamps
    sys.path.insert(0, os.path.join(ROOT, "grab_skill"))
    import grab_aruco
    ok_stamp, stamp_note = grab_aruco._claw_arm_stamp_ok()
    check("grab_aruco stamp gate accepts matching stamps",
          ok_stamp is True and stamp_note == "",
          f"ok={ok_stamp} note={stamp_note!r}")

    # ---- per-object grip depth: ids whose calibration stores a
    # grip_z_offset (recessed markers, e.g. the ring tray) override the
    # global z-touch; unknown ids fall back to it
    import aruco as aruco_wrap
    aruco_wrap.W.CAL.setdefault("marker_offsets", {})["77"] = {
        "grip_z_offset_mm": 22.0}
    try:
        z77 = aruco_wrap.grip_z_offset(77)
        z99 = aruco_wrap.grip_z_offset(99)
        check("per-id grip depth overrides z-touch",
              z77 == 22.0 and z99 == aruco_wrap.Z_TOUCH,
              f"id77={z77} id99={z99} z_touch={aruco_wrap.Z_TOUCH}")
    finally:
        aruco_wrap.W.CAL["marker_offsets"].pop("77", None)
    cam_v, arm_v = aruco_wrap.model_stamps()
    check("model stamps present and matching",
          cam_v is not None and str(cam_v) == str(arm_v),
          f"cam={cam_v} arm={arm_v}")

    # ---- ground-truth anchors: derivation under the current model must
    # reproduce the stored claw arm; the agreement gate must refuse
    # disagreeing rows; derive_and_save restamps and keeps the values
    import anchors as ANC
    rows = ANC.derive()
    check("anchors stored (Generate anchor seed)", len(rows) >= 2,
          f"{len(rows)} rows")
    if len(rows) >= 2:
        import numpy as _np
        arms = _np.array([r["arm"] for r in rows])
        mean = arms.mean(0)
        stored = _np.array(aruco_wrap.W.CAL["claw_arm_tool_mm"], float)
        dis = max(float(_np.hypot(*(a - b))) for a in arms for b in arms)
        check("anchor derivation self-consistent and near the stored arm",
              dis < 1.0 and float(_np.hypot(*(mean - stored))) < 0.5,
              f"mean={mean.round(2).tolist()} stored={stored.tolist()} "
              f"disagreement={dis:.2f}")
        bad = [dict(rows[0], arm=None), ]  # synthetic disagreeing pair
        fake = [{"mark_px": [1500, 1000], "H_mm": 230.0,
                 "pose": [350.0, -180.0, 70.0],
                 "grab_tcp": [300.0, -300.0], "grab_rz": 80.0},
                {"mark_px": [1900, 1400], "H_mm": 230.0,
                 "pose": [350.0, -180.0, 70.0],
                 "grab_tcp": [300.0, -300.0], "grab_rz": 80.0}]
        fr = ANC.derive(fake)
        d = float(_np.hypot(*(_np.array(fr[0]["arm"])
                              - _np.array(fr[1]["arm"]))))
        check("disagreeing anchors are detectable", d > 1.0,
              f"disagreement {d:.1f} mm")
        res = ANC.derive_and_save()
        cam_v2, arm_v2 = aruco_wrap.model_stamps()
        check("derive_and_save writes the row-mean and restamps",
              res.get("ok") is True
              and abs(res["arm"][0] - float(mean[0])) < 0.05
              and abs(res["arm"][1] - float(mean[1])) < 0.05
              and str(cam_v2) == str(arm_v2), str(res)[:160])

    # ---- grasp-way evaluation on the REAL live capture from 2026-07-23:
    # board rotated ~155 deg off taught + placed far out -> every way's
    # convergence pose must compute beyond the 480 mm reach (the actual
    # diagnosis of that day's faults)
    live = os.path.join(ROOT, "bioyond-s4-mcp", "captures",
                        "cap0025_gige_raw.jpg")
    if os.path.exists(live):
        ev = teach.evaluate_ways(live, 411.077, -264.134, 280.049, -134.624)
        check("ways diagnosis on live capture", ev.get("detected") is True
              and len(ev["ways"]) == 2
              and all(w["conv_radius"] > 480 for w in ev["ways"]),
              str([(w["cfg"], w["conv_radius"], w["grasp_radius"])
                   for w in ev.get("ways", [])]))
        w0 = ev["ways"][0]
        check("way carries the +180 wrist alternative",
              abs(abs(w0["grasp_rz"] - w0["grasp_rz_alt"]) - 180.0) < 0.01
              or abs(abs(w0["grasp_rz"] - w0["grasp_rz_alt"]) - 180.0) > 359.9,
              f"rz={w0['grasp_rz']} alt={w0['grasp_rz_alt']}")

    # ---- find_disk plumbing: static replayed frame -> runs iterations,
    # never converges (image can't change), aborts cleanly. Z opens to
    # -1000: the replayed frame's radius-derived height error is huge, and
    # since the grasp estimate is height-corrected the way-feasibility
    # check would (rightly) reject every way in a 0-floor box.
    svc.set_envelope(0, 1000, -1000, 1000, -1000, 1000)
    svc.move_cartesian(305, -265, 270, -110)
    cam = FakeCam(FRAME_WITH_DISK)
    run5 = Runner()
    run5.start("find_disk", seq_find_disk, svc, cam, teach)
    wait(run5, timeout=300)
    iters = sum(1 for e in run5.log if "cfg" in e["msg"])
    guarded = any("refused" in e["msg"] or "physical reach" in e["msg"]
                  or "budget" in e["msg"] or "feasible" in e["msg"]
                  or "RISEN" in e["msg"] or "UNREACHABLE" in e["msg"]
                  for e in run5.log)
    # a static replayed frame can never converge. This scene's grasp ways
    # all sit far beyond physical reach (conv radii ~590-680): with the
    # exact kinematic guard the sequence may rightly refuse BEFORE moving
    # (guarded, 0 iterations) instead of stepping toward an unreachable
    # boundary — either path proves the capture -> solve -> plan plumbing
    check("find_disk ran the loop or guarded up front",
          iters >= 2 or guarded, f"iters={iters} guarded={guarded}")
    check("find_disk ended cleanly (no crash)",
          run5.state in ("done", "error"), run5.state)
    check("find_disk detected the disk",
          any("disk FOUND" in e["msg"] for e in run5.log))
    check("find_disk annotated the detection",
          run5.detection_ts > 0 and run5.detection_path is not None
          and os.path.exists(run5.detection_path))
    import re
    steps = [float(m.group(1)) for e in run5.log
             for m in [re.search(r"step ([\d.]+) of", e["msg"])] if m]
    check("find_disk adaptive steps bounded",
          all(s <= seqmod.STEP_MAX_MM + 0.05 for s in steps)
          and (steps or guarded), str(steps[:8]))

    # not-found path: a blank frame must abort with guidance and NO motion
    # (re-park at hover first — run5 rode Z down chasing the replayed
    # frame's huge height error and ended below the teach-view guard)
    svc.move_cartesian(305, -265, 270, -110)
    import numpy as np
    blank = os.path.join(HERE, "_fake_blank.png")
    cv2.imwrite(blank, np.full((2048, 3072), 30, dtype="uint8"))
    pose_before = svc.pose_mm()
    cam2 = FakeCam(blank)
    run6 = Runner()
    run6.start("find_disk", seq_find_disk, svc, cam2, teach)
    wait(run6, timeout=120)
    check("blank frame -> NOT FOUND + working-distance hint",
          run6.state == "error"
          and any("NOT FOUND" in e["msg"] and "working distance" in e["msg"]
                  for e in run6.log))
    check("not-found made no motion", svc.pose_mm() == pose_before,
          str(svc.pose_mm()))

    # ---- generate_anchor: vendor-exact full-correction loop. The replayed
    # frame's vendor targets sit far beyond the arm (conv radius ~600) ->
    # the reach REFUSAL must stop the run cleanly, saving NOTHING
    from sequences import seq_generate_anchor
    import aruco as aruco_mod2
    import anchors as ANC2
    n_before = ANC2.count()
    runA = Runner()
    runA.start("generate_anchor", seq_generate_anchor, svc,
               FakeCam(FRAME_WITH_DISK), teach, aruco_mod2)
    wait(runA, timeout=180)
    check("generate_anchor refuses out-of-reach vendor target",
          runA.state == "error"
          and any("outside the arm's limits" in e["msg"]
                  for e in runA.log), runA.state)
    check("failed anchor run saved nothing", ANC2.count() == n_before,
          f"{n_before} -> {ANC2.count()}")
    check("anchor run logged capture + pose",
          any("@ pose" in e["msg"] and "xy_err" in e["msg"]
              for e in runA.log))

    print("  find_disk log tail:")
    for e in run5.log[-4:]:
        print(f"    [{e['t']}] {e['msg'][:110]}")

    # ---- find_aruco: synthetic frame with a real 4x4_50 marker centered ->
    # centers (no motion needed), locks after two agreeing solves, publishes
    # a claw-arm-compensated TCP target in the standard target shape
    mk = cv2.aruco.generateImageMarker(
        cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), 3, 320)
    canvas = np.full((2048, 3072), 200, dtype="uint8")
    cy0, cx0 = 1024 - 160, 1536 - 160
    canvas[cy0:cy0 + 320, cx0:cx0 + 320] = mk
    aruco_png = os.path.join(HERE, "_fake_aruco.png")
    cv2.imwrite(aruco_png, canvas)
    # quarantine any REAL learned offset for id 3 (live calibration data)
    # so these checks run against the raw geometry; restored below
    _prev3 = aruco.W.CAL.get("marker_offsets", {}).pop("3", None)
    # pin CANONICAL camera constants for the synthetic scenes — the live
    # calibration (tilt/scale of the real camera) must not skew fixtures
    _cam_saved = (aruco.W.CAM_ARM.copy(), aruco.W.BPSI,
                  aruco.W.TILT.copy(), aruco.W.USCALE, aruco.W.MIRROR,
                  aruco.W.HSCALE)
    aruco.W.CAM_ARM = np.array([10.71, 54.96])
    aruco.W.BPSI = 90.5
    aruco.W.TILT = np.array([0.0, 0.0])
    aruco.W.USCALE = 1.0
    aruco.W.MIRROR = -1.0
    aruco.W.HSCALE = 1.0
    cam3 = FakeCam(aruco_png)
    run7 = Runner()
    run7.start("find_aruco", seq_find_aruco, svc, cam3, aruco)
    wait(run7, timeout=120)
    t7 = run7.target if run7.state == "done" else None
    check("find_aruco ended cleanly", run7.state in ("done", "error"),
          run7.state)
    check("find_aruco published a target", t7 is not None
          and all(k in t7 for k in ("x", "y", "rz", "z_calibrated"))
          and str(t7.get("config", "")).startswith("ArUco"),
          str({k: t7.get(k) for k in ("x", "y", "rz", "z_calibrated",
                                      "config")} if t7 else run7.log[-1]))
    if t7 is not None:
        # the published TCP must be the marker position minus the claw arm
        import math as _m
        mw_line = next(e["msg"] for e in run7.log if "GRAB TARGET" in e["msg"])
        a = _m.radians(float(t7["rz"]))
        arm = aruco.CLAW_ARM
        claw_x = t7["x"] + arm[0] * _m.cos(a) - arm[1] * _m.sin(a)
        claw_y = t7["y"] + arm[0] * _m.sin(a) + arm[1] * _m.cos(a)
        check("find_aruco claw-arm math consistent",
              "GRAB TARGET" in mw_line and
              abs(_m.hypot(claw_x - float(mw_line.split("(")[1].split(",")[0]),
                           claw_y - float(mw_line.split("(")[1]
                                          .split(",")[1].split(")")[0])))
              < 0.5, f"claw=({claw_x:.1f},{claw_y:.1f})")
    print("  find_aruco log tail:")
    for e in run7.log[-4:]:
        print(f"    [{e['t']}] {e['msg'][:110]}")

    # ---- learned per-marker grasp offset: applied in the MARKER frame
    import math as _m2
    s0 = aruco.solve(aruco_png, 305, -265, 270, -110)
    aruco.W.CAL.setdefault("marker_offsets", {})["3"] = {"dx_mm": 5.0,
                                                         "dy_mm": -3.0}
    try:
        s1 = aruco.solve(aruco_png, 305, -265, 270, -110)
        yw = _m2.radians(s0["marker_yaw_deg"])
        exp_dx = 5.0 * _m2.cos(yw) - (-3.0) * _m2.sin(yw)
        exp_dy = 5.0 * _m2.sin(yw) + (-3.0) * _m2.cos(yw)
        got_dx = s1["grab_point"][0] - s0["grab_point"][0]
        got_dy = s1["grab_point"][1] - s0["grab_point"][1]
        check("marker offset rotates with the marker frame",
              abs(got_dx - exp_dx) < 0.05 and abs(got_dy - exp_dy) < 0.05,
              f"got ({got_dx:.2f},{got_dy:.2f}) want "
              f"({exp_dx:.2f},{exp_dy:.2f})")
        check("marker offset shifts the grab TCP",
              abs((s1["grab_candidates"][0]["tcp"][0]
                   - s0["grab_candidates"][0]["tcp"][0]) - got_dx) < 0.05)
    finally:
        aruco.W.CAL["marker_offsets"].pop("3", None)
        if _prev3 is not None:
            aruco.W.CAL.setdefault("marker_offsets", {})["3"] = _prev3

    # ---- ALL FOUR grab approaches: two clamp axes x two wrist sides,
    # span-gated against the claw window (60-88 mm gap)
    _cur3 = aruco.W.CAL.get("marker_offsets", {}).pop("3", None)
    try:
        s4 = aruco.solve(aruco_png, 305, -265, 270, -110)
        c4 = s4["grab_candidates"]
        check("solver emits 4 approaches (2 axes x 2 sides)",
              len(c4) == 4 and [c["axis"] for c in c4]
              == ["width", "width", "length", "length"],
              str([c.get("axis") for c in c4]))
        rz0 = c4[0]["rz"]
        rel = sorted(round((c["rz"] - rz0) % 360.0, 1) for c in c4)
        check("approach angles are 0/90/180/270 apart",
              rel == [0.0, 90.0, 180.0, 270.0], str(rel))
        check("uncalibrated id -> span unknown, reach-only feasibility",
              all(c["span_mm"] is None and c["clampable"] is None
                  for c in c4),
              str([(c["span_mm"], c["clampable"]) for c in c4]))
        aruco.W.CAL.setdefault("marker_offsets", {})["3"] = {
            "dx_mm": 0.0, "dy_mm": 0.0, "rel_yaw_deg": 0.0,
            "width_mm": 70.0, "length_mm": 120.0}
        s5 = aruco.solve(aruco_png, 305, -265, 270, -110)
        w5 = [c for c in s5["grab_candidates"] if c["axis"] == "width"]
        l5 = [c for c in s5["grab_candidates"] if c["axis"] == "length"]
        check("clampable width passes the claw window",
              len(w5) == 2 and all(c["clampable"] is True for c in w5),
              str(w5 and w5[0]))
        # claw guard REMOVED per operator (2026-07-28): span is
        # informational — feasible must equal ARM reachability alone
        import math as _m3
        lim = aruco.W._LIM
        exp = [(_m3.hypot(c["tcp"][0] - lim["base_x_mm"],
                          c["tcp"][1] - lim["base_y_mm"])
                <= lim["link1_mm"] + lim["link2_mm"]
                - lim["extension_margin_mm"]) for c in l5]
        check("overwide length flagged but feasibility = reach only",
              len(l5) == 2 and all(c["clampable"] is False for c in l5)
              and [c["feasible"] for c in l5] == exp,
              str([(c["feasible"], c["clampable"], e)
                   for c, e in zip(l5, exp)]))
    finally:
        aruco.W.CAL["marker_offsets"].pop("3", None)
        if _cur3 is not None:
            aruco.W.CAL.setdefault("marker_offsets", {})["3"] = _cur3

    # ---- calibrate disk id: dark disk on light background, marker glued
    # off-center -> edge detection must measure the offset and spans
    canvas2 = np.full((2048, 3072), 200, dtype="uint8")
    canvas2[274:1774, 336:2736] = 60                    # the "disk"
    mkx, mky = 1536 + 200 - 160, 1024 - 130 - 160       # marker center +200,-130
    canvas2[mky - 50:mky + 370, mkx - 50:mkx + 370] = 255   # quiet zone
    canvas2[mky:mky + 320, mkx:mkx + 320] = mk
    acal_png = os.path.join(HERE, "_fake_acal_scene.png")
    cv2.imwrite(acal_png, canvas2)
    calres = aruco.calibrate(acal_png, 305, -265, 270, -110)
    mmpp = 16.553 / 320.0
    exp_off = (200 ** 2 + 130 ** 2) ** 0.5 * mmpp
    got_off = ((calres["entry"]["dx_mm"] ** 2
                + calres["entry"]["dy_mm"] ** 2) ** 0.5
               if calres.get("ok") else -1)
    check("calibrate_disk finds the disk and offset",
          calres.get("ok") is True and abs(got_off - exp_off) < 1.0,
          f"offset {got_off:.2f} vs {exp_off:.2f} mm")
    check("calibrate_disk measures the spans",
          calres.get("ok") is True
          and abs(calres["entry"]["length_mm"] - 2400 * mmpp) < 3
          and abs(calres["entry"]["width_mm"] - 1500 * mmpp) < 3,
          str(calres.get("entry")))

    # ---- 180-degree invariance: rotate the SAME disk+marker 180 deg about
    # the disk center -> with the scene-A calibration applied, the solved
    # grab point must land on the same physical spot
    entryA = calres["entry"]
    canvas3 = np.full((2048, 3072), 200, dtype="uint8")
    canvas3[274:1774, 336:2736] = 60                    # same disk footprint
    mk180 = np.rot90(mk, 2)
    m2x, m2y = 1536 - 200 - 160, 1024 + 130 - 160       # mirrored placement
    canvas3[m2y - 50:m2y + 370, m2x - 50:m2x + 370] = 255
    canvas3[m2y:m2y + 320, m2x:m2x + 320] = mk180
    rot_png = os.path.join(HERE, "_fake_aruco_rot180.png")
    cv2.imwrite(rot_png, canvas3)
    aruco.W.CAL.setdefault("marker_offsets", {})["3"] = dict(entryA)
    try:
        sA = aruco.solve(acal_png, 305, -265, 270, -110)
        sB = aruco.solve(rot_png, 305, -265, 270, -110)
        dyaw = abs(((sB["marker_yaw_deg"] - sA["marker_yaw_deg"]) + 180)
                   % 360 - 180)
        gpA, gpB = sA["grab_point"], sB["grab_point"]
        check("marker yaw flips 180 with the object",
              abs(dyaw - 180.0) < 1.5, f"dyaw={dyaw:.2f}")
        check("grab point invariant under 180-deg disk rotation",
              abs(gpA[0] - gpB[0]) < 1.0 and abs(gpA[1] - gpB[1]) < 1.0,
              f"A={gpA} B={gpB}")
    finally:
        aruco.W.CAL["marker_offsets"].pop("3", None)
        if _prev3 is not None:
            aruco.W.CAL.setdefault("marker_offsets", {})["3"] = _prev3

    # full sequence path with save stubbed (never touch the real file)
    saved_entries = []
    orig_save = aruco.save_disk
    aruco.save_disk = lambda mid, e, note="": (saved_entries.append((mid, e))
                                               or e)
    try:
        cam4 = FakeCam(acal_png)
        run8 = Runner()
        run8.start("calibrate_aruco", seq_calibrate_aruco, svc, cam4, aruco)
        wait(run8, timeout=120)
        check("calibrate sequence completes and saves",
              run8.state == "done" and len(saved_entries) == 1
              and saved_entries[0][0] == 3,
              f"state={run8.state} saved={len(saved_entries)}")
        if run8.state != "done":
            print("  calibrate seq log tail:")
            for e in run8.log[-6:]:
                print(f"    [{e['t']}] {e['msg'][:110]}")
        check("calibrate sequence annotated the edges",
              run8.detection_path is not None
              and os.path.exists(run8.detection_path))
    finally:
        aruco.save_disk = orig_save
        (aruco.W.CAM_ARM, aruco.W.BPSI, aruco.W.TILT, aruco.W.USCALE,
         aruco.W.MIRROR, aruco.W.HSCALE) = _cam_saved

    # ---- camera-mount fit with tilt: synthetic rows from known constants
    # must be recovered exactly (the auto-calibration's math core)
    import numpy as _np
    rng_c = _np.array([12.5, 52.0])
    rng_t = _np.array([0.004, -0.007])
    rng_s = 1.15
    rng_b = 88.75
    rng_m = _np.array([350.0, -250.0])

    def _R(d):
        a = _np.radians(d)
        return _np.array([[_np.cos(a), -_np.sin(a)],
                          [_np.sin(a), _np.cos(a)]])
    Fm = _np.diag([1.0, -1.0])
    synth_rows = []
    for rz_s, dx_s, dy_s, H_s in ((70, 0, 0, 190), (70, 30, 0, 190),
                                  (70, 0, 30, 190), (70, -30, 0, 220),
                                  (100, 5, 3, 190), (40, -4, 6, 190),
                                  (130, 8, -5, 205), (10, -6, -8, 205),
                                  (160, 3, 9, 190), (-20, -9, 2, 220)):
        T = _np.array([320.0 + dx_s, -220.0 + dy_s])
        # invert the model to get the pnp u this row would measure
        rhs = rng_m - T - _R(rz_s) @ rng_c
        u_f = (_np.linalg.solve(_R(rz_s + rng_b) @ Fm, rhs)
               - rng_t * H_s) / rng_s
        synth_rows.append({"x": T[0], "y": T[1], "rz": rz_s,
                           "ux": float(u_f[0]), "uy": float(u_f[1]),
                           "H": H_s})
    fitres = aruco.fit_mount(synth_rows)
    check("camera fit recovers lever arm + tilt + scale",
          abs(fitres["lever_arm_mm"][0] - 12.5) < 0.05
          and abs(fitres["lever_arm_mm"][1] - 52.0) < 0.05
          and abs(fitres["tilt_per_mm"][0] - 0.004) < 0.0005
          and abs(fitres["tilt_per_mm"][1] + 0.007) < 0.0005
          and abs(fitres["u_scale"] - 1.15) < 0.005
          and abs(fitres["yaw_offset_deg"] - 88.75) < 0.3
          and fitres["mirror_f"] == -1.0
          and fitres["rms_mm"] < 0.05,
          str(fitres))

    # portability: a camera mounted the OTHER way (mirror +1) must be
    # auto-detected, and the Z scale regressed from height-diverse rows
    Fp = _np.diag([1.0, 1.0])
    rows_p = []
    hsc = 0.94
    for rz_s, dx_s, dy_s, H_s in ((70, 0, 0, 190), (70, 40, 0, 190),
                                  (70, 0, 40, 220), (100, 5, 3, 190),
                                  (40, -4, 6, 190), (130, 8, -5, 205),
                                  (10, -6, -8, 205), (160, 3, 9, 190)):
        T = _np.array([320.0 + dx_s, -220.0 + dy_s])
        rhs = rng_m - T - _R(rz_s) @ rng_c
        u_f = (_np.linalg.solve(_R(rz_s + rng_b) @ Fp, rhs)
               - rng_t * H_s) / rng_s
        rows_p.append({"x": T[0], "y": T[1], "z": 300.0 + hsc * H_s,
                       "rz": rz_s, "ux": float(u_f[0]),
                       "uy": float(u_f[1]), "H": H_s})
    fit_p = aruco.fit_mount(rows_p)
    check("camera fit auto-detects mirror and Z scale",
          fit_p["mirror_f"] == 1.0 and fit_p["rms_mm"] < 0.05
          and abs(fit_p.get("h_scale", 0) - hsc) < 0.005,
          str({k: fit_p.get(k) for k in ("mirror_f", "h_scale",
                                         "rms_mm")}))

    # two-sided claw-arm solve: separates true arm from camera bias
    arm_t = _np.array([181.2, -6.4])
    bias_t = _np.array([4.7, -2.1])
    th1, th2 = 87.0, -95.0
    m1 = arm_t + _R(-th1) @ bias_t
    m2 = arm_t + _R(-th2) @ bias_t
    arm_r, bias_r = aruco.W.solve_claw_arm_two(m1, th1, m2, th2)
    check("two-sided claw-arm solve separates arm from bias",
          abs(arm_r[0] - 181.2) < 0.01 and abs(arm_r[1] + 6.4) < 0.01
          and abs(bias_r[0] - 4.7) < 0.01 and abs(bias_r[1] + 2.1) < 0.01,
          f"arm={arm_r.round(2).tolist()} bias={bias_r.round(2).tolist()}")

    # robot params: loader falls back to defaults and honours the file
    from sequences import _robot_params
    rp = _robot_params()
    check("robot params load (file or defaults)",
          rp["reach_hard_mm"] > 0 and rp["j4_hard_abs_deg"]
          > rp["j4_pref_abs_deg"]
          and rp["claw_gap_max_mm"] > rp["claw_gap_min_mm"], str(rp))

    # ---- operator torque-threshold plumbing (torque feedback tab)
    from sequences import TORQUE_CFG_PATH, band_floor
    had = os.path.exists(TORQUE_CFG_PATH)
    backup = open(TORQUE_CFG_PATH).read() if had else None
    if had:
        os.remove(TORQUE_CFG_PATH)
    check("band floor defaults to 25", band_floor() == 25.0,
          str(band_floor()))
    with open(TORQUE_CFG_PATH, "w", encoding="utf-8") as f:
        f.write('{"band_counts": 60}')
    check("band floor takes the operator value", band_floor() == 60.0,
          str(band_floor()))
    os.remove(TORQUE_CFG_PATH)
    if had and backup:
        with open(TORQUE_CFG_PATH, "w", encoding="utf-8") as f:
            f.write(backup)

    for f in os.listdir(HERE):
        if f.startswith("_fake_"):
            os.remove(os.path.join(HERE, f))

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
