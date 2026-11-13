"""One controller queue, one gripper action, and the checks around them.

The queue speaks the published Lua trajectory protocol 220109 (operator_ui/lua/mod_Trajectory_segment_speeds.lua)
exactly as operator_ui/trajectory_queue.LuaTrajectory does, with its own helpers (handshake, upload in batches of 3,
checksum, commit, execute) and the same watch while the arm moves: the operator's Stop, the controller's health, the
joint limits, and a corridor of 2 mm / 2 degrees around the taught path. On any failure after the upload started, the
controller program is stopped and the move is never sent again. LuaTrajectory itself accepts only the exact point
lists of the old routes, so the joined legs need this executor; the protocol and the checks are the same.

Between moves there is one state read (status and the external axes), not a full record rewrite.
"""
from __future__ import annotations

import math
import secrets
import threading
import time
from collections.abc import Callable

from arm_service import OPERATOR_UI  # noqa: F401
from arm_service.routes import EMPTY_E1, GRIP_E1, KEYS

PROTOCOL = 220109
CORRIDOR_MM = 2.0
CORRIDOR_DEG = 2.0
JOINT_KEYS = ("J1", "J2", "J3", "J4")


class MotionError(RuntimeError):
    """The step did not complete as planned. After motion was sent the controller program was stopped."""


class QueueLost(MotionError):
    """The controller no longer holds a queue that was uploaded earlier. Nothing ran: it can be uploaded again."""


def state(service, expected_e1: float | None = None, *, stationary: bool = True) -> tuple[dict, dict]:
    """One read: controller status (connected, no errors, enabled, Auto, program running) and the external axes."""
    from scope_step_trial import preflight
    from home_hamilton_exchange import native
    from gripper_closure import grip_feedback_matches

    try:
        s = preflight(service)
        n = native(service)
    except Exception as error:  # noqa: BLE001  the console's checks raise their own error types
        raise MotionError(str(error)) from error
    if stationary and n.get("moving"):
        raise MotionError("The arm is still moving.")
    e1 = n["external_axes"].get("E1")
    if not isinstance(e1, (int, float)) or not math.isfinite(e1):
        raise MotionError("The gripper position (E1) is not available.")
    if expected_e1 is not None:
        held = expected_e1 == GRIP_E1
        ok = grip_feedback_matches(e1, GRIP_E1) if held else abs(e1 - expected_e1) <= 0.15
        if not ok:
            raise MotionError(f"The gripper is at {e1:.2f} mm, expected {expected_e1:.2f} mm.")
    return s, n


def near(pose: dict, target: dict, tolerance_mm: float = 0.05, what: str = "the planned position") -> None:
    d = math.dist([pose[k] for k in ("X", "Y", "Z")], [target[k] for k in ("X", "Y", "Z")])
    yaw = abs((pose["Rz"] - target["Rz"] + 180) % 360 - 180)
    if d > tolerance_mm or yaw > 0.5:
        raise MotionError(f"The arm is {d:.2f} mm / {yaw:.2f} degrees away from {what}.")


def check_capability(service) -> None:
    """The controller program offers the trajectory queue 220109 and runs. Read once per run: within a run the
    program only changes by a stop, which ends the run."""
    from trajectory_queue import LuaTrajectory, travel_program_blocker

    capability = LuaTrajectory(service).capability()
    blocker = travel_program_blocker(capability, speed=0)
    if blocker:
        raise MotionError(blocker)
    if capability.get("version") != PROTOCOL:
        raise MotionError(f"The controller program must offer the trajectory queue {PROTOCOL}; nothing moved.")


def _locked(service, fn):
    result = service._locked(fn)
    if isinstance(result, dict) and result.get("ok") is False:  # the motion lock was busy: nothing was sent
        raise MotionError(result.get("error") or "Another motion command is running.")
    return result


def _stop_after(lua, error: Exception) -> MotionError:
    """After the handshake a failure stops the controller program; nothing is sent again."""
    try:
        lua.stop_controller()
    except Exception as stop_error:  # noqa: BLE001
        return MotionError(f"{error}; the controller stop was not confirmed ({stop_error}): use the E-stop")
    return error if isinstance(error, MotionError) else MotionError(str(error))


def upload_queue(service, points: list[dict], speeds: list[float], stopped: Callable[[], bool],
                 capability_checked: bool = False) -> dict:
    """Upload and commit the points, from where the arm stands now. Nothing moves: the queue runs only with
    execute_queue. While the arm stands still, other reads may run meanwhile (the grip's settle check)."""
    from trajectory_queue import LuaTrajectory, checksum

    lua = LuaTrajectory(service)

    def locked():
        if not capability_checked:
            check_capability(service)
        if stopped():
            raise MotionError("Stopped by the operator.")
        start = service.pose_mm()
        joints = service.joints() or {}
        if any(not isinstance(joints.get(k), (int, float)) for k in JOINT_KEYS):
            raise MotionError("Joint feedback is not available; nothing moved.")
        token = secrets.randbelow(1073741823) + 1
        try:
            reply = service.robot.set_sys_var_i({0: 22, 1: 1, 2: 0, 3: 0, 4: 6, 5: 0, 6: 0}, reply_timeout=10)
            if reply != {"index": 1, "value": PROTOCOL}:
                raise MotionError("The controller did not answer the queue handshake; nothing was uploaded.")
            header = [len(points), max(speeds), -1] + [start[k] for k in KEYS] + [joints[k] for k in JOINT_KEYS]
            lua._job(8, token, dict(enumerate(header)))
            for offset in range(0, len(points), 3):
                batch = points[offset:offset + 3]
                values = [v for i, p in enumerate(batch) for v in [p[k] for k in KEYS] + [speeds[offset + i]]]
                lua._job(9, token, dict(enumerate(values)), offset, len(batch))
            lua._job(3, token, offset=checksum(points, speeds))
            if service.robot.get_sys_var_i([7, 17, 18, 19]) != {7: token, 17: PROTOCOL, 18: 2, 19: len(points)}:
                raise MotionError("The controller did not confirm the complete queue; nothing moved.")
        except Exception as error:
            raise _stop_after(lua, error) from error
        return dict(token=token, start=start, joints=joints, points=[dict(p) for p in points], speeds=list(speeds))

    return _locked(service, locked)


def run_queue(service, points: list[dict], speeds: list[float], expected: dict, cfg: dict,
              stopped: Callable[[], bool], started: Callable[[], None], progress: Callable[[float], None],
              capability_checked: bool = False, uploaded: dict | None = None) -> dict:
    """Run the points as one queue: upload them, unless uploaded holds this queue already committed, then run.
    started() is called once, when the arm begins to move. The caller has just read the controller's state
    (state()); the health check is made again before the move, and all the time while the arm moves."""
    if uploaded is not None:
        if uploaded["points"] != points or uploaded["speeds"] != list(speeds):
            raise MotionError("The uploaded queue is not this move; nothing moved.")
        try:
            return execute_queue(service, uploaded, expected, cfg, stopped, started, progress)
        except QueueLost:  # dropped by the controller before it ran (a gripper job in between): upload once more
            pass
    uploaded = upload_queue(service, points, speeds, stopped, capability_checked)
    return execute_queue(service, uploaded, expected, cfg, stopped, started, progress)


def execute_queue(service, uploaded: dict, expected: dict, cfg: dict, stopped: Callable[[], bool],
                  started: Callable[[], None], progress: Callable[[float], None]) -> dict:
    """Run a committed queue: the controller must still hold it, the arm must still stand where it was uploaded."""
    from trajectory_queue import LuaTrajectory, locate
    from autonomy import ensure_arrival

    lua = LuaTrajectory(service)
    token, start, points, speeds = uploaded["token"], uploaded["start"], uploaded["points"], uploaded["speeds"]

    def locked():
        def healthy():
            if stopped():
                raise MotionError("Stopped by the operator.")
            refusal = service._preflight()
            if refusal:
                raise MotionError(refusal)
            q = service.joints() or {}
            if any(not isinstance(q.get(k), (int, float)) or not math.isfinite(q[k]) for k in JOINT_KEYS):
                raise MotionError("Joint feedback is not available.")
            if (abs(q["J2"]) > abs(cfg["j2_min_deg"]) - cfg["j2_margin_deg"]
                    or abs(q["J4"]) > min(cfg["j4_pref_abs_deg"], cfg["j4_hard_abs_deg"] - 5)):
                raise MotionError("The measured joints are past the automatic limits.")

        # Before anything is sent: the controller still holds exactly this committed queue (a gripper job in
        # between did not change it), and the arm stands where the queue was uploaded.
        if service.robot.get_sys_var_i([7, 17, 18, 19]) != {7: token, 17: PROTOCOL, 18: 2, 19: len(points)}:
            raise QueueLost("The controller no longer holds the uploaded queue; nothing moved.")
        q = service.joints() or {}
        if any(abs(q[k] - uploaded["joints"][k]) > 0.5 for k in JOINT_KEYS if k in q):
            raise MotionError("The arm's joints changed after the upload; nothing moved.")
        try:
            healthy()
            ensure_arrival(service.pose_mm(), start)
            done, outcome = threading.Event(), {}
            path = [start] + points
            travel_s = sum(math.dist([a[k] for k in KEYS[:3]], [b[k] for k in KEYS[:3]]) / v
                           for a, b, v in zip(path, path[1:], speeds))
            timeout = 300 + 2 * len(points) + 4 * travel_s

            def execute_job():
                try:
                    lua._job(4, token, timeout=timeout)
                except Exception as error:  # noqa: BLE001
                    outcome["error"] = error
                finally:
                    done.set()

            thread = threading.Thread(target=execute_job, daemon=True, name="arm-queue-reply")
            thread.start()
            started()
            deadline = time.monotonic() + timeout
            while not done.wait(0.1):
                healthy()
                d, yaw, percent = locate(service.pose_mm(), path)
                if d > CORRIDOR_MM or yaw > CORRIDOR_DEG:
                    raise MotionError(f"The arm left the taught path: {d:.2f} mm / {yaw:.2f} degrees.")
                progress(min(percent, 99))
                if time.monotonic() > deadline:
                    raise MotionError("The move took too long; the physical state needs review.")
            if stopped():  # the operator's Stop ended the queue: say so, not the controller's reply to it
                raise MotionError("Stopped by the operator.")
            if "error" in outcome:
                raise MotionError(str(outcome["error"]))
            healthy()
            values = service.robot.get_sys_var_i([7, 17, 18, 19])
            if values != {7: token, 17: PROTOCOL, 18: 4, 19: len(points)}:
                raise MotionError("The controller did not confirm the end of the queue.")
            ensure_arrival(service.pose_mm(), points[-1])
            q = service.joints() or {}
            if any(abs(q[k] - expected[k]) > 0.5 for k in ("J2", "J3", "J4")):
                raise MotionError("The joint configuration at the end differs from the planned one.")
            progress(100)
            return dict(ok=True, points=len(points))
        except Exception as error:
            raise _stop_after(lua, error) from error

    return _locked(service, locked)


def _require(result: dict, what: str) -> dict:
    if not result.get("ok") or result.get("recovered") or result.get("gripper_warning"):
        raise MotionError(f"{what} failed or is uncertain: {result.get('error') or result}")
    return result


def _e1(service) -> float:
    """The gripper only: one read of the external axes (the controller's fault, E-stop and hand-guiding flags come
    with it). Not the full controller status; that is read once at the end of each gripper action."""
    from home_hamilton_exchange import native

    try:
        n = native(service)
    except Exception as error:  # noqa: BLE001
        raise MotionError(str(error)) from error
    e1 = n["external_axes"].get("E1")
    if not isinstance(e1, (int, float)) or not math.isfinite(e1):
        raise MotionError("The gripper position (E1) is not available.")
    return e1


def _still(service, before: dict, what: str) -> None:
    """One full read at the end of a gripper action: the controller is healthy and the arm did not move."""
    s, _ = state(service, None)
    near(s["pose_mm"], before, what=what)


def jaws(service, target: float, speed: float, before: dict, stopped: Callable[[], bool],
         report: bool = True) -> dict | None:
    """One gripper move with the arm still: arrival (3 gripper readings in 2 s), then one full read (healthy, the
    arm did not move) and, with report, a fresh torque report."""
    from gripper_closure import grip_feedback_matches

    closing = command_jaws(service, target, speed, stopped)
    arrived(service, target, closing, before)
    if not report:
        return None
    torque = _require(service.torque_report(), "The torque report")
    matches = (grip_feedback_matches(torque["e1_position"], target) if closing
               else abs(torque["e1_position"] - target) <= 0.07)
    if not torque.get("telemetry_live") or not math.isfinite(torque["e1_torque"]) or not matches:
        raise MotionError("No fresh, settled gripper feedback.")
    return torque


def command_jaws(service, target: float, speed: float, stopped: Callable[[], bool]) -> bool:
    """Send the gripper move; it returns when the controller finished the job. True when closing."""
    if stopped():
        raise MotionError("Stopped by the operator.")
    closing = target < _e1(service)
    _require(service.move_gripper(target, speed), f"The gripper move to {target} mm")
    return closing


def arrived(service, target: float, closing: bool, before: dict, *, readings: int = 3,
            full_read: bool = True) -> None:
    """The jaws at the target (readings stable gripper readings in 2 s), then, with full_read, one full read:
    healthy, the arm did not move. Only reads: it may run while the next queue is uploaded."""
    from gripper_closure import grip_feedback_matches

    deadline, stable = time.monotonic() + 2, 0
    while stable < readings:
        e1 = _e1(service)
        arrived = grip_feedback_matches(e1, target) if closing else abs(e1 - target) <= 0.07
        stable = stable + 1 if arrived else 0
        if time.monotonic() > deadline:
            raise MotionError(f"The gripper did not arrive at {target} mm (it is at {e1:.2f} mm).")
        if stable < readings:
            time.sleep(0.1)
    if full_read:
        _still(service, before, "the gripper position")


def grip(service, before: dict, stopped: Callable[[], bool]) -> dict:
    """Close on the plate with the accepted two-speed closure (to 4.9 mm at 10, the last mm at 5; a torque report
    after the last), then watch the grip settle for 0.5 s (5 gripper readings) and read the full state once: the
    plate must stay held and the arm still."""
    torque = close_on_plate(service, before, stopped)
    settle(service, before)
    return torque


def close_on_plate(service, before: dict, stopped: Callable[[], bool]) -> dict:
    """The two-speed closure and the torque report after it. Between the two closing moves one gripper reading
    (the slow finish starts only from the approach point); after the last, 3 gripper readings and the torque report.
    The full read (healthy, the arm still) comes once, at the end of the settle check (settle)."""
    from gripper_closure import closure_commands, grip_feedback_matches

    commands = closure_commands(EMPTY_E1, GRIP_E1)
    for c in commands[:-1]:
        closing = command_jaws(service, c["target_e1_mm"], c["speed"], stopped)
        arrived(service, c["target_e1_mm"], closing, before, readings=1, full_read=False)
    last = commands[-1]
    closing = command_jaws(service, last["target_e1_mm"], last["speed"], stopped)
    arrived(service, last["target_e1_mm"], closing, before, full_read=False)
    torque = _require(service.torque_report(), "The torque report")
    if (not torque.get("telemetry_live") or not math.isfinite(torque["e1_torque"])
            or not grip_feedback_matches(torque["e1_position"], last["target_e1_mm"])):
        raise MotionError("No fresh, settled gripper feedback.")
    return torque


def settle(service, before: dict) -> None:
    """0.5 s of gripper readings on the plate, then one full read: still held, the arm still. Only reads: it may run
    while the next queue is uploaded."""
    from gripper_closure import grip_feedback_matches

    for _ in range(5):
        if not grip_feedback_matches(_e1(service), GRIP_E1):
            raise MotionError("The grip did not settle on the plate.")
        time.sleep(0.1)
    _still(service, before, "the grip position")


def release(service, before: dict, stopped: Callable[[], bool]) -> None:
    """Open to 7 mm: arrival and one full read. No torque report: an open jaw holds nothing to measure."""
    return jaws(service, EMPTY_E1, 5, before, stopped, report=False)


def squid_ready() -> dict:
    """Squid's own checks: a real stage, idle, the loading reference of this controller, at the loading position."""
    from cellvis24_squid_route import geometry, instrument_ready

    try:
        return dict(position=instrument_ready(geometry()))
    except Exception as error:  # noqa: BLE001
        raise MotionError(f"Squid is not ready for the arm: {error}") from error
