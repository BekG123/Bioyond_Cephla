# Bioyond S4 MCP Server

MCP server that exposes the Bioyond LabGenius S4 robot arm (BRCAPI / Rob INTF
v1.1, TCP port 56788, controller at 192.168.201.220) as tools, so Claude can
query and drive the robot in natural language.

Registered for this project in `../.mcp.json` (stdio transport). Restart the
Claude Code session after changing that file, then approve the `bioyond-s4`
server when prompted.

## Controller-side contract (deployed main.bin)

The controller runs a job loop (`mod_Socket`) keyed on integer system
variables: `0=DeviceID 1-3=PosSelectors 4=MoveType 5=ObjType 6=ClampMode`.
Completion is signalled by SysOutVar `{index:1, value:1}` (success) or
`{index:1, value:-1}` (invalid job). Taught jobs: device 3 = homing,
11/12/13/14/15/9998/9999 = station pick/place, 1 = stack, 2 = scan.

**Host Cartesian control requires `main_hostpoint.bin`** (built from the
deployed project by `tests/../..`'s build script; file lives at
`C:\Users\raman\Desktop\test1\main_hostpoint.bin`). It adds device ID 21:
float params 40=X 41=Y 42=Z 43=Rz(deg) 44=speed 45=blend 46=E1, with
MoveType 1=MoveL 2=MoveJ 3=gripper 4=MoveAbsJ. Publish it via Bioyond Works.
On a stock program, device-21 jobs are rejected with -1 and no motion — the
server reports this cleanly.

Units: motion commands are mm / degrees (taught-point scale); the
controller's pose *query* reports meters (the server converts). The
controller returns float params as strings (the client coerces). E1 gripper:
open=6.5, close=3 (data.lua). E2 is the rotator; the server always holds it.

## Configuration (env vars, set in .mcp.json)

| Variable | Default | Meaning |
| --- | --- | --- |
| `BIOYOND_IP` | 192.168.201.220 | Controller IP (port fixed 56788) |
| `BIOYOND_LINEAR_SPEED` / `BIOYOND_MAX_LINEAR_SPEED` | 50 / 200 | MoveL/MoveJ speed default and cap (Lua mm/s scale) |
| `BIOYOND_JOINT_SPEED` / `BIOYOND_MAX_JOINT_SPEED` | 10 / 30 | MoveAbsJ/MoveExtJ speed default and cap |
| `BIOYOND_X/Y/Z_MIN/MAX` | X 200..450, Y -250..50, Z 350..400 | Commissioning envelope (mm); adjustable at runtime via `set_workspace_envelope` |
| `BIOYOND_MOTION_TIMEOUT` | 180 | Seconds to wait for completion replies |

## Tools

Read-only: `get_status`, `get_cartesian_pose` (mm + raw), `get_joint_positions`,
`get_robot_errors`, `read_system_values`, `raw_brcapi` (query-only).

Cameras (capture-only — object detection is done by the agent viewing the
images; operator preference: no local CV detection):
- Arducam B0478 USB3 (1920×1080, selected by device name): `camera_capture`
  (labeled grid overlay), `camera_inspect_region` (3× zoom, fine grid),
  `camera_release`.
- GigE Vision JHEM600GM-HM (mono 3072×2048, 192.168.201.89, via the MVS
  SDK's Python bindings): `gige_capture`, `gige_inspect_region`,
  `gige_release`, `gige_list_devices`. GigE allows one controller at a
  time — close the MVS live view before capturing, and `gige_release`
  to give it back.

Session/control: `connect`/`disconnect`, `switch_mode`, `start_program`/
`pause_program`/`stop_program`, `enable_robot`*, `disable_robot`,
`clear_errors`*, `move_backwards`*/`stop_move_backwards`,
`set_workspace_envelope`*.

Motion (host-point, needs main_hostpoint.bin): `move_to_cartesian`
(envelope-checked), `move_joints`*, `move_gripper`.

Taught jobs: `go_home`*, `run_station_job`* (pick/place at stations),
`run_lua_job`* (raw var patterns, e.g. stack/scan).

`*` = requires `operator_confirmed=true` from a human.

## Safety model

- Motion preflight: refuses to move on active errors, manual mode, disabled
  servos, or a non-running/uninitialized Lua program.
- Cartesian targets outside the envelope are refused; joint-space and taught
  jobs (which bypass the envelope) need operator confirmation.
- A motion timeout is reported as **unknown physical state** and never
  retried automatically; if the trigger was provably never consumed, the
  server clears it and says so.
- The hardware E-stop remains the authoritative safety control.

## Testing offline

`py tests/test_offline.py` runs the full tool surface against a fake
controller on 127.0.0.1 that emulates the deployed contract (fragmented
frames, meters pose, string params, -1 invalid path). No robot needed.
