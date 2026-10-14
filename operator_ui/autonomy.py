"""One-cycle, operator-armed ArUco plate transfer. No hardware on import.

CAD is visualization, not collision checking. The operator must commission
the marker grasp, destination TCP pose and clear swept volume before a run.
"""

from __future__ import annotations

import math
import statistics
import time

# Shared implementations now live with the complete two-disk calibration.
from pick_and_hold.Calibration.fast_disk import (
    TransferError, number, wrap, near, ik, check_path, ensure_arrival, GuardedService,
)

ALIGN_WRIST_SPEED = 30.0  # existing RobotService joint-speed cap
ALIGN_WRIST_STEP_DEG = 30.0  # existing RobotService wrist segment ceiling


def validate_request(body, preview=False):
    if not isinstance(body, dict):
        raise TransferError("expected a JSON object")
    mid = number(body.get("marker_id"), "marker ID")
    if mid != int(mid) or not 0 <= mid < 50:
        raise TransferError("marker ID must be an integer from 0 to 49")
    dest = body.get("destination")
    if not isinstance(dest, dict):
        raise TransferError("destination TCP X/Y/Z/Rz required")
    dest = {k: number(dest.get(k), f"destination {k}") for k in ("x", "y", "z", "rz")}
    travel = number(body.get("travel_z"), "travel Z")
    if travel < dest["z"] + 25:
        raise TransferError("travel Z must be at least 25 mm above placement Z")
    if not -180 <= dest["rz"] <= 180:
        raise TransferError("destination Rz must be -180..180 degrees")
    if not preview and (body.get("confirm") is not True or body.get("cell_clear") is not True):
        raise TransferError("confirm a supervised run and the commissioned clear route")
    offset = number(body.get("grip_z_offset_mm"), "verified marker-to-grip TCP Z offset")
    if abs(offset) > 100:
        raise TransferError("grip Z offset must be within +/-100 mm")
    if travel < 300:
        raise TransferError("automatic wrist rotation requires travel Z >=300 mm (and clear of Squid)")
    return {"marker_id": int(mid), "destination": dest, "travel_z": travel,
            "grip_z_offset_mm": offset, "preview": preview}


def alignment_plan(start, target, joints, params, envelope, hover_z=300, validate_descent=True):
    """Shared disk/marker preflight. Preserve the live branch on every leg.

    No collision claim: the swept volume must still be commissioned.
    Validate descent too, but return alignment legs only (never grip).
    """
    pose = {k: number(start[k], k) for k in ("X", "Y", "Z", "Rz")}
    goal = {k: number(target[v], v) for k, v in
            (("X", "x"), ("Y", "y"), ("Z", "z_calibrated"), ("Rz", "rz"))}
    hover = max(number(hover_z, "hover Z"), pose["Z"])
    if hover < goal["Z"] + 20:
        raise TransferError("hover must be at least 20 mm above descent target")
    if abs(wrap(goal["Rz"]-pose["Rz"])) > 0.05 and hover < 300:
        raise TransferError("wrist rotation requires hover Z >=300 mm")
    q = dict(joints)
    legs = []
    for end in ({**pose, "Z": hover},
                {**pose, "Z": hover, "Rz": goal["Rz"]},
                {**goal, "Z": hover}):
        origin = dict(pose)
        delta = wrap(end["Rz"]-origin["Rz"])
        n = max(1, math.ceil(max(abs(end[k]-origin[k]) for k in ("X","Y","Z"))/10),
                math.ceil(abs(delta)/ALIGN_WRIST_STEP_DEG))
        for i in range(1, n+1):
            point = {k: origin[k]+(end[k]-origin[k])*i/n for k in ("X","Y","Z")}
            point["Rz"] = origin["Rz"]+delta*i/n
            q = check_path(pose, point, q, params, envelope)
            if any(abs(point[k]-pose[k]) > 1e-6 for k in point):
                legs.append(point)
            pose = point
    if validate_descent:
        check_path(pose, goal, q, params, envelope)
    return legs


class AlignmentGuard(GuardedService):
    """Allow only small, checked wrist-only MoveJ segments during Align."""

    def rotate_to_rz(self, rz):
        self._preflight()
        start = self.service.pose_mm()
        if number(start['Z'], 'rotation height') < 300 - 0.05:
            raise TransferError('alignment wrist rotation requires TCP Z >=300 mm')
        delta = wrap(number(rz, 'rotation yaw') - start['Rz'])
        if abs(delta) > ALIGN_WRIST_STEP_DEG + 0.05:
            raise TransferError(f'alignment wrist rotation exceeds the {ALIGN_WRIST_STEP_DEG:g}-degree segment limit')
        target = {**start, 'Rz': start['Rz'] + delta}
        expected = check_path(start, target, self.service.joints() or {},
                              self.params, self.service.envelope)
        # The dedicated service pins XYZ to the live pose. Never dispatch
        # a translated waypoint through joint interpolation.
        result = self.checked(self.service.rotate_to_rz(target['Rz'], ALIGN_WRIST_SPEED,
                                                       force_delta=delta))
        self._preflight()
        ensure_arrival(self.service.pose_mm(), target)
        actual = self.service.joints() or {}
        for key in ('J2', 'J3', 'J4'):
            if abs(number(actual.get(key), key) - expected[key]) > 0.5:
                raise TransferError(f'alignment rotation joint arrival mismatch: {key}; no retry')
        return result


def route(start, source, dest, height):
    """Vertical clearances before wrist rotation and XY translation."""
    points = []
    p = dict(start)
    def add(label, **changes):
        nonlocal p
        p = {**p, **changes}
        points.append((label, dict(p)))
    add("rise to travel height", Z=height)
    add("orient over source", Rz=source["rz"])
    add("source approach", X=source["x"], Y=source["y"])
    add("pick depth", Z=source["z_calibrated"])
    add("lift plate", Z=height)
    add("orient for destination", Rz=dest["rz"])
    add("destination approach", X=dest["x"], Y=dest["y"])
    add("placement depth", Z=dest["z"])
    add("retract", Z=height)
    return points


def detect_source(run, guard, cam, aruco, marker_id, grip_offset):
    """Three centered, stationary observations. No searching motion on Squid."""
    camera_stamp, arm_stamp = aruco.model_stamps()
    if not camera_stamp or not arm_stamp or str(camera_stamp) != str(arm_stamp):
        raise TransferError("camera/claw calibration stamps missing or mismatched")
    entry = aruco.W.CAL.get("marker_offsets", {}).get(str(marker_id), {})
    for key in ("dx_mm", "dy_mm", "rel_yaw_deg", "width_mm", "length_mm"):
        number(entry.get(key), f"marker {marker_id} calibration {key}")
    pose = guard.pose_mm()
    samples = []
    for i in range(3):
        guard._preflight()
        ensure_arrival(guard.pose_mm(), pose)
        path = cam.save(cam.snap(), prefix="transfer")
        s = aruco.solve(path, pose["X"], pose["Y"], pose["Z"], pose["Rz"], marker_id=marker_id)
        ensure_arrival(guard.pose_mm(), pose)
        if not s.get("detected") or s.get("id") != marker_id:
            raise TransferError(f"marker {marker_id} not found unambiguously; no motion made")
        h = number(s.get("H_mm"), "camera distance")
        if not 205 <= h <= 240:
            raise TransferError(f"camera distance {h:.1f} outside commissioned 205..240 mm range")
        center = aruco.view_center_world(pose["X"], pose["Y"], pose["Rz"], h)
        mw = [number(v, "marker coordinate") for v in s["marker_world"]]
        if math.hypot(mw[0]-center[0], mw[1]-center[1]) > 5:
            raise TransferError("marker is not centered within 5 mm; center camera manually before starting")
        number(s.get("marker_yaw_deg"), "marker yaw")
        samples.append(s)
        run.say(f"observation {i+1}/3: marker {marker_id}, XYZ {mw}, camera gap {h:.1f} mm")
    for a in samples:
        for b in samples:
            if math.dist(a["marker_world"], b["marker_world"]) > 2 or abs(wrap(a["marker_yaw_deg"]-b["marker_yaw_deg"])) > 2:
                raise TransferError("marker measurements disagree (>2 mm or 2 deg)")
    # Stationary repeats reject jitter, not systematic calibration error.
    sol = samples[-1]
    mz = statistics.median(s["marker_world"][2] for s in samples)
    return pose, sol, mz + grip_offset


def seq_transfer(run, service, cam, aruco, config, params):
    """No resume or fault recovery. Any uncertain hold leaves the claw as-is."""
    from sequences import seq_descend, seq_grip
    guard = GuardedService(service, run, params)
    phase, holding = "preflight", False
    run.target = None
    try:
        guard._preflight()
        initial = guard.torque_report()
        if number(initial.get("e1_torque"), "initial claw torque") < -100:
            raise TransferError("gripper may already hold an object; inspect and empty it before starting")
        pose, sol, grip_z = detect_source(run, guard, cam, aruco, config["marker_id"], config["grip_z_offset_mm"])
        height, dest = config["travel_z"], config["destination"]
        if height < max(pose["Z"], grip_z+25, dest["z"]+25):
            raise TransferError("travel Z must be above current Z and both grasp/placement heights +25 mm")
        choices, failures = [], []
        for candidate in sol["grab_candidates"]:
            if candidate.get("clampable") is not True:
                continue
            target = dict(x=candidate["tcp"][0], y=candidate["tcp"][1], rz=candidate["rz"], z=sol["marker_world"][2], z_calibrated=grip_z, marker_id=config["marker_id"], span_mm=candidate["span_mm"])
            plan = route(pose, target, dest, height)
            try:
                joints, previous = service.joints() or {}, pose
                for label, point in plan:
                    joints = check_path(previous, point, joints, params, service.envelope)
                    previous = point
            except TransferError as ex:
                failures.append(str(ex))
                continue
            choices.append((abs(wrap(target["rz"]-pose["Rz"])), target, plan))
        if not choices:
            raise TransferError("no calibrated, clampable, path-valid approach: " + ("; ".join(failures) or "check marker dimensions / grasp calibration"))
        _, target, plan = min(choices, key=lambda c: c[0])
        run.target = {**target, "marker_world": sol["marker_world"], "config": "ArUco transfer", "found_at": time.strftime("%H:%M:%S")}
        run.say("Complete TCP route checked. CAD is not a collision model; operator must verify the full swept route.")
        if config.get("preview"):
            run.say("Preview only: no robot or gripper motion was made.", "good")
            return {"ok": True, "phase": "preview", "target": run.target, "plan": plan, "start": pose}

        def move(point):
            guard.move_cartesian(point["X"], point["Y"], point["Z"], point["Rz"], 10)

        def opened():
            g = guard.move_gripper(28)["gripper"]
            if abs(g["position_error"]) > 0.5:
                raise TransferError("claw did not reach open position; no further motion")

        for label, point in plan:
            phase = label
            guard._preflight()
            run.say(label)
            if label in ("pick depth", "placement depth"):
                if label == "pick depth":
                    opened()
                result = seq_descend(run, guard, {"x": point["X"], "y": point["Y"], "z_calibrated": point["Z"]})
                if not result.get("ok") or result.get("breach"):
                    raise TransferError("descent did not reach depth cleanly; no grip/release, inspect contact")
                ensure_arrival(guard.pose_mm(), point)
                if label == "pick depth":
                    phase = "gripping (hold unverified)"
                    result = seq_grip(run, guard, {"reopen_on_miss": False})
                    g = result.get("grip", {})
                    if not result.get("ok") or not result.get("gripped") or not g.get("grip_detected"):
                        raise TransferError("grip requires both torque and position stall; no lift")
                    if abs(number(g.get("e1_position"), "grip position") + params["claw_gap_min_mm"] - target["span_mm"]) > 3:
                        raise TransferError("gripped span disagrees with calibrated plate size; no lift")
                    holding = True
                    guard.holding = True
                else:
                    opened()
                    holding = False
                    guard.holding = False
            else:
                if holding:
                    g = guard.torque_report()
                    if number(g.get("e1_torque"), "hold torque") >= -100:
                        raise TransferError("grip holding torque lost; claw left as-is")
                # Short commands bound between-step Stop latency. Validate
                # the whole leg first, then revalidate from fresh feedback.
                origin = guard.pose_mm()
                delta = wrap(point["Rz"]-origin["Rz"])
                count = max(1, math.ceil(math.dist([origin[k] for k in ("X", "Y", "Z")], [point[k] for k in ("X", "Y", "Z")])/20), math.ceil(abs(delta)/15))
                for i in range(1, count+1):
                    part = {k: origin[k]+(point[k]-origin[k])*i/count for k in ("X", "Y", "Z")}
                    part["Rz"] = wrap(origin["Rz"]+delta*i/count)
                    move(part)
                    if holding:
                        if number(guard.torque_report().get("e1_torque"), "hold torque") >= -100:
                            raise TransferError("holding torque lost after move; no further motion")
        run.say("Transfer cycle finished; retracted above destination. Verify plate seating before another cycle.", "good")
        return {"ok": True, "phase": "complete", "marker_id": config["marker_id"], "destination": dest, "holding": holding, "plan": plan}
    except Exception as ex:
        run.state = "stopped" if run.stopped() else "error"
        run.say(f"TRANSFER STOPPED during {phase}: {ex}. No automatic retry or recovery motion.", "err")
        return {"ok": False, "error": str(ex), "phase": phase, "holding": holding, "inspect_required": True}
