"""Existing guarded stage, extracted without behavior changes."""
from __future__ import annotations

def seq_grip(run: Runner, svc, params: dict) -> dict:
    from sequences import (_abort, _read_torque, BASELINE_N, _halt, time, band_floor)
    refusal = svc._preflight()
    if refusal:
        return _abort(run, refusal)
    threshold = float(params.get("threshold", -100.0))
    start = float(params.get("start", 28.0))
    floor = float(params.get("floor", 1.0))
    step = float(params.get("step", 0.1))
    coarse = float(params.get("coarse_step", 0.5))
    fine_from = float(params.get("fine_from", 8.0))
    if step <= 0 or start <= floor:
        return _abort(run, "need step > 0 and start > floor")

    run.say(f"grip: open to {start}, close in {coarse}/{step} steps until "
            f"torque <= {threshold} (floor {floor})")
    g = svc.move_gripper(start)
    if not g.get("ok"):
        return _abort(run, f"open failed — {g.get('error')}")

    # arm-joint torque guard: the E1 check below only sees the GRIPPER's
    # own torque sensor — if the object catches at an angle, the reaction
    # can load the WRIST (J4) instead, which E1 can't see at all. That
    # blind spot let closing keep commanding tighter until the controller's
    # own hard collision fault (3873, axis 4) was the only thing that
    # stopped it (hit live twice, 2026-09-14). Baseline + per-step band,
    # same formula seq_descend uses for its own torque guard — no Z motion
    # happens during a grip, so (unlike descend) J1 needs no special
    # trend handling; a plain static baseline works for all 4 joints.
    r = _read_torque(run, svc)
    if r is None:
        return {"ok": False}
    if not r["telemetry_live"]:
        return _abort(run, "J1-J4 torque slots read ZERO — "
                           "main_hostpoint_trq.bin is not the running "
                           "program; torque-guarded grip unavailable")
    samples = []
    for _ in range(BASELINE_N):
        if run.stopped():
            return _halt(run)
        r = _read_torque(run, svc)
        if r is None:
            return {"ok": False}
        samples.append([r["joints"][f"J{i}"] for i in (1, 2, 3, 4)])
    n = len(samples)
    jmean = [sum(s[i] for s in samples) / n for i in range(4)]
    jstd = [(sum((s[i] - jmean[i]) ** 2 for s in samples) / n) ** 0.5
            for i in range(4)]
    jband = [max(3.0 * sd, band_floor()) for sd in jstd]
    run.say("arm-joint torque baseline " + str([round(m) for m in jmean])
            + " band " + str([round(b) for b in jband]))

    target = start
    steps = 0
    while target - step >= floor - 1e-9:
        if run.stopped():
            run.say("stopped — gripper left where it is", "warn")
            return {"ok": False, "stopped": True}
        if coarse > step and target - coarse > max(fine_from, floor):
            target = round(target - coarse, 3)
        else:
            target = round(target - step, 3)
        g = svc.move_gripper(target)
        if not g.get("ok"):
            return _abort(run, f"close step to {target} failed — "
                               f"{g.get('error')}")
        gr = g.get("gripper", {})
        steps += 1

        jr = _read_torque(run, svc)
        if jr is None:
            return {"ok": False}
        j = [jr["joints"][f"J{i}"] for i in (1, 2, 3, 4)]
        jdevs = [j[i] - jmean[i] for i in range(4)]
        jhit = [i for i in range(4) if abs(jdevs[i]) > jband[i]]
        if jhit:
            run.say(f"ARM TORQUE BREACH at E1 {target}: J "
                    + str([round(v) for v in j]) + "  dev "
                    + str([round(d) for d in jdevs]) + "  BREACH "
                    + str([f"J{i+1}" for i in jhit])
                    + " — stopping before this becomes a collision fault; "
                      "gripper left where it is, inspect before retrying",
                    "err")
            return {"ok": False, "arm_torque_breach": True,
                    "breached": [f"J{i+1}" for i in jhit],
                    "stopped_at_command": target}

        if steps % 10 == 0 or gr.get("e1_torque", 999) <= threshold:
            run.say(f"E1 cmd {target:6.2f}  pos {gr.get('e1_position')}  "
                    f"torque {gr.get('e1_torque')}")
        if gr.get("e1_torque", 999) <= threshold:
            detected = (gr.get("position_error", 0) > 0.15
                        and gr.get("e1_torque", 0) < -100)
            run.say(f"TORQUE CROSSING at cmd {target}: pos "
                    f"{gr.get('e1_position')}, torque {gr.get('e1_torque')}"
                    f" — grip_detected={detected}",
                    "good" if detected else "warn")
            if not detected:
                run.say("torque crossed but no position stall — verify "
                        "visually before lifting", "warn")
            return {"ok": detected, "gripped": detected, "grip": gr,
                    "confirmed_at": time.time() if detected else None,
                    "error": None if detected else "Torque crossing without position stall: grip not confirmed",
                    "stopped_at_command": target}
    run.say(f"floor {floor} reached with no torque crossing — no grip confirmed.", "err")
    if params.get("reopen_on_miss", True):
        svc.move_gripper(start)
    return {"ok": False, "gripped": False,
            "error": "no object detected between the plates"}
