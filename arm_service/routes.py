"""The two legs, joined from the accepted taught routes. Nothing here is a new coordinate.

Taught routes used (read, never written):
  hotel slot 1, revision 7    hotel_slot1_retrieval.geometry() and hotel_slot1_delivery.geometry(), loaded through
                              run_hotel_slot1_workflow.load_workflow(): the acceptance pins in
                              Pick and Hold/Station Handling/workflows/hotel_slot1_v1.json must match.
  Squid (Cellvis)             the "Travel forward" and "Travel reverse" queues of
                              composed_cellvis_registration.delivery_steps('Squid', True), from
                              cellvis24_squid_route.geometry(), pinned by its PLAN_SHA.

The plate is held from the slot to Squid: the HOME holder (the rotating platform) is not used. Both taught routes
pass the HOME clearance C (X 312.5, Y -66.3, Z 105.7, Rz 89.84) with the plate gripped on the same long side at the
same opening (3.9 mm). The only joins are vertical moves at that XY between C and the safe point S above it (Z 293.24),
a part of the vertical that the Squid route itself runs (from Z 80.72 to 293.24). The empty arm parks at C.

A leg is a list of steps. Each run of moves with no gripper action between them is ONE controller queue, so the arm
does not wait for the host between those waypoints.
"""
from __future__ import annotations

import math

from arm_service import OPERATOR_UI  # noqa: F401  (puts the console's modules on the path)

SLOTS = (1,)  # the hotel slots taught for the Cellvis plate
EMPTY_E1 = 7.0  # open jaws for travel without a plate, at the slot and at Squid
GRIP_E1 = 3.9
RELEASE_SPEED = 5
SEAT_SLOW_MM = 10.0  # the last mm above the Squid seat at the taught 5 mm/s; above that, travel speed
LIFT_SPEED = 20  # the 5 mm straight up from the slot rails or the Squid seat (taught at 5)
KEYS = ("X", "Y", "Z", "Rz")


def _point(p: dict) -> dict:
    """The controller stores 1/100 mm (its checksum rounds the same way)."""
    return {k: math.floor(p[k] * 100 + 0.5) / 100 for k in KEYS}


def _squid_queue(steps: list[dict], label: str) -> tuple[list[dict], list[float]]:
    found = [s for s in steps if s["kind"] == "queue" and s["label"] == label]
    if not found:
        raise RuntimeError(f"The accepted Squid route has no '{label}' step.")
    step = found[0]
    speeds = (step.get("flags") or {}).get("segment_speeds") or [step["speed"]] * len(step["points"])
    return [_point(p) for p in step["points"]], list(speeds)


def taught() -> dict:
    """The accepted routes, with their checks. Raises when a file or an acceptance pin changed."""
    from run_hotel_slot1_workflow import load_workflow
    from composed_cellvis_registration import delivery_steps

    workflow, plans = load_workflow()  # acceptance pins, trial evidence and geometry hashes
    delivery, retrieval = plans["deliver"], plans["retrieve"]
    steps = delivery_steps("Squid", True)
    forward, forward_speeds = _squid_queue(steps, "Travel forward")
    reverse, reverse_speeds = _squid_queue(steps, "Travel reverse")
    home = _point(delivery["home"])
    if (abs(forward[0]["X"] - home["X"]) > 0.05 or abs(forward[0]["Y"] - home["Y"]) > 0.05
            or abs(forward[0]["Rz"] - home["Rz"]) > 0.05 or forward[0]["Z"] <= home["Z"]):
        raise RuntimeError("The Squid route no longer starts straight above the HOME clearance.")
    if (abs(reverse[-2]["X"] - home["X"]) > 0.05 or abs(reverse[-2]["Y"] - home["Y"]) > 0.05
            or reverse[-1]["Z"] >= home["Z"]):
        raise RuntimeError("The Squid route no longer returns straight down at the HOME clearance.")
    return dict(workflow=workflow, delivery=delivery, retrieval=retrieval, home=home,
                squid_forward=(forward, forward_speeds), squid_reverse=(reverse, reverse_speeds))


def _queue(label: str, points: list[dict], speeds: list[float], *, loaded: bool, squid: bool = False) -> dict:
    if len(points) != len(speeds) or not points:
        raise RuntimeError(f"{label}: points and speeds differ.")
    return dict(kind="queue", label=label, points=[_point(p) for p in points], speeds=list(speeds),
                e1=GRIP_E1 if loaded else EMPTY_E1, enters_squid=squid)


def legs(t: dict | None = None) -> dict:
    """{'load': steps from slot 1 to Squid, 'unload': steps from Squid to slot 1}. Both start and end with the empty
    arm parked at C with the jaws at 7 mm."""
    t = t or taught()
    home = t["home"]
    forward, forward_speeds = t["squid_forward"]  # S, P1, P2, Squid seat (down at 5)
    reverse, reverse_speeds = t["squid_reverse"]  # lift 5 mm (at 5), P2, P1, S, down to Z 80.72
    if reverse[0]["Z"] - forward[-1]["Z"] > 5.01 or any(reverse[0][k] != forward[-1][k] for k in ("X", "Y", "Rz")):
        raise RuntimeError("The Squid lift is no longer 5 mm straight up from the seat.")
    reverse_speeds = [LIFT_SPEED] + reverse_speeds[1:]
    approach = t["retrieval"]["routes"]["approach"]  # C -> slot 1, the last segment into the slot at 50
    lift = dict(t["retrieval"]["routes"]["lift"])  # 5 mm straight up in the slot (taught at 5)
    if len(lift["points"]) != 1 or abs(lift["points"][0]["Z"] - lift["start"]["Z"] - 5) > 0.01:
        raise RuntimeError("The slot 1 lift is no longer 5 mm straight up.")
    lift["speeds"] = [LIFT_SPEED]
    withdraw_loaded = t["retrieval"]["routes"]["return"]  # out of the slot at 50, back to C
    deliver = t["delivery"]["routes"]["deliver"]  # (HOME proof) C -> slot 1, the last segment into the slot at 50
    withdraw_empty = t["delivery"]["routes"]["return"]  # empty out of the slot at 50, back to C
    if _point(deliver["points"][0]) != home or _point(withdraw_loaded["points"][-1]) != home:
        raise RuntimeError("The slot 1 routes no longer pass the HOME clearance.")
    # Down to Squid fast until 10 mm above the seat, on the same vertical, then the last 10 mm at the taught 5 mm/s.
    seat = forward[-1]
    above_seat = dict(seat, Z=round(seat["Z"] + SEAT_SLOW_MM, 2))
    if not forward[-2]["Z"] > above_seat["Z"] or any(forward[-2][k] != seat[k] for k in ("X", "Y", "Rz")):
        raise RuntimeError("The Squid seat is no longer below its approach point.")
    to_squid = forward[:-1] + [above_seat, seat]  # from C: straight up to S, the taught route, the seat
    to_squid_speeds = forward_speeds[:-1] + [forward_speeds[-2], forward_speeds[-1]]
    squid_to_c = reverse[:-1] + [home]  # the taught way back, ending at C instead of going lower
    squid_to_c_speeds = reverse_speeds[:-1] + [reverse_speeds[-1]]
    # Holding the plate the arm does not go down to C between the slot and Squid: from the last point of the slot
    # route (X 240, Y 25, Z 191.2) it goes straight to S above C (Z 293.24), and back the same way. That one segment
    # is new; it runs higher than the taught dip to C and is checked like every move.
    load = [
        _queue("To slot 1, empty", approach["points"], approach["speeds"], loaded=False),
        dict(kind="grip", label="Grip the plate in slot 1"),
        dict(kind="squid", label="Check that Squid is at its loading position"),
        _queue("Slot 1 to Squid, holding the plate",
               lift["points"] + withdraw_loaded["points"][:-1] + to_squid,
               lift["speeds"] + withdraw_loaded["speeds"][:-1] + to_squid_speeds, loaded=True, squid=True),
        dict(kind="release", label="Release the plate at Squid"),
        _queue("Back to the safe position, empty", squid_to_c, squid_to_c_speeds, loaded=False, squid=True),
    ]
    unload = [
        dict(kind="squid", label="Check that Squid is at its loading position"),
        _queue("To Squid, empty", to_squid, to_squid_speeds, loaded=False, squid=True),
        dict(kind="grip", label="Grip the plate at Squid"),
        _queue("Squid to slot 1, holding the plate",
               squid_to_c[:-1] + deliver["points"][1:], squid_to_c_speeds[:-1] + deliver["speeds"][1:],
               loaded=True, squid=True),
        dict(kind="release", label="Release the plate in slot 1"),
        _queue("Back to the safe position, empty", withdraw_empty["points"], withdraw_empty["speeds"], loaded=False),
    ]
    return dict(load=load, unload=unload, home=home)


def recoveries(t: dict | None = None) -> list[dict]:
    """Where an empty arm can stop between two steps, and the taught empty way back to C from there: the last queue
    of each leg ("Back to the safe position, empty"), which starts where the plate was just released (in slot 1, or
    on the Squid seat)."""
    all_legs = legs(t)
    out = []
    for name, where in (("load", "the Squid seat"), ("unload", "slot 1")):
        steps = all_legs[name]
        back = steps[-1]
        loaded = [s for s in steps if s["kind"] == "queue"][-2]
        if back["kind"] != "queue" or back["e1"] != EMPTY_E1 or steps[-2]["kind"] != "release":
            raise RuntimeError(f"The {name} leg no longer ends with a release and an empty way back.")
        out.append(dict(at=loaded["points"][-1], where=where, step=dict(back)))
    return out


def check_queue(start: dict, joints: dict, points: list[dict], cfg: dict, envelope: dict) -> dict:
    """Reach, joint limits and winding along the moves, with the same checks the slot 1 routes use. Points outside
    the box are allowed only in the exact slot 1 corridor. Returns the joints expected at the end."""
    from hotel_slot1_retrieval import checked

    return checked(start, points, joints, cfg, envelope, True)["endpoint_joints"]


def check_legs(start_joints: dict, cfg: dict, envelope: dict, t: dict | None = None) -> dict:
    """Offline: every queue of both legs from C with the given joints at C, chained. Returns the expected joints at
    the end of each queue, by leg and step index."""
    all_legs = legs(t)
    home = all_legs["home"]
    out = {}
    for name in ("load", "unload"):
        q, pose, expected = dict(start_joints), home, {}
        for index, step in enumerate(all_legs[name]):
            if step["kind"] != "queue":
                continue
            q = check_queue(pose, q, step["points"], cfg, envelope)
            expected[index] = q
            pose = step["points"][-1]
        if any(abs(q[k] - start_joints[k]) > 0.5 for k in ("J2", "J3", "J4")) or pose != home:
            raise RuntimeError(f"The {name} leg does not end parked at C with the same winding.")
        out[name] = expected
    return out
