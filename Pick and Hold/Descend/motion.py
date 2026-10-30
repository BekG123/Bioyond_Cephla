"""Existing guarded stage, extracted without behavior changes."""
from __future__ import annotations

def seq_descend(run: Runner, svc, target: dict) -> dict:
    from sequences import (_abort, GuardedService, _RP, _wrap180, TransferError, math, _read_torque, APPROACH_OFFSET, _move, DESCEND_SPEED, _halt, BASELINE_N, band_floor, MIN_BAND, PROBE_SPEED, FINE_ZONE, STEP_FINE, STEP_COARSE, J1_TREND_LEN)
    refusal = svc._preflight()
    if refusal:
        return _abort(run, refusal)
    grip_z = float(target["z_calibrated"])
    pose = svc.pose_mm()
    guard = svc if isinstance(svc, GuardedService) else GuardedService(svc, run, _RP)
    try:
        guard._preflight()
        if abs(_wrap180(pose["Rz"] - float(target.get("rz", pose["Rz"])))) > 0.5:
            return _abort(run, "wrist not aligned to target; no descent")
        report = guard.torque_report()
        span = float(target.get("span_mm") or (_RP["claw_gap_max_mm"] - 0.5))
        required = span - _RP["claw_gap_min_mm"] + 0.5
        if not guard.holding and float(report["e1_position"]) < required:
            return _abort(run, "open jaws to clear the plate before descent; no automatic grip/open command issued")
        from autonomy import check_path
        check_path(pose, {**pose, "Z": grip_z}, guard.service.joints() or {}, _RP, guard.service.envelope)
    except (TransferError, KeyError, TypeError, ValueError) as ex:
        return _abort(run, str(ex))

    if math.hypot(pose["X"] - float(target["x"]),
                  pose["Y"] - float(target["y"])) > 1.0:
        return _abort(run, f"tool is at X {pose['X']} Y {pose['Y']} but the "
                           f"target is X {target['x']} Y {target['y']} — run "
                           "Align first")

    r = _read_torque(run, svc)
    if r is None:
        return {"ok": False}
    if not r["telemetry_live"]:
        return _abort(run, "J1-J4 torque slots read ZERO — "
                           "controller/main_hostpoint_trq.bin is not the running "
                           "program; torque-guarded descent unavailable")

    approach_z = grip_z + APPROACH_OFFSET
    if pose["Z"] > approach_z + 0.5:
        err = _move(run, svc, pose["X"], pose["Y"], approach_z, pose["Rz"],
                    DESCEND_SPEED, "approach")
        if err:
            return err
    if run.stopped():
        return _halt(run)

    run.say(f"taking torque baseline ({BASELINE_N} stationary reads)...")
    samples = []
    for _ in range(BASELINE_N):
        r = _read_torque(run, svc)
        if r is None:
            return {"ok": False}
        samples.append([r["joints"][f"J{i}"] for i in (1, 2, 3, 4)])
        if run.stopped():
            return _halt(run)
    n = len(samples)
    mean = [sum(s[i] for s in samples) / n for i in range(4)]
    std = [(sum((s[i] - mean[i]) ** 2 for s in samples) / n) ** 0.5
           for i in range(4)]
    floor = band_floor()
    band = [max(3.0 * sd, floor) for sd in std]
    run.say("baseline mean " + str([round(m) for m in mean])
            + " band " + str([round(b) for b in band])
            + (f" (operator-set floor ±{floor:g} from the torque tab)"
               if floor != MIN_BAND else ""))

    # J1's stationary hold torque is NOT comparable to its post-step
    # readings (observed live: 493 stationary -> 384 right after a free
    # 1 mm step — a false CONTACT stop). Per the skill, J1 is judged ONLY
    # against the local trend of previous post-step readings; the first
    # step seeds that trend and is guarded by J2-J4 alone.
    j1_trend = []
    pose = svc.pose_mm()
    cur_z = pose["Z"]
    run.say(f"stepping down from Z {cur_z:.2f} to grip Z {grip_z:.2f} "
            f"at speed {PROBE_SPEED:g} (1.0 mm steps, 0.5 mm within "
            f"{FINE_ZONE:g} mm)")

    while cur_z > grip_z + 1e-6:
        if run.stopped():
            return _halt(run)
        step = STEP_FINE if cur_z - grip_z <= FINE_ZONE else STEP_COARSE
        next_z = max(grip_z, cur_z - step)
        res = guard.move_cartesian(pose["X"], pose["Y"], next_z, pose["Rz"],
                                 PROBE_SPEED, "linear")
        if not res.get("ok"):
            return _abort(run, f"step refused/failed — {res.get('error')}")
        cur_z = next_z

        r = _read_torque(run, svc)
        if r is None:
            return {"ok": False}
        j = [r["joints"][f"J{i}"] for i in (1, 2, 3, 4)]
        # J1 (Z ram, gravity-loaded) drifts with Z and reads differently
        # right after a move: judge vs the local trend of POST-STEP reads
        # only; J2-J4 idle near zero: judge vs the static baseline
        if j1_trend:
            j1_ref = sum(j1_trend) / len(j1_trend)
            devs = [j[0] - j1_ref] + [j[i] - mean[i] for i in (1, 2, 3)]
            hit = [i for i in range(4) if abs(devs[i]) > band[i]]
        else:
            j1_ref = j[0]     # first post-step read seeds the J1 trend
            devs = [0.0] + [j[i] - mean[i] for i in (1, 2, 3)]
            hit = [i for i in range(1, 4) if abs(devs[i]) > band[i]]
            run.say(f"first step: J1 {j[0]} seeds the local trend "
                    "(stationary baseline is not comparable to post-step "
                    "reads) — J2-J4 guard this step")
        run.say(f"Z {cur_z:7.2f}  J " + str([round(v) for v in j])
                + "  dev " + str([round(d) for d in devs])
                + ("  BREACH " + str([f"J{i+1}" for i in hit]) if hit else ""))

        if hit:
            breach_devs = list(devs)
            run.say("torque band breach — STOP. Retreating 1 mm to "
                    "discriminate contact vs drift", "warn")
            res = guard.move_cartesian(pose["X"], pose["Y"], cur_z + 1.0,
                                     pose["Rz"], PROBE_SPEED, "linear")
            if not res.get("ok"):
                return _abort(run, f"retreat failed — {res.get('error')} — "
                                   "physical state must be checked")
            # read twice and judge on the settled second read — a report
            # taken right after the up-move carries the same post-move
            # artifact that motivated the J1 trend rule
            r2 = _read_torque(run, svc)
            if r2 is not None:
                r2 = _read_torque(run, svc)
            if r2 is None:
                return {"ok": False}
            j2v = [r2["joints"][f"J{i}"] for i in (1, 2, 3, 4)]
            devs2 = [j2v[0] - j1_ref] + [j2v[i] - mean[i] for i in (1, 2, 3)]
            verdicts = {}
            for i in hit:
                unloaded = abs(devs2[i]) < 0.5 * abs(breach_devs[i])
                verdicts[f"J{i+1}"] = "CONTACT (unloaded on retreat)" \
                    if unloaded else "drift (deviation persists)"
            contact = any("CONTACT" in v for v in verdicts.values())
            for jn, v in verdicts.items():
                run.say(f"{jn}: {v}", "warn" if contact else "info")
            above = cur_z - grip_z
            if contact and above > 0.5:
                run.say(f"CONTACT {above:.1f} mm ABOVE grip depth — do NOT "
                        "grip here. Check the camera: what was touched? "
                        "Re-find or reseat the object.", "err")
            elif contact:
                run.say("contact at grip depth — the surface/backstop was "
                        "reached; you may grip from the retreated height",
                        "warn")
            else:
                run.say("looks like sensor drift, not contact. You may "
                        "re-run Descend to continue from here.", "info")
            return {"ok": True, "breach": True, "contact": contact,
                    "verdicts": verdicts, "stopped_z": cur_z,
                    "retreated_to": cur_z + 1.0}

        j1_trend.append(j[0])
        del j1_trend[:-J1_TREND_LEN]

    run.say(f"reached calibrated grip Z {grip_z:.2f} with no torque breach "
            "— ready to Grip", "good")
    return {"ok": True, "breach": False, "at_z": grip_z}
