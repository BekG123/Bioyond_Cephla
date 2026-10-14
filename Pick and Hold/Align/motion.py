"""Existing guarded stage, extracted without behavior changes."""
from __future__ import annotations

def seq_align(run: Runner, svc, target: dict, hover_z: float, validate_descent=True) -> dict:
    """Disk and ArUco use the same fully preflighted, branch-safe approach."""
    from sequences import (AlignmentGuard, _RP, alignment_plan, TransferError, ensure_arrival, _abort)
    try:
        guard = AlignmentGuard(svc, run, _RP)
        pose = guard.pose_mm()
        legs = alignment_plan(pose, target, svc.joints() or {}, _RP,
                              svc.envelope, hover_z or max(300, pose["Z"]),
                              validate_descent=validate_descent)
        previous = pose
        for point in legs:
            if abs(point['Rz'] - previous['Rz']) > 1e-6:
                if any(abs(point[k] - previous[k]) > 1e-6 for k in ('X', 'Y', 'Z')):
                    raise TransferError('alignment rotation must hold XYZ fixed')
                run.say(f"alignment wrist-only MoveJ to Rz {point['Rz']:.3f} at Z {point['Z']:.3f}")
                guard.rotate_to_rz(point['Rz'])
            else:
                run.say(f"alignment MoveL to X {point['X']:.3f} Y {point['Y']:.3f} Z {point['Z']:.3f}")
                guard.move_cartesian(point["X"], point["Y"], point["Z"],
                                     point["Rz"], 5, "linear")
            ensure_arrival(guard.pose_mm(), point)
            run.say(f"alignment waypoint reached: {point}")
            previous = point
        return {"ok": True, "pose": guard.pose_mm(), "gripped": False}
    except (TransferError, KeyError, TypeError) as ex:
        return _abort(run, str(ex))
