"""Offline end-to-end test: MCP tool functions against the fake controller."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fake_controller import FakeController  # noqa: E402
import server  # noqa: E402


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {detail}")
    if not cond:
        sys.exit(1)


def main():
    fake = FakeController()

    r = server.connect(ip="127.0.0.1", port=fake.port)
    check("connect", r.get("ok") and r.get("connected"), str(r.get("system_state")))

    r = server.get_status()
    check("get_status", r["ok"] and r["control_mode"]["mode"] == "auto"
          and r["enabled"] and r["program_state"]["state"] == "running")

    r = server.get_cartesian_pose()
    check("pose meters->mm", r["ok"] and r["pose_mm"] == {"X": 300.0, "Y": -50.0, "Z": 370.0},
          str(r["pose_mm"]))

    r = server.get_joint_positions()
    check("get_joint_positions", r["ok"] and r["joints"]["J1"] == 250.0)

    # envelope refusals
    for kw, label in (
        (dict(x=100, y=-50, z=370), "X"),
        (dict(x=300, y=100, z=370), "Y"),
        (dict(x=300, y=-50, z=200), "Z"),
    ):
        r = server.move_to_cartesian(rz=90.0, **kw)
        check(f"envelope: bad {label} refused", not r["ok"] and "envelope" in r["error"])

    # host-point Cartesian move (in-envelope)
    r = server.move_to_cartesian(x=310.0, y=-60.0, z=390.0, rz=45.0, speed=9999)
    check("move_to_cartesian completes", r["ok"], str(r.get("error", "")))
    check("linear speed capped", fake.para_f[4] == server.LINEAR_SPEED_MAX,
          str(fake.para_f.get(44)))
    check("paraF slots 0-3 written", fake.para_f[0] == 310.0
          and fake.para_f[2] == 390.0)
    check("pose updated", r["pose_after_mm"]["X"] == 310.0
          and r["pose_after_mm"]["Z"] == 390.0, str(r["pose_after_mm"]))

    # gripper via host-point, with torque feedback
    r = server.move_gripper(e1_position=25.0)
    check("move_gripper completes", r["ok"] and fake.e1 == 25.0)
    check("free motion: positive torque, no grip",
          r["gripper"]["e1_torque"] == fake.free_torque
          and not r["gripper"]["grip_detected"], str(r["gripper"]))
    r = server.move_gripper(e1_position=22.5)
    check("squeeze: negative torque + position stall = grip_detected",
          r["gripper"]["grip_detected"]
          and r["gripper"]["e1_torque"] < server.GRIP_TORQUE_THRESHOLD
          and r["gripper"]["position_error"] > server.GRIP_POS_ERROR,
          str(r["gripper"]))
    r = server.gripper_status()
    check("gripper_status (no motion)", r["ok"]
          and abs(r["e1_position"] - fake.object_width) < 0.01, str(r))
    r = server.grip_with_force_limit(e1_position=20.0, force_limit=30.0)
    check("force-limited grip stops at object",
          r["ok"] and abs(r["gripper"]["e1_position"] - fake.object_width) < 0.2
          and r["gripper"]["grip_detected"], str(r.get("gripper")))
    r = server.move_gripper(e1_position=28.0)
    check("gripper reopens, grip cleared", r["ok"] and fake.e1 == 28.0
          and not r["gripper"]["grip_detected"])

    # adaptive torque-based grip
    r = server.grip_by_torque(torque_threshold=-100.0)
    check("grip_by_torque grips", r["ok"] and r["gripped"]
          and r["grip_torque"] <= -100.0
          and abs(r["grip_position"] - fake.object_width) < 0.05,
          f"stopped at cmd {r.get('stopped_at_command')} after {r.get('steps')} steps")
    check("grip log recorded", len(r["log"]) == r["steps"] + 1)
    r = server.move_gripper(e1_position=28.0)
    check("release after adaptive grip", r["ok"])
    fake.object_width = 0.0  # nothing between the fingers
    r = server.grip_by_torque(torque_threshold=-100.0, floor=26.0)
    check("grip_by_torque empty close fails + reopens",
          not r["ok"] and not r["gripped"] and fake.e1 == 28.0,
          r.get("error", "")[:70])
    fake.object_width = 23.34

    # joint move gated + works
    r = server.move_joints(j1=200.0, j2=0.0, j3=0.0, j4=0.0)
    check("move_joints requires confirmation", not r["ok"])
    r = server.move_joints(j1=200.0, j2=0.0, j3=0.0, j4=0.0, operator_confirmed=True)
    check("move_joints completes", r["ok"] and fake.joints[0] == 200.0)

    # unsupported program -> clean -1 detection
    fake.hostpoint_supported = False
    r = server.move_to_cartesian(x=310.0, y=-60.0, z=390.0, rz=45.0)
    check("stock program detected via -1", not r["ok"]
          and "main_hostpoint.bin" in r["error"], r.get("error", "")[:80])
    fake.hostpoint_supported = True

    # taught jobs
    r = server.go_home()
    check("go_home requires confirmation", not r["ok"])
    r = server.go_home(operator_confirmed=True)
    check("go_home completes", r["ok"] and fake.joints[0] == 66.75)

    r = server.run_station_job(11, "pick")
    check("station job requires confirmation", not r["ok"])
    r = server.run_station_job(11, "pick", operator_confirmed=True)
    check("station pick completes", r["ok"])
    check("station vars pattern", fake.job_log[-1]["vars"][0] == 11
          and fake.job_log[-1]["vars"][4] == 1)
    r = server.run_station_job(99, "pick", operator_confirmed=True)
    check("bad device id refused", not r["ok"])

    # safety gates on state
    r = server.enable_robot()
    check("enable requires confirmation", not r["ok"])
    r = server.clear_errors()
    check("clear_errors requires confirmation", not r["ok"])

    fake.errors = [{"errCode": 3873, "errMsg": "Collision detected"}]
    r = server.move_to_cartesian(x=310.0, y=-60.0, z=390.0, rz=45.0)
    check("motion refused while errors active", not r["ok"] and "3873" in r["error"])
    fake.errors = []

    fake.mode = 0
    r = server.move_to_cartesian(x=310.0, y=-60.0, z=390.0, rz=45.0)
    check("motion refused in manual mode", not r["ok"] and "manual" in r["error"])
    fake.mode = 1

    # envelope adjustment tool
    r = server.set_workspace_envelope(0, 500, -300, 300, 50, 450)
    check("envelope change requires confirmation", not r["ok"])
    r = server.set_workspace_envelope(0, 500, -300, 300, 50, 450,
                                      operator_confirmed=True)
    check("envelope change applied", r["ok"] and server.ENVELOPE["Z"] == (50.0, 450.0))
    r = server.move_to_cartesian(x=310.0, y=-60.0, z=100.0, rz=45.0)
    check("move allowed in widened envelope", r["ok"], r.get("error", "")[:80])

    r = server.switch_mode("manual")
    check("switch_mode", r["ok"] and fake.mode == 0)
    r = server.switch_mode("auto")
    check("switch back to auto", r["ok"] and fake.mode == 1)
    r = server.enable_robot(operator_confirmed=True)
    check("enable with confirmation", r["ok"])

    r = server.read_system_values(para_f_indexes=[0, 1, 2])
    check("string paraF coerced to float", r["ok"]
          and isinstance(r["sys_para_f"][0], float))

    r = server.raw_brcapi("getSysState")
    check("raw_brcapi query", r["ok"] and r["response"]["ret"]["value"] == 1)
    r = server.raw_brcapi("setSysVarI")
    check("raw_brcapi blocks motion cmds", not r["ok"])

    r = server.disconnect()
    check("disconnect", r["ok"])
    r = server.get_cartesian_pose()
    check("query after disconnect fails cleanly", not r["ok"])

    print("\nAll offline tests passed.")


if __name__ == "__main__":
    main()
