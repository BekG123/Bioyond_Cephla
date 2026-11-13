"""The arm service against a simulated controller: the Lua queue protocol 220109, the gripper and the state reads.
No robot, no Squid. The routes are the real accepted ones, read from their files."""
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from arm_service import motion, routes  # noqa: E402
from arm_service.server import create_app  # noqa: E402
from arm_service.service import ArmService, Refused  # noqa: E402

TAUGHT = routes.taught()
CFG = TAUGHT["delivery"]["cfg"]
ENVELOPE = {k: tuple(v) for k, v in TAUGHT["delivery"]["envelope"].items()}
HOME = routes.legs(TAUGHT)["home"]


def home_joints():
    from hotel_slot_trial import reference

    return dict(reference()[0]["start_joints"])


class FakeRobot:
    """The controller registers and the Lua queue jobs (device 22), as mod_Trajectory_segment_speeds.lua answers."""

    def __init__(self, arm):
        self.arm = arm
        self.connected = True
        self.regs = {7: 0, 17: 220109, 18: 0, 19: 0}
        self.floats = {}
        self.points = []
        self.program = "running"
        self.errors = []
        self.hold_execute = threading.Event()  # set: op 4 waits until Stop
        self.stopped = threading.Event()

    def get_lua_app_status(self):
        return self.program == "running"

    def get_sys_var_i(self, indexes):
        return {i: self.regs.get(i, 0) for i in indexes}

    def set_sys_para_f(self, values):
        self.floats = dict(values)

    def get_prog_state(self):
        return {"state": self.program}

    def prog_stop(self):
        self.program = "stopped"
        self.stopped.set()
        return "ok"

    def set_sys_var_i(self, values, reply_timeout=10):
        op, token = values[4], values[2]
        if op == 6:
            return {"index": 1, "value": 220109}
        if op == 8:
            self.points, self.speeds = [], []
            self.expected = int(self.floats[0])
            self.regs.update({7: token, 18: 1, 19: 0})
        elif op == 9:
            count, f = values[5], self.floats
            for i in range(count):
                x, y, z, rz, v = (f[i * 5 + j] for j in range(5))
                self.points.append(dict(X=x, Y=y, Z=z, Rz=rz))
                self.speeds.append(v)
            self.regs[19] = len(self.points)
        elif op == 3:
            self.regs[18] = 2
        elif op == 4:
            if self.hold_execute.is_set():
                self.stopped.wait(5)
                raise RuntimeError("program stopped during the queue")
            start = self.arm.pose
            self.arm.joints_now = routes.check_queue(start, self.arm.joints_now, self.points, CFG, ENVELOPE)
            self.arm.pose = dict(self.points[-1], Rx=0.0, Ry=0.0)
            self.regs[18] = 4
            self.arm.moves.append(list(self.points))
        return {"index": 1, "value": 1}


class FakeArm:
    """The parts of operator_ui/robot_service.RobotService that the arm service uses."""

    def __init__(self, e1=7.0):
        self.robot = FakeRobot(self)
        self.envelope = dict(ENVELOPE)
        self.envelope_enabled = True
        self.pose = dict(HOME, Rx=0.0, Ry=0.0)
        self.joints_now = home_joints()
        self.e1 = e1
        self.moves = []
        self.gripper_moves = []

    def joints(self):
        return dict(self.joints_now)

    def _preflight(self):
        if self.robot.errors:
            return "robot has active errors"
        return None if self.robot.program == "running" else f"Lua program is '{self.robot.program}'"

    def pose_mm(self):
        return dict(self.pose)

    def status(self):
        return dict(ok=True, connected=True, errors=list(self.robot.errors), enabled=True,
                    control_mode={"mode": "auto"}, program_state={"state": self.robot.program},
                    pose_mm=dict(self.pose), joints=dict(self.joints_now), external_axes={"E1": self.e1})

    def _locked(self, fn):
        return fn()

    def program(self, action, force=False):
        if action == "stop":
            return {"ok": True, "reply": self.robot.prog_stop()}
        self.robot.program = "running"
        self.e1 = 0.0  # program start closes the jaws fully
        return {"ok": True, "notes": []}

    def clear_errors(self, confirmed):
        assert confirmed is True
        self.robot.errors = []
        return {"ok": True, "errors_after": []}

    def move_gripper(self, target, speed):
        self.gripper_moves.append((target, speed))
        self.e1 = target
        return {"ok": True}

    def torque_report(self):
        return {"ok": True, "e1_position": self.e1, "e1_torque": -150.0 if self.e1 < 5 else 160.0,
                "telemetry_live": True}


@pytest.fixture(autouse=True)
def native(monkeypatch):
    import home_hamilton_exchange

    def fake(service):
        return dict(moving=False, error=False, emergency=False, drag=False, manual=False,
                    external_units={"E1": "mm", "E2": "degrees"},
                    external_axes={"E1": service.e1, "E2": 1.77})

    monkeypatch.setattr(home_hamilton_exchange, "native", fake)


@pytest.fixture
def arm(tmp_path):
    fake = FakeArm()
    squid = []
    service = ArmService(fake, cfg=CFG, taught=TAUGHT, squid_check=lambda: squid.append(1) or {}, runs=tmp_path)
    service.fake, service.squid_calls = fake, squid
    return service


def run_to_end(arm, direction):
    plan = arm.plan(direction)
    assert plan["executable"], plan["blockers"]
    arm.start(plan["id"])
    arm.wait(30)
    return arm.state()["run"]


def test_slot_to_microscope_runs_the_joined_taught_route_in_three_queues(arm):
    run = run_to_end(arm, "load")
    assert run["ok"] is True, run["error"]
    assert run["started_moving_at"] is not None
    assert arm.plate["at"] == "Squid"
    moves = arm.fake.moves
    assert len(moves) == 3  # empty to the slot; slot to Squid holding the plate; empty back
    assert moves[1][-1] == {"X": 223.94, "Y": 373.76, "Z": 268.77, "Rz": 88.34}  # the Squid seat
    assert all(p["Z"] > 100 for move in moves for p in move)  # never down to the HOME holder (seat Z 75.72)
    assert arm.fake.gripper_moves == [(4.9, 10), (3.9, 5), (7.0, 5)]  # two-speed grip in the slot, release at Squid
    assert arm.fake.pose["Z"] == HOME["Z"] and arm.squid_calls  # parked at the safe position; Squid was checked


def test_the_next_move_is_uploaded_while_the_grip_settles_and_lifts_are_faster(arm):
    run_to_end(arm, "load")
    log = (arm._runs / time.strftime("%Y-%m-%d")).glob("*.jsonl")
    events = [line for path in log for line in path.read_text(encoding="utf-8").splitlines()]
    assert any('"uploaded"' in e and "Slot 1 to Squid" in e for e in events)  # during the grip
    assert any('"uploaded"' in e and "Back to the safe position" in e for e in events)  # during the release
    loaded = [s for s in routes.legs(TAUGHT)["load"] if s["kind"] == "queue"][1]
    assert loaded["speeds"][0] == routes.LIFT_SPEED == 20  # the 5 mm off the slot rails
    back = [s for s in routes.legs(TAUGHT)["load"] if s["kind"] == "queue"][2]
    assert back["speeds"][0] == 20  # the 5 mm off the Squid seat
    assert loaded["speeds"][-1] == 5  # the last 10 mm onto the Squid seat stay at the taught 5


def test_a_grip_that_does_not_settle_never_runs_the_uploaded_move(arm, monkeypatch):
    fake = arm.fake
    report = fake.torque_report

    def slipping():
        result = report()
        fake.e1 = 5.5  # the plate slips out after the torque report
        return result

    monkeypatch.setattr(fake, "torque_report", slipping)
    plan = arm.plan("load")
    arm.start(plan["id"])
    arm.wait(30)
    run = arm.state()["run"]
    assert run["ok"] is False and "did not settle" in run["error"]
    assert len(fake.moves) == 1  # only the empty move to the slot; the uploaded move with the plate never ran


def test_a_release_that_does_not_open_never_runs_the_uploaded_move(arm, monkeypatch):
    fake = arm.fake
    move = fake.move_gripper

    def stuck(target, speed):
        result = move(target, speed)
        if target == routes.EMPTY_E1 and len(fake.moves) == 2:  # the release at Squid: the jaws stay closed
            fake.e1 = routes.GRIP_E1
        return result

    monkeypatch.setattr(fake, "move_gripper", stuck)
    plan = arm.plan("load")
    arm.start(plan["id"])
    arm.wait(30)
    run = arm.state()["run"]
    assert run["ok"] is False and "did not arrive" in run["error"]
    assert len(fake.moves) == 2  # the empty arm never left the plate at Squid


def test_a_queue_that_the_controller_dropped_during_the_grip_is_uploaded_again(arm, monkeypatch):
    fake = arm.fake
    move = fake.move_gripper

    def forgetting(target, speed):
        result = move(target, speed)
        fake.robot.regs[18] = 0  # a gripper job that cleared the committed queue
        return result

    monkeypatch.setattr(fake, "move_gripper", forgetting)
    run = run_to_end(arm, "load")
    assert run["ok"] is True, run["error"]
    assert len(fake.moves) == 3 and fake.moves[1][-1]["Z"] == 268.77  # it ran, after a second upload


def test_microscope_to_slot_after_a_load(arm):
    run_to_end(arm, "load")
    run = run_to_end(arm, "unload")
    assert run["ok"] is True, run["error"]
    assert arm.plate["at"] == "slot 1"
    assert arm.fake.moves[-2][-1]["X"] == pytest.approx(290.88)  # into slot 1 holding the plate


def test_a_load_is_refused_while_this_service_left_a_plate_at_squid(arm):
    run_to_end(arm, "load")
    plan = arm.plan("load")
    assert not plan["executable"] and "take it back first" in " ".join(plan["blockers"])


def test_only_slot_1_is_taught(arm):
    with pytest.raises(Refused, match="Only slot 1"):
        arm.plan("load", 2)


def test_jaws_open_wide_are_set_to_7_first_and_jaws_that_may_hold_a_plate_block(arm):
    arm.fake.e1 = 28.0
    plan = arm.plan("load")
    assert plan["executable"] and plan["steps"][0]["label"].startswith("Set the empty jaws")
    arm.fake.e1 = 4.2
    plan = arm.plan("load")
    assert not plan["executable"] and "may hold a plate" in " ".join(plan["blockers"])


def test_the_arm_must_be_at_the_safe_position(arm):
    arm.fake.pose = dict(arm.fake.pose, X=arm.fake.pose["X"] + 5)
    plan = arm.plan("load")
    assert not plan["executable"] and "safe position" in " ".join(plan["blockers"])


def test_stop_during_a_move_stops_the_program_and_ends_the_run(arm):
    arm.fake.robot.hold_execute.set()
    plan = arm.plan("load")
    arm.start(plan["id"])
    deadline = time.monotonic() + 5
    while not arm.state()["run"].get("moving") and time.monotonic() < deadline:
        time.sleep(0.02)
    assert arm.state()["run"]["moving"] is True
    arm.stop()
    arm.wait(10)
    run = arm.state()["run"]
    assert run["ok"] is False and run["active"] is False and "Stop" in run["error"]
    assert arm.fake.robot.program == "stopped" and arm.plate is None


def test_clear_errors_and_restart_are_refused_while_a_run_is_active_and_work_after(arm):
    arm.fake.robot.hold_execute.set()
    plan = arm.plan("load")
    arm.start(plan["id"])
    time.sleep(0.3)
    with pytest.raises(Refused):
        arm.clear_errors()
    with pytest.raises(Refused):
        arm.start_program()
    arm.stop()
    arm.wait(10)
    arm.fake.robot.errors = ["E-stop"]
    assert arm.clear_errors()["ok"] is True
    assert arm.start_program()["ok"] is True and arm.fake.robot.program == "running"


def test_a_plan_cannot_start_twice_or_after_it_was_replaced(arm):
    first = arm.plan("load")
    second = arm.plan("load")
    with pytest.raises(Refused, match="does not wait"):
        arm.start(first["id"])
    arm.start(second["id"])
    arm.wait(30)
    with pytest.raises(Refused):
        arm.start(second["id"])


def test_an_empty_arm_left_in_slot_1_goes_back_on_the_taught_way(arm):
    slot = [s for s in routes.legs(TAUGHT)["unload"] if s["kind"] == "queue"][-2]["points"][-1]
    arm.fake.pose = dict(slot, Rx=0.0, Ry=0.0)
    arm.fake.joints_now = routes.check_queue(HOME, home_joints(), [s for s in routes.legs(TAUGHT)["load"]
                                                                   if s["kind"] == "queue"][0]["points"], CFG, ENVELOPE)
    assert arm.state()["robot"]["at_safe_position"] is False
    plan = arm.plan("recover")
    assert plan["executable"], plan["blockers"]
    assert plan["summary"] == "Empty arm back to the safe position (from slot 1)"
    arm.start(plan["id"])
    arm.wait(30)
    assert arm.state()["run"]["ok"] is True
    assert arm.fake.pose["Z"] == HOME["Z"] and arm.fake.moves[-1][0]["X"] == pytest.approx(154.41)
    assert arm.fake.gripper_moves == []  # the jaws stay open: nothing is gripped


def test_no_recovery_from_an_unknown_place_or_with_closed_jaws(arm):
    arm.fake.pose = dict(arm.fake.pose, X=300.0)
    plan = arm.plan("recover")
    assert not plan["executable"] and "not where a plate was just released" in plan["blockers"][0]
    slot = [s for s in routes.legs(TAUGHT)["unload"] if s["kind"] == "queue"][-2]["points"][-1]
    arm.fake.pose, arm.fake.e1 = dict(slot, Rx=0.0, Ry=0.0), 3.9
    plan = arm.plan("recover")
    assert not plan["executable"] and "may hold the plate" in plan["blockers"][0]


def test_http_routes(arm):
    client = create_app(arm).test_client()
    assert client.get("/api/state").json["ok"] is True
    reply = client.post("/api/plans", json={"direction": "load", "slot": 1}).json
    assert reply["ok"] and reply["plan"]["summary"] == "Hotel slot 1 → microscope"
    assert client.post("/api/plans", json={"direction": "load", "slot": 3}).status_code == 409
    started = client.post(f"/api/plans/{reply['plan']['id']}/start").json
    assert started["ok"] is True
    arm.wait(30)
    assert client.get("/api/state").json["run"]["ok"] is True
    assert client.post("/api/stop").json["ok"] is True
    assert client.get("/api/state", environ_overrides={"REMOTE_ADDR": "192.168.1.5"}).status_code == 403
