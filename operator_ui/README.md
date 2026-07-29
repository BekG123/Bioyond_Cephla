# S4 Operator Console

Human-in-the-loop control panel for the Bioyond S4 cell: the operator sees
the eye-in-hand (GigE) camera live and drives every step with buttons — the
software only executes single, envelope-checked steps and reports back.

```
py operator_ui/app.py        ->  http://127.0.0.1:5002
```

## Exclusive resources (one owner at a time)

- **Robot TCP** — the controller accepts ONE client. The bioyond-s4 MCP
  server, Bioyond Works and this console are mutually exclusive; disconnect
  the others first.
- **GigE camera** — close the MVS live view first. `Release cam` hands it
  back; `Resume cam` takes it again.

## Workflow

1. **Connect** → check the header chips (mode/enabled/program/errors).
2. Switch **Auto**, **Enable** (confirm dialog = you at the E-stop),
   **Start prog** (never while an object is held — E1 resets to 0).
3. Set the **envelope** (work-area preset: X 180-470, Y -400..-100, Z 35-420).
4. **Jog** / `go to` to bring the eye camera roughly over the disk
   (hover Z ≈ 265-270).
5. **Find calibration disk** — iterative SDK-exact vision solve; the arm
   makes small correction moves between captures until converged
   (xy < 0.3 mm, rz < 0.2°, z < 0.3 mm), then publishes the grasp target
   (X, Y, Rz + vision Z and touch-calibrated grip Z). Runs the mcp_teach
   selftest first and refuses on failure.
6. **Align** — in-place Rz rotation (≤30° joint chunks), then a linear move
   to target X/Y at hover height.
7. **Descend** — approach to grip Z + 20, J1-J4 torque baseline (5 reads),
   then 1.0 / 0.5 mm steps at speed 5. First band breach → stop, retreat
   1 mm, classify contact vs drift, and wait for your decision. Refuses to
   run if torque telemetry (SysVarI 13-16) is dead.
8. **Grip** — stepwise torque-guided close (reopens if nothing is gripped);
   **Lift** — straight up, then re-reads the gripper to confirm the hold.
9. **STOP SEQ** halts any sequence after the step in progress. It is NOT an
   E-stop — the physical E-stop stays in the human's hand.

## Files

- `app.py` — Flask routes + page serving (port 5002)
- `robot_service.py` — thread-safe port of the MCP server's control logic
  (preflight, envelope + 480 mm reach check, host-point jobs, gripper,
  torque report)
- `camera_service.py` — GigE capture (wraps `bioyond-s4-mcp/hikcam.py`)
- `teach.py` — SDK-exact solve wrapper around `grab_skill/mcp_teach.py`
- `sequences.py` — find-disk / align / descend / grip as stoppable,
  logged background sequences
- `static/index.html` — the console UI
- `captures/` — teach iteration frames + snapshots (PNG)

Motion faults are never retried: an unknown-state result aborts the
sequence and tells you to re-check status/pose first.
