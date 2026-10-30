"""MCP server exposing the Bioyond LabGenius S4 robot arm as tools.

Transport: stdio (registered in the project's .mcp.json).
Protocol to the robot: BRCAPI (Rob INTF v1.1) TCP/JSON on port 56788.

Controller-side contract (the deployed controller/main.bin project, mod_Socket loop):
- SysVarI: 0=DeviceID 1=PosX 2=PosY 3=PosZ 4=MoveType 5=ObjType 6=ClampMode
- Taught jobs: device 3=home, 11/12/13/14/15/9998/9999=stations, 1=stack, 2=scan
- Completion: Lua sends SysOutVar reply {index:1, value:1} on success,
  {index:1, value:-1} for an invalid/unmatched job (mod_EndInvalid)
- Host-point extension (controller/main_hostpoint.bin, device ID 21):
  SysParaF 0=X 1=Y 2=Z 3=Rz(deg) 4=speed 5=blend 6=E1;
  MoveType 1=MoveL 2=MoveJ 3=gripper(E1) 4=MoveAbsJ. Units: mm / degrees.
  (The controller's own pose *query* getFrameWithU0T0 reports meters.)

Safety rules baked in (from the project context pack):
- never auto-enable or auto-clear errors on connect
- motion tools refuse to run unless the robot is in auto mode, enabled, the
  Lua program is running and initialized, and there are no active errors
- Cartesian targets outside the commissioning envelope are refused
- speed is capped; a motion timeout is reported as UNKNOWN STATE and is
  never silently retried
"""

from __future__ import annotations

import functools
import json
import logging
import os
import sys
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from robot import (  # noqa: E402
    DEFAULT_PORT,
    RobotClient,
    RobotError,
    UnknownStateError,
)

logging.basicConfig(level=logging.INFO, stream=sys.stderr)

DEFAULT_IP = os.environ.get("BIOYOND_IP", "192.168.201.220")
MOTION_TIMEOUT = float(os.environ.get("BIOYOND_MOTION_TIMEOUT", "180"))

# linear (MoveL/MoveJ) speed in the deployed Lua is mm/s-scale
# (modules use 200-2000); joint/gripper speed is the MoveAbsJ/MoveExtJ scale
# (modules use 100)
LINEAR_SPEED_DEFAULT = float(os.environ.get("BIOYOND_LINEAR_SPEED", "50"))
LINEAR_SPEED_MAX = float(os.environ.get("BIOYOND_MAX_LINEAR_SPEED", "200"))
JOINT_SPEED_DEFAULT = float(os.environ.get("BIOYOND_JOINT_SPEED", "10"))
JOINT_SPEED_MAX = float(os.environ.get("BIOYOND_MAX_JOINT_SPEED", "30"))

# SysParaF slots used by mod_HostPoint. The live controller only accepts
# setSysParaF for indexes ~0-19 (error 3 above that, despite the docs saying
# 0-49), so the block lives at 0-6 like the vendor convention. The library's
# stack-group loader nominally reads 0-28 but is never called.
PF_X, PF_Y, PF_Z, PF_RZ, PF_SPEED, PF_BLEND, PF_E1 = 0, 1, 2, 3, 4, 5, 6

HOSTPOINT_DEVICE = 21
MOVETYPE_LINEAR = 1
MOVETYPE_JOINT = 2
MOVETYPE_GRIPPER = 3
MOVETYPE_ABSJ = 4
MOVETYPE_GRIP_REPORT = 5   # no motion, just refresh SysVarI 10-12
MOVETYPE_GRIP_FORCE = 6    # force-limited E1 move (force in blend slot)

# after gripper moves/reports the Lua writes E1 status x1000 here
VAR_E1_POS, VAR_E1_TRQ, VAR_E1_NORMTRQ = 10, 11, 12

# Grip-detection thresholds calibrated on the real gripper (2026-07-19):
# free-motion torque baseline is POSITIVE (+150..+195); pressing an object
# swings it negative, saturating at ~-187 (motor limit); the reported E1
# position stalls at the object width (measured 23.34 for the test object)
# while the command keeps decreasing.
GRIP_TORQUE_THRESHOLD = float(os.environ.get("BIOYOND_GRIP_TRQ", "-100"))
GRIP_POS_ERROR = float(os.environ.get("BIOYOND_GRIP_POSERR", "0.15"))

# Temporary commissioning workspace: Cartesian targets outside this box are
# refused. Adjustable at runtime via set_workspace_envelope.
ENVELOPE = {
    "X": (float(os.environ.get("BIOYOND_X_MIN", "200")),
          float(os.environ.get("BIOYOND_X_MAX", "450"))),
    "Y": (float(os.environ.get("BIOYOND_Y_MIN", "-250")),
          float(os.environ.get("BIOYOND_Y_MAX", "50"))),
    "Z": (float(os.environ.get("BIOYOND_Z_MIN", "350")),
          float(os.environ.get("BIOYOND_Z_MAX", "400"))),
}

mcp = FastMCP(
    "bioyond-s4",
    instructions=(
        "Controls a Bioyond LabGenius S4 4-axis lab robot (J1-J4, E1 gripper, "
        "E2 rotator) over the BRCAPI TCP protocol. Call connect first, then "
        "get_status. Motion needs auto mode + enabled + Lua program running, "
        "and host Cartesian moves need the controller/main_hostpoint.bin program "
        "published on the controller. This is physical machinery: keep speeds "
        "low, never retry a timed-out motion without re-checking state, and "
        "leave error clearing / enabling to operator-confirmed calls."
    ),
)

robot = RobotClient()


def _fail(message: str) -> dict:
    return {"ok": False, "error": message}


def _guard(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except RobotError as ex:
            return _fail(f"{type(ex).__name__}: {ex}")
        except (OSError, ValueError, KeyError, TypeError) as ex:
            return _fail(f"{type(ex).__name__}: {ex}")

    return wrapper


import math


def _pose_mm() -> dict:
    """Controller pose (meters/radians) -> mm/degrees, the units every
    motion tool takes. VERIFIED live: getFrameWithU0T0 returns Rz in
    RADIANS while RobTarget/MoveL takes DEGREES."""
    raw = robot.get_cartesian_pose()
    out = {}
    for k, v in raw.items():
        if k in ("X", "Y", "Z"):
            out[k] = round(v * 1000.0, 3)
        else:
            out[k] = round(math.degrees(v), 3)
    return out


def _status_snapshot() -> dict:
    return {
        "connected": True,
        "endpoint": robot.endpoint,
        "system_state": robot.get_sys_state(),
        "control_mode": robot.get_ctrl_mode(),
        "enabled": robot.get_enable_status(),
        "program_state": robot.get_prog_state(),
        "lua_app_initialized": robot.get_lua_app_status(),
        "errors": robot.get_robot_errors(),
    }


def _motion_preflight() -> Optional[str]:
    if not robot.connected:
        return "not connected — call connect first"
    errors = robot.get_robot_errors()
    if errors:
        return (
            "robot has active errors, refusing to move: "
            + json.dumps(errors)
            + " — resolve the cause, then use clear_errors (operator-confirmed)"
        )
    mode = robot.get_ctrl_mode()
    if mode["mode"] != "auto":
        return "robot is in manual mode — call switch_mode('auto') first"
    if not robot.get_enable_status():
        return "robot is disabled — call enable_robot first (operator-confirmed)"
    prog = robot.get_prog_state()
    if prog["state"] != "running":
        return f"Lua program state is '{prog['state']}' — call start_program first"
    if not robot.get_lua_app_status():
        return "Lua application reports uninitialized — wait or restart the program"
    return None


def _check_envelope(x: float, y: float, z: float) -> Optional[str]:
    violations = []
    for axis, val in (("X", x), ("Y", y), ("Z", z)):
        lo, hi = ENVELOPE[axis]
        if not (lo <= val <= hi):
            violations.append(f"{axis}={val} outside [{lo}, {hi}]")
    if violations:
        return (
            "target outside the safe commissioning envelope, refusing to move: "
            + "; ".join(violations)
            + ". Allowed box: "
            + ", ".join(f"{a} {lo}..{hi}" for a, (lo, hi) in ENVELOPE.items())
            + ". The operator can adjust it with set_workspace_envelope."
        )
    return None


def _run_job(sys_vars: dict[int, int], wait_timeout: float) -> dict:
    """Trigger a controller-side job via SysVarI and wait for the Lua reply.

    Returns the reply plus post-motion pose/joints. Reply value 1 = done,
    -1 = the running program rejected the job as invalid/unsupported.
    """
    reply = robot.set_sys_var_i(sys_vars, reply_timeout=wait_timeout)
    result: dict[str, Any] = {"ok": True, "completion_reply": reply}
    if isinstance(reply, dict) and reply.get("value") == -1:
        dev = sys_vars.get(0)
        msg = "controller program rejected the job as invalid (SysOutVar=-1)"
        if dev == HOSTPOINT_DEVICE:
            msg += (
                " — the loaded program has no host-point support; publish "
                "controller/main_hostpoint.bin via Bioyond Works to enable Cartesian moves"
            )
        return _fail(msg)
    try:
        result["pose_after_mm"] = _pose_mm()
        result["joints_after"] = robot.get_joint_info()
    except RobotError:
        pass
    return result


def _hostpoint_move(
    para_f: dict[int, float], move_type: int, wait_timeout: float
) -> dict:
    refusal = _motion_preflight()
    if refusal:
        return _fail(refusal)
    robot.set_sys_para_f(para_f)
    try:
        return _run_job(
            {0: HOSTPOINT_DEVICE, 1: 1, 4: move_type}, wait_timeout
        )
    except UnknownStateError as ex:
        # Distinguish "job never consumed" from "still executing / link lost"
        note = ""
        try:
            if robot.connected:
                v = robot.get_sys_var_i([0, 1, 4])
                if v.get(0) == HOSTPOINT_DEVICE:
                    robot.request(
                        "setSysVarI",
                        [{"index": i, "value": 0} for i in (0, 1, 2, 3, 4, 5, 6)],
                    )
                    return _fail(
                        "the running Lua program never consumed the host-point "
                        "job (trigger cleared; no motion occurred). Publish "
                        "controller/main_hostpoint.bin via Bioyond Works, restart the "
                        "program, and retry."
                    )
                note = " Trigger was consumed — the robot may be moving."
        except RobotError:
            note = " Could not re-query state."
        return _fail(f"{ex}{note} Re-query get_status/get_cartesian_pose before retrying.")


# --------------------------------------------------------------- connection


@mcp.tool()
@_guard
def connect(ip: str = "", port: int = DEFAULT_PORT) -> dict:
    """Connect to the S4 robot controller over TCP.

    Args:
        ip: Controller IP. Empty string uses the configured default
            (192.168.201.220 for this deployment).
        port: BRCAPI port, fixed at 56788 on Bioyond controllers.

    Connecting performs NO motion, no enabling and no error clearing.
    Note the controller accepts only ONE raw TCP client at a time.
    """
    robot.connect(ip or DEFAULT_IP, port)
    try:
        return {"ok": True, **_status_snapshot()}
    except RobotError as ex:
        return {
            "ok": True,
            "connected": True,
            "endpoint": robot.endpoint,
            "warning": f"connected but status query failed: {ex} "
            "(controller may still be initializing — try get_status)",
        }


@mcp.tool()
@_guard
def disconnect() -> dict:
    """Close the TCP connection to the robot controller."""
    robot.disconnect()
    return {"ok": True, "connected": False}


@mcp.tool()
@_guard
def get_status() -> dict:
    """Full robot status: system state, control mode, enable, program state,
    Lua initialization flag, and any active robot errors."""
    if not robot.connected:
        return _fail("not connected — call connect first")
    return {"ok": True, **_status_snapshot()}


# ------------------------------------------------------------------ queries


@mcp.tool()
@_guard
def get_cartesian_pose() -> dict:
    """Current Cartesian tool pose in the T0/U0 frame. Returns pose_mm
    (X/Y/Z in mm) and rotation_deg (Rx/Ry/Rz in DEGREES) — exactly the
    units all motion tools take. The controller's raw values (meters /
    RADIANS — verified live) are included for reference; never feed raw
    Rz back into a move command."""
    raw = robot.get_cartesian_pose()
    return {
        "ok": True,
        "pose_mm": {k: round(v * 1000.0, 3) for k, v in raw.items() if k in ("X", "Y", "Z")},
        "rotation_deg": {k: round(math.degrees(v), 3) for k, v in raw.items() if k in ("Rx", "Ry", "Rz")},
        "pose_raw": raw,
        "frame": "T0/U0",
    }


@mcp.tool()
@_guard
def get_joint_positions() -> dict:
    """Current joint positions J1-J4 plus any reported external axes.
    (On this cell E1=gripper and E2=rotator live on axes 7-8 of the Lua
    JointTarget, but the controller currently reports no external axes via
    getJointInfo.)"""
    return {"ok": True, **robot.get_joint_info()}


@mcp.tool()
@_guard
def get_robot_errors() -> dict:
    """Read active robot errors (code + message). Empty list = no errors.
    Known critical codes: 3611/3608 emergency stop, 3873 collision."""
    return {"ok": True, "errors": robot.get_robot_errors()}


@mcp.tool()
@_guard
def read_system_values(
    var_i_indexes: list[int] = [],
    para_i_indexes: list[int] = [],
    para_f_indexes: list[int] = [],
) -> dict:
    """Read controller system variables/parameters (debugging).

    Args:
        var_i_indexes: integer system VARIABLE indexes (0-19) — the job
            trigger variables (0=device 1-3=pos 4=movetype 5=obj 6=clamp).
        para_i_indexes: integer system PARAMETER indexes (0-49).
        para_f_indexes: float system PARAMETER indexes (writable ~0-19 on
            this controller); 0-6 are the host-point target slots
            (X,Y,Z,Rz,speed,blend,E1).
    """
    out: dict[str, Any] = {"ok": True}
    if var_i_indexes:
        out["sys_var_i"] = robot.get_sys_var_i(var_i_indexes)
    if para_i_indexes:
        out["sys_para_i"] = robot.get_sys_para_i(para_i_indexes)
    if para_f_indexes:
        out["sys_para_f"] = robot.get_sys_para_f(para_f_indexes)
    return out


# ------------------------------------------------------------------ control


@mcp.tool()
@_guard
def switch_mode(mode: str) -> dict:
    """Switch robot control mode.

    Args:
        mode: 'auto' (required for remote enable/motion) or 'manual'
            (pendant jogging, lower speed).
    """
    mode = mode.strip().lower()
    if mode not in ("auto", "manual"):
        return _fail("mode must be 'auto' or 'manual'")
    reply = robot.switch_mode(auto=(mode == "auto"))
    return {"ok": reply == "CmdDone", "reply": reply, "mode": mode}


@mcp.tool()
@_guard
def enable_robot(operator_confirmed: bool = False) -> dict:
    """Enable robot servo power so it can move. Requires auto mode.

    Args:
        operator_confirmed: must be true, confirming a human has verified
            the cell is clear and the E-stop is within reach.
    """
    if not operator_confirmed:
        return _fail(
            "refused: enabling makes the arm able to move. Confirm with the "
            "operator that the cell is clear and the E-stop is reachable, "
            "then call again with operator_confirmed=true"
        )
    reply = robot.set_enable(True)
    return {"ok": reply == "CmdDone", "reply": reply}


@mcp.tool()
@_guard
def disable_robot() -> dict:
    """Disable robot servo power (safe to approach). Never blocked."""
    reply = robot.set_enable(False)
    return {"ok": reply == "CmdDone", "reply": reply}


@mcp.tool()
@_guard
def clear_errors(operator_confirmed: bool = False) -> dict:
    """Clear robot controller errors.

    Args:
        operator_confirmed: must be true. Errors are cleared only after a
            human has understood the cause and confirmed it is resolved.
    """
    if not operator_confirmed:
        errors = robot.get_robot_errors() if robot.connected else []
        return _fail(
            "refused: clearing errors requires operator confirmation. "
            f"Active errors: {json.dumps(errors)}. Call again with "
            "operator_confirmed=true once the cause is resolved."
        )
    reply = robot.clear_errors()
    return {"ok": reply == "CmdDone", "reply": reply}


@mcp.tool()
@_guard
def start_program() -> dict:
    """Start (or resume) the controller Lua program — required before any
    motion/job tool. Program start itself commands no motion in the deployed
    project, but treat it as arming the system."""
    reply = robot.prog_start()
    return {
        "ok": reply == "CmdDone",
        "reply": reply,
        "lua_app_initialized": robot.get_lua_app_status(),
    }


@mcp.tool()
@_guard
def pause_program() -> dict:
    """Pause the controller Lua program at the current statement."""
    reply = robot.prog_pause()
    return {"ok": reply == "CmdDone", "reply": reply}


@mcp.tool()
@_guard
def stop_program() -> dict:
    """Stop the controller Lua program (pointer returns to main())."""
    reply = robot.prog_stop()
    return {"ok": reply == "CmdDone", "reply": reply}


@mcp.tool()
@_guard
def move_backwards(operator_confirmed: bool = False) -> dict:
    """Fault recovery: retrace the robot backwards along its recent path.
    Only valid when the Lua program is NOT running and the robot is idle.

    Args:
        operator_confirmed: must be true — a human must watch this motion.
    """
    if not operator_confirmed:
        return _fail(
            "refused: move-backwards is a recovery motion and must be "
            "supervised. Call again with operator_confirmed=true."
        )
    reply = robot.move_backwards()
    return {"ok": reply == "CmdDone", "reply": reply}


@mcp.tool()
@_guard
def stop_move_backwards() -> dict:
    """Stop an in-progress move-backwards recovery motion."""
    reply = robot.stop_move_backwards()
    return {"ok": reply == "CmdDone", "reply": reply}


@mcp.tool()
@_guard
def set_workspace_envelope(
    x_min: float, x_max: float,
    y_min: float, y_max: float,
    z_min: float, z_max: float,
    operator_confirmed: bool = False,
) -> dict:
    """Adjust the safe Cartesian envelope (mm, T0/U0) that motion targets are
    checked against. Operator confirmation required — widening this box is a
    safety decision.

    Args:
        x_min: lower X bound in mm.
        x_max: upper X bound in mm.
        y_min: lower Y bound in mm.
        y_max: upper Y bound in mm.
        z_min: lower Z bound in mm.
        z_max: upper Z bound in mm.
        operator_confirmed: must be true.
    """
    if not operator_confirmed:
        return _fail(
            "refused: changing the safety envelope requires "
            "operator_confirmed=true. Current box: "
            + ", ".join(f"{a} {lo}..{hi}" for a, (lo, hi) in ENVELOPE.items())
        )
    if not (x_min < x_max and y_min < y_max and z_min < z_max):
        return _fail("each min must be strictly less than its max")
    ENVELOPE["X"] = (x_min, x_max)
    ENVELOPE["Y"] = (y_min, y_max)
    ENVELOPE["Z"] = (z_min, z_max)
    return {"ok": True, "envelope": {k: list(v) for k, v in ENVELOPE.items()}}


# ------------------------------------------------------------------- motion
# (host-point interface — needs controller/main_hostpoint.bin on the controller)


@mcp.tool()
@_guard
def move_to_cartesian(
    x: float,
    y: float,
    z: float,
    rz: float,
    speed: float = 0,
    interpolation: str = "linear",
    wait_timeout: float = MOTION_TIMEOUT,
) -> dict:
    """Move the tool to a Cartesian target and wait for completion.
    Requires controller/main_hostpoint.bin published on the controller (a stock program
    rejects the job with no motion).

    Args:
        x: target X in mm (T0/U0 frame).
        y: target Y in mm.
        z: target Z in mm.
        rz: target Rz in degrees (the only commandable rotation on this
            4-axis arm; Rx/Ry are fixed at 0).
        speed: linear speed (Lua MoveL scale, ~mm/s; deployed modules use
            200-2000). 0 uses the default (50); capped at 200.
        interpolation: 'linear' (MoveL, straight line) or 'joint' (MoveJ,
            joint-interpolated path to the same target).
        wait_timeout: seconds to wait for motion completion.

    Read get_cartesian_pose first and command small, deliberate steps.
    Targets outside the safe envelope are refused. E1/E2 are held.
    """
    interpolation = interpolation.strip().lower()
    if interpolation not in ("linear", "joint"):
        return _fail("interpolation must be 'linear' or 'joint'")
    violation = _check_envelope(x, y, z)
    if violation:
        return _fail(violation)
    spd = min(speed, LINEAR_SPEED_MAX) if speed > 0 else LINEAR_SPEED_DEFAULT
    mtype = MOVETYPE_LINEAR if interpolation == "linear" else MOVETYPE_JOINT
    res = _hostpoint_move(
        {PF_X: x, PF_Y: y, PF_Z: z, PF_RZ: rz, PF_SPEED: spd, PF_BLEND: -1.0,
         PF_E1: 0.0},
        mtype,
        wait_timeout,
    )
    res.setdefault("commanded", {"x": x, "y": y, "z": z, "rz": rz,
                                 "speed": spd, "interpolation": interpolation})
    return res


@mcp.tool()
@_guard
def move_joints(
    j1: float,
    j2: float,
    j3: float,
    j4: float,
    speed: float = 0,
    operator_confirmed: bool = False,
    wait_timeout: float = MOTION_TIMEOUT,
) -> dict:
    """Move to absolute joint targets J1-J4 (MoveAbsJ). Requires
    controller/main_hostpoint.bin on the controller.

    Args:
        j1: target J1.
        j2: target J2.
        j3: target J3.
        j4: target J4.
        speed: joint speed (MoveAbsJ scale; deployed modules use 100).
            0 uses the default (10); capped at 30.
        operator_confirmed: must be true — joint-space targets bypass the
            Cartesian envelope check, so a human must confirm the target is
            collision-free. Prefer move_to_cartesian.
        wait_timeout: seconds to wait for completion.
    """
    if not operator_confirmed:
        return _fail(
            "refused: joint-space moves bypass the safe Cartesian envelope. "
            "Prefer move_to_cartesian; otherwise have the operator confirm "
            "the target and call again with operator_confirmed=true."
        )
    spd = min(speed, JOINT_SPEED_MAX) if speed > 0 else JOINT_SPEED_DEFAULT
    res = _hostpoint_move(
        {PF_X: j1, PF_Y: j2, PF_Z: j3, PF_RZ: j4, PF_SPEED: spd,
         PF_BLEND: -1.0, PF_E1: 0.0},
        MOVETYPE_ABSJ,
        wait_timeout,
    )
    res.setdefault("commanded", {"j1": j1, "j2": j2, "j3": j3, "j4": j4,
                                 "speed": spd})
    return res


def _read_gripper_report() -> dict:
    """Read the E1 status block the Lua writes after gripper moves/reports."""
    v = robot.get_sys_var_i([VAR_E1_POS, VAR_E1_TRQ, VAR_E1_NORMTRQ])
    return {
        "e1_position": v[VAR_E1_POS] / 1000.0,
        "e1_torque": v[VAR_E1_TRQ] / 1000.0,
        "e1_torque_normalized": v[VAR_E1_NORMTRQ] / 1000.0,
    }


@mcp.tool()
@_guard
def move_gripper(
    e1_position: float,
    speed: float = 0,
    wait_timeout: float = MOTION_TIMEOUT,
) -> dict:
    """Move the E1 gripper axis while the arm stays still (MoveExtJ), then
    report the E1 position and torque measured AFTER the move — use the
    torque signal to detect contact/grip (rises sharply when the fingers
    close on an object). Requires controller/main_hostpoint.bin on the controller.

    Args:
        e1_position: target E1 position (28 = fully open on this gripper;
            smaller = closing; contact torque appears at the object width).
        speed: external-axis speed (MoveExtJ scale; modules use 100).
            0 uses the default (10); capped at 30.
        wait_timeout: seconds to wait for completion.
    """
    spd = min(speed, JOINT_SPEED_MAX) if speed > 0 else JOINT_SPEED_DEFAULT
    res = _hostpoint_move(
        {PF_SPEED: spd, PF_BLEND: -1.0, PF_E1: e1_position},
        MOVETYPE_GRIPPER,
        wait_timeout,
    )
    res.setdefault("commanded", {"e1": e1_position, "speed": spd})
    if res.get("ok"):
        try:
            g = _read_gripper_report()
            g["position_error"] = round(g["e1_position"] - e1_position, 3)
            g["grip_detected"] = (
                g["position_error"] > GRIP_POS_ERROR
                and g["e1_torque"] < GRIP_TORQUE_THRESHOLD
            )
            res["gripper"] = g
        except RobotError as ex:
            res["gripper_warning"] = str(ex)
    return res


@mcp.tool()
@_guard
def gripper_status(wait_timeout: float = 30.0) -> dict:
    """Read the E1 gripper's current position and torque WITHOUT moving
    anything (triggers the Lua report job, then reads it back). Torque is a
    controller/motor signal, not calibrated newtons — interpret it relative
    to the free-motion baseline.

    Args:
        wait_timeout: seconds to wait for the report job.
    """
    refusal = _motion_preflight()
    if refusal:
        return _fail(refusal)
    res = _run_job({0: HOSTPOINT_DEVICE, 1: 1, 4: MOVETYPE_GRIP_REPORT},
                   wait_timeout)
    if not res.get("ok"):
        return res
    return {"ok": True, **_read_gripper_report()}


@mcp.tool()
@_guard
def grip_by_torque(
    torque_threshold: float = -100.0,
    start: float = 28.0,
    step: float = 0.1,
    floor: float = 20.0,
    coarse_step: float = 0.0,
    fine_from: float = 0.0,
    speed: float = 0,
    step_timeout: float = 30.0,
) -> dict:
    """Adaptive torque-based grip: open E1 to `start`, then close in small
    steps, reading torque after each, and STOP as soon as torque falls to
    the threshold — no prior knowledge of the object width needed.

    Free-motion torque on this gripper is +150..+195; pressing an object
    drives it negative (saturation ≈ -187). The default threshold of -100
    stops at a firm but not saturated grip.

    Args:
        torque_threshold: stop when reported torque <= this (default -100).
        start: opening position to start from (28 = fully open).
        step: fine closing step (default 0.1).
        floor: minimum E1 to try; if reached with no grip, the gripper
            REOPENS to `start` and the tool reports failure.
        coarse_step: optional larger step to use before `fine_from`, to
            speed up the free-air part of the close (0 = fine steps all
            the way).
        fine_from: E1 value below which stepping switches from coarse_step
            to step (only used when coarse_step > 0).
        speed: per-step E1 speed; 0 = default (10); capped at 30.
        step_timeout: seconds to wait for each step's completion.

    On success the object stays gripped; result includes the full
    E1-vs-torque log, the grip position, and grip_detected.
    """
    if step <= 0 or start <= floor:
        return _fail("need step > 0 and start > floor")
    refusal = _motion_preflight()
    if refusal:
        return _fail(refusal)
    spd = min(speed, JOINT_SPEED_MAX) if speed > 0 else JOINT_SPEED_DEFAULT

    def _step_to(target: float) -> dict:
        res = _hostpoint_move(
            {PF_SPEED: spd, PF_BLEND: -1.0, PF_E1: target},
            MOVETYPE_GRIPPER,
            step_timeout,
        )
        if not res.get("ok"):
            raise RobotError(f"gripper step to {target:.2f} failed: {res.get('error')}")
        g = _read_gripper_report()
        g["commanded"] = round(target, 3)
        g["position_error"] = round(g["e1_position"] - target, 3)
        return g

    log = []
    g = _step_to(start)
    log.append(g)
    target = start
    while target - step >= floor - 1e-9:
        if coarse_step > step and target - coarse_step > max(fine_from, floor):
            target = round(target - coarse_step, 3)
        else:
            target = round(target - step, 3)
        g = _step_to(target)
        log.append(g)
        if g["e1_torque"] <= torque_threshold:
            g["grip_detected"] = (
                g["position_error"] > GRIP_POS_ERROR
                and g["e1_torque"] < GRIP_TORQUE_THRESHOLD
            )
            return {
                "ok": True,
                "gripped": True,
                "stopped_at_command": target,
                "grip_position": g["e1_position"],
                "grip_torque": g["e1_torque"],
                "grip_detected": g["grip_detected"],
                "steps": len(log) - 1,
                "log": log,
            }
    # floor reached without torque crossing: nothing gripped — reopen
    reopen = _hostpoint_move(
        {PF_SPEED: spd, PF_BLEND: -1.0, PF_E1: start},
        MOVETYPE_GRIPPER,
        step_timeout,
    )
    return {
        "ok": False,
        "gripped": False,
        "error": (
            f"no torque crossing of {torque_threshold} down to floor "
            f"{floor} — no object between the fingers? Gripper reopened to "
            f"{start} (reopen ok={reopen.get('ok')})"
        ),
        "log": log,
    }


@mcp.tool()
@_guard
def grip_with_force_limit(
    e1_position: float,
    force_limit: float,
    speed: float = 0,
    wait_timeout: float = MOTION_TIMEOUT,
) -> dict:
    """Close/move the E1 gripper with a FORCE-LIMITED motion
    (MoveExtJWithForce): the axis stops advancing when the force/torque
    limit is reached, so it grips without crushing. Calibrate the limit
    value against torque readings from move_gripper steps first — units are
    the controller's own torque scale, not newtons.

    Args:
        e1_position: target E1 position (command past the object width so
            the force limit, not the position, ends the close).
        force_limit: force/torque cap on the motion.
        speed: external-axis speed; 0 = default (10); capped at 30.
        wait_timeout: seconds to wait for completion.
    """
    spd = min(speed, JOINT_SPEED_MAX) if speed > 0 else JOINT_SPEED_DEFAULT
    res = _hostpoint_move(
        {PF_SPEED: spd, PF_BLEND: float(force_limit), PF_E1: e1_position},
        MOVETYPE_GRIP_FORCE,
        wait_timeout,
    )
    res.setdefault("commanded", {"e1": e1_position, "force_limit": force_limit,
                                 "speed": spd})
    if res.get("ok"):
        try:
            g = _read_gripper_report()
            g["position_error"] = round(g["e1_position"] - e1_position, 3)
            g["grip_detected"] = (
                g["position_error"] > GRIP_POS_ERROR
                and g["e1_torque"] < GRIP_TORQUE_THRESHOLD
            )
            res["gripper"] = g
        except RobotError as ex:
            res["gripper_warning"] = str(ex)
    return res


# ---------------------------------------------------- taught controller jobs


@mcp.tool()
@_guard
def go_home(
    home_point: int = 1,
    operator_confirmed: bool = False,
    wait_timeout: float = MOTION_TIMEOUT,
) -> dict:
    """Run the controller's taught homing job (device ID 3). This is a LARGE
    joint move at the program's own speed (VAR1=100) — not adjustable from
    the host.

    Args:
        home_point: 1 = taught point (66.75, 8.38, 105.69, 0);
            any other value = (250, 0, 0, 0).
        operator_confirmed: must be true — a human must confirm the path to
            home is clear and watch the motion.
        wait_timeout: seconds to wait for completion.
    """
    if not operator_confirmed:
        return _fail(
            "refused: homing is a large fast taught motion. Confirm the "
            "path is clear and call again with operator_confirmed=true."
        )
    refusal = _motion_preflight()
    if refusal:
        return _fail(refusal)
    return _run_job({0: 3, 1: 1 if home_point == 1 else 2}, wait_timeout)


@mcp.tool()
@_guard
def run_station_job(
    device_id: int,
    action: str,
    obj_type: int = 3,
    clamp_mode: int = 0,
    operator_confirmed: bool = False,
    wait_timeout: float = MOTION_TIMEOUT,
) -> dict:
    """Run a taught pick/place job at a station of the deployed program.
    These are full taught sequences (safe point -> approach -> grip/release
    -> retreat) at the program's own speeds.

    Args:
        device_id: station device ID — 11 (P1), 12 (Squid), 13 (Scale),
            14 (FluidicsSystem), 15 (Lid table), 9998, 9999.
        action: 'pick' or 'place'.
        obj_type: object type as taught (deployed jobs accept 3, some also 5).
        clamp_mode: SysVarI 6; non-zero/non-11/non-12 triggers the rotate
            module for device-11-style jobs. Leave 0 unless you know the
            taught behavior.
        operator_confirmed: must be true — taught sequences move fast and
            far; a human must watch.
        wait_timeout: seconds to wait for completion.
    """
    if not operator_confirmed:
        return _fail(
            "refused: station jobs are large taught motions. Call again "
            "with operator_confirmed=true with a human watching."
        )
    action = action.strip().lower()
    if action not in ("pick", "place"):
        return _fail("action must be 'pick' or 'place'")
    if device_id not in (11, 12, 13, 14, 15, 9998, 9999):
        return _fail("device_id must be one of 11, 12, 13, 14, 15, 9998, 9999")
    refusal = _motion_preflight()
    if refusal:
        return _fail(refusal)
    return _run_job(
        {0: device_id, 1: 1, 2: 1, 3: 1,
         4: 1 if action == "pick" else 2, 5: obj_type, 6: clamp_mode},
        wait_timeout,
    )


@mcp.tool()
@_guard
def run_lua_job(
    sys_var_values: dict[str, int],
    operator_confirmed: bool = False,
    wait_timeout: float = MOTION_TIMEOUT,
) -> dict:
    """Advanced: write raw integer system variables to trigger any job in
    the controller Lua program and wait for its completion reply. Only use
    var patterns that actually exist in the deployed program (e.g. stack
    jobs: {0:1, 1:col 1-5, 2:level 1-3, ...}; scan: {0:2}).

    Args:
        sys_var_values: map of SysVarI index (string) to value, written in
            one frame.
        operator_confirmed: must be true.
        wait_timeout: seconds to wait for the completion reply.
    """
    if not operator_confirmed:
        return _fail("refused: raw job triggers require operator_confirmed=true")
    refusal = _motion_preflight()
    if refusal:
        return _fail(refusal)
    values = {int(k): int(v) for k, v in sys_var_values.items()}
    return _run_job(values, wait_timeout)


# ------------------------------------------------------------------- vision
# Arducam B0478 USB camera. These tools only CAPTURE — object detection is
# done by the agent itself by viewing the returned images (per operator
# preference, no local CV detection). Grid overlays let the agent read
# pixel coordinates directly off the image.

import vision  # noqa: E402

camera = vision.Camera(0)    # first Arducam in enumeration order
camera2 = vision.Camera(1)   # second Arducam (identical name, ordinal 1)
CAPTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")
os.makedirs(CAPTURE_DIR, exist_ok=True)
_capture_counter = 0
_last_frames: dict[int, Any] = {}  # per-camera last raw frame for inspect


def _usb_capture(cam: "vision.Camera", grid: bool, label: str) -> dict:
    try:
        frame = cam.capture()
    except vision.CameraError as ex:
        return _fail(str(ex))
    _last_frames[cam.ordinal] = frame
    img = vision.draw_grid(frame) if grid else frame
    path = _save_capture(img, f"{label}_{'grid' if grid else 'raw'}")
    h, w = frame.shape[:2]
    return {
        "ok": True,
        "image_path": path,
        "width": w,
        "height": h,
        "image_center_px": [w // 2, h // 2],
        "mean_brightness": round(float(frame.mean()), 1),
        "hint": "Read image_path and locate the target visually; grid labels are pixel coordinates",
    }


def _usb_inspect(cam: "vision.Camera", cx: int, cy: int, size: int,
                 fresh: bool, label: str) -> dict:
    if fresh or cam.ordinal not in _last_frames:
        try:
            _last_frames[cam.ordinal] = cam.capture()
        except vision.CameraError as ex:
            return _fail(str(ex))
    img, (x0, y0) = vision.crop_zoom(_last_frames[cam.ordinal], int(cx),
                                     int(cy), int(size))
    path = _save_capture(img, f"{label}_zoom_{cx}_{cy}")
    return {
        "ok": True,
        "image_path": path,
        "crop_origin_px": [x0, y0],
        "crop_size": size,
        "zoom": 3,
        "requested_point": [cx, cy],
        "hint": "grid labels are full-frame pixel coordinates; red cross = your requested point",
    }


def _save_capture(frame, suffix: str) -> str:
    global _capture_counter
    _capture_counter += 1
    import cv2
    path = os.path.join(CAPTURE_DIR, f"cap{_capture_counter:04d}_{suffix}.jpg")
    cv2.imwrite(path, frame)
    return path


@mcp.tool()
@_guard
def camera_capture(grid: bool = True) -> dict:
    """Capture a fresh frame from the Arducam and save it as a JPEG.
    READ the returned image path to see the scene — locate objects with
    your own vision; there is no local detection.

    Args:
        grid: overlay a labeled pixel-coordinate grid (every 100 px, cyan
            lines, white cross at image center) so you can read off the
            pixel position of anything you see. Set false for a clean image.

    Pixel convention: origin top-left, x grows right, y grows down,
    frame is 1920x1080. After spotting a target, call
    camera_inspect_region(cx, cy) to zoom in and refine your estimate.
    First call takes a few seconds (camera warm-up)."""
    return _usb_capture(camera, grid, "cam1")


@mcp.tool()
@_guard
def camera_inspect_region(
    center_x: int,
    center_y: int,
    size: int = 300,
    fresh: bool = False,
) -> dict:
    """Zoom into a region of the camera view to refine a pixel-coordinate
    estimate. Returns a crop around (center_x, center_y), upscaled 3x, with
    a fine grid every 20 px labeled in FULL-FRAME coordinates and a red
    cross at the point you asked about. READ the image to verify/refine.

    Args:
        center_x: full-frame x of the region of interest.
        center_y: full-frame y of the region of interest.
        size: square crop side in px (default 300).
        fresh: true = capture a new frame first; false = reuse the frame
            from the last camera_capture (default, so coordinates stay
            consistent while you refine).
    """
    return _usb_inspect(camera, center_x, center_y, size, fresh, "cam1")


@mcp.tool()
@_guard
def camera_release() -> dict:
    """Release the first Arducam so other applications can use it."""
    camera.release()
    return {"ok": True, "released": True}


@mcp.tool()
@_guard
def camera2_capture(grid: bool = True) -> dict:
    """Capture a fresh frame from the SECOND Arducam (same model, ordinal 1
    in device enumeration) with the same labeled coordinate grid. READ the
    returned path and locate objects with your own vision.

    NOTE: the two Arducams have identical device names — which physical
    camera is 'second' follows USB enumeration order and can swap after
    reboots/replugs; verify by the scene content."""
    return _usb_capture(camera2, grid, "cam2")


@mcp.tool()
@_guard
def camera2_inspect_region(
    center_x: int,
    center_y: int,
    size: int = 300,
    fresh: bool = False,
) -> dict:
    """Zoom into a region of the SECOND Arducam's view (3x, fine grid in
    full-frame coordinates, red cross at the requested point).

    Args:
        center_x: full-frame x of the region of interest.
        center_y: full-frame y of the region of interest.
        size: square crop side in px (default 300).
        fresh: true = capture a new frame first; false = reuse the last
            camera2_capture frame.
    """
    return _usb_inspect(camera2, center_x, center_y, size, fresh, "cam2")


@mcp.tool()
@_guard
def camera2_release() -> dict:
    """Release the second Arducam so other applications can use it."""
    camera2.release()
    return {"ok": True, "released": True}


# --------------------------------------------------------- GigE camera (MVS)
# Second camera: HIKROBOT-style GigE Vision camera (JHEM600GM-HM, mono,
# 3072x2048) on the robot's Ethernet segment, normally viewed in MVS.
# Same rules: capture-only, agent does the detection by viewing images.
# GigE allows ONE controller — close the MVS live view before using these.

import hikcam  # noqa: E402

gige_camera = hikcam.HikCamera()
_last_gige_frame = None


@mcp.tool()
@_guard
def gige_capture(grid: bool = True) -> dict:
    """Capture a frame from the GigE Vision camera (the one normally viewed
    in MVS; mono 3072x2048) and save it as a JPEG. READ the returned path to
    see the scene — locate objects with your own vision.

    Args:
        grid: overlay a labeled pixel-coordinate grid (every 200 px on this
            larger sensor) for reading positions. False for a clean image.

    Fails with a clear message if the MVS client currently holds the camera
    (only one controller allowed) — close the MVS live view first."""
    global _last_gige_frame
    try:
        frame = gige_camera.capture()
    except hikcam.HikError as ex:
        return _fail(str(ex))
    _last_gige_frame = frame
    img = vision.draw_grid(frame, step=200) if grid else frame
    path = _save_capture(img, "gige_grid" if grid else "gige_raw")
    h, w = frame.shape[:2]
    return {
        "ok": True,
        "camera": gige_camera.info,
        "image_path": path,
        "width": w,
        "height": h,
        "image_center_px": [w // 2, h // 2],
        "mean_brightness": round(float(frame.mean()), 1),
        "hint": "Read image_path and locate the target visually; grid labels are pixel coordinates",
    }


@mcp.tool()
@_guard
def gige_inspect_region(
    center_x: int,
    center_y: int,
    size: int = 400,
    fresh: bool = False,
) -> dict:
    """Zoom into a region of the GigE camera view (3x, fine grid labeled in
    full-frame coordinates, red cross at the requested point). READ the
    returned image to verify/refine a pixel estimate.

    Args:
        center_x: full-frame x of the region of interest.
        center_y: full-frame y of the region of interest.
        size: square crop side in px (default 400 on this larger sensor).
        fresh: true = capture a new frame first; false = reuse the last
            gige_capture frame so coordinates stay consistent.
    """
    global _last_gige_frame
    if fresh or _last_gige_frame is None:
        try:
            _last_gige_frame = gige_camera.capture()
        except hikcam.HikError as ex:
            return _fail(str(ex))
    img, (x0, y0) = vision.crop_zoom(_last_gige_frame, int(center_x),
                                     int(center_y), int(size))
    path = _save_capture(img, f"gige_zoom_{center_x}_{center_y}")
    return {
        "ok": True,
        "image_path": path,
        "crop_origin_px": [x0, y0],
        "crop_size": size,
        "zoom": 3,
        "requested_point": [center_x, center_y],
        "hint": "grid labels are full-frame pixel coordinates; red cross = your requested point",
    }


@mcp.tool()
@_guard
def gige_release() -> dict:
    """Release the GigE camera so the MVS client can reconnect to it."""
    gige_camera.release()
    return {"ok": True, "released": True}


@mcp.tool()
@_guard
def gige_list_devices() -> dict:
    """Enumerate GigE Vision cameras visible on the network (works even
    while another application holds them)."""
    return {"ok": True, "devices": hikcam.enumerate_devices()}


@mcp.tool()
@_guard
def raw_brcapi(cmd: str, params_json: str = "", timeout: float = 10.0) -> dict:
    """Advanced/debug: send a raw BRCAPI QUERY command and return the raw
    response frame. Motion-triggering commands must use the dedicated tools.

    Args:
        cmd: BRCAPI command name (e.g. 'getSysState', 'getFrameWithU0T0').
        params_json: optional JSON string for the params field.
        timeout: response timeout in seconds.
    """
    if cmd in ("setSysVarI", "remoteEnable", "remoteStart", "moveBackwards"):
        return _fail(f"'{cmd}' must go through its dedicated tool, not raw_brcapi")
    params = json.loads(params_json) if params_json.strip() else None
    frame = robot.request(cmd, params, timeout=timeout)
    return {"ok": True, "response": frame}


if __name__ == "__main__":
    mcp.run()
