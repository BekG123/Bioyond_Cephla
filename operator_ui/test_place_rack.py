"""Standalone test: place the currently-gripped plate into a single-column,
side-loading rack slot, then retreat empty.

This mirrors mod_Stack.lua's PLACE branch (SYSINVAR4==2): slide in elevated
above the seat height, lower straight down onto the shelf/pins, release,
then retreat at the LOWERED height (not re-lifted) so the gripper clears
the shelf above before it moves back out.

Talks to the already-running Flask console (localhost:5002) so every move
goes through the existing envelope check — nothing here bypasses safety.

--------------------------------------------------------------------------
BEFORE RUNNING: with the plate still gripped, manually jog the arm (Flask
console's Jog tab) through three waypoints and read each pose from
GET /state -> robot.pose_mm. Fill them in below.

  STANDOFF  fully clear of the rack, safe travel pose (current pose is
            probably fine as a start).
  APPROACH  aligned with the slot's XY/Rz, OUTSIDE the slot mouth,
            elevated ~7-10 mm above where the plate will finally rest.
  SEATED    same XY/Rz as APPROACH, Z lowered onto the shelf/pins - the
            plate's true resting height.

Human must be at the E-stop. Run: py test_place_rack.py
--------------------------------------------------------------------------
"""
import math
import sys
import time

import requests

BASE = "http://127.0.0.1:5002"

STANDOFF = {"x": 254.955, "y": -238.328, "z": 150.0, "rz": 86.734}
APPROACH = {"x": 255.607, "y": -183.496, "z": 359.157, "rz": -2.318}
SEATED = {"x": 279.624, "y": -139.4, "z": 359.138, "rz": 0.386}

RELEASE_E1 = 28.0        # gripper opening (mm) that lets go of the plate
SPEED_TRAVEL = 15.0
SPEED_SETTLE = 5.0
STEP_MM = 1.0             # torque-guarded step size for the final settle
BAND_FLOOR = 30.0         # min deviation treated as real (torque units)
BASELINE_N = 5


def die(msg):
    sys.exit(f"ABORT: {msg}")


def check_filled():
    for name, p in (("STANDOFF", STANDOFF), ("APPROACH", APPROACH),
                    ("SEATED", SEATED)):
        if any(v is None for v in p.values()):
            die(f"{name} is not filled in — jog there and copy pose_mm "
                "from GET /state first")


def pose():
    r = requests.get(f"{BASE}/state").json()["robot"]
    if not r.get("connected"):
        die("robot not connected — hit POST /connect first")
    return r["pose_mm"]


def travel(target, speed, why):
    """Staged move to a waypoint that may differ a lot from the current
    pose: rise/lower Z in place, then rotate Rz in place, then translate
    XY - never a single diagonal MoveL blending all axes at once. Same
    z,rz,xy leg order the workflow engine (WF_ORDER_DEFAULT) uses
    elsewhere in this codebase, for the same reason."""
    p = pose()
    if abs(p["Z"] - target["z"]) > 0.5:
        move(p["X"], p["Y"], target["z"], p["Rz"], speed,
             f"{why}: rise/lower Z")
    p = pose()
    if abs(((target["rz"] - p["Rz"] + 180) % 360) - 180) > 0.5:
        move(p["X"], p["Y"], p["Z"], target["rz"], speed,
             f"{why}: rotate Rz")
    p = pose()
    if math.hypot(target["x"] - p["X"], target["y"] - p["Y"]) > 0.5:
        move(target["x"], target["y"], p["Z"], target["rz"], speed,
             f"{why}: slide XY")


def move(x, y, z, rz, speed, why):
    print(f"{why}: -> X{x:.2f} Y{y:.2f} Z{z:.2f} Rz{rz:.2f} @ {speed:g}")
    r = requests.post(f"{BASE}/move", json={
        "x": x, "y": y, "z": z, "rz": rz, "speed": speed,
        "interpolation": "linear"}).json()
    if not r.get("ok"):
        die(f"move refused/failed — {r.get('error')}")
    return r


def torque():
    r = requests.post(f"{BASE}/gripper", json={"action": "torque"}).json()
    if not r.get("ok"):
        die(f"torque report failed — {r.get('error')}")
    return r


def gripper_move(e1, speed=0):
    return requests.post(f"{BASE}/gripper",
                          json={"action": "move", "e1": e1,
                                "speed": speed}).json()


def gripper_status():
    return requests.post(f"{BASE}/gripper",
                          json={"action": "status"}).json()


def baseline():
    samples = []
    for _ in range(BASELINE_N):
        r = torque()
        samples.append([r["joints"][f"J{i}"] for i in (1, 2, 3, 4)])
        time.sleep(0.1)
    n = len(samples)
    mean = [sum(s[i] for s in samples) / n for i in range(4)]
    std = [(sum((s[i] - mean[i]) ** 2 for s in samples) / n) ** 0.5
           for i in range(4)]
    band = [max(3.0 * sd, BAND_FLOOR) for sd in std]
    print("baseline mean", [round(m) for m in mean],
          "band", [round(b) for b in band])
    return mean, band


def main():
    check_filled()
    print("=== place-rack test ===")

    print("1) travel to STANDOFF")
    travel(STANDOFF, SPEED_TRAVEL, "standoff")

    print("2) travel to APPROACH (elevated, aligned with the slot)")
    travel(APPROACH, SPEED_TRAVEL, "approach")

    print("3) slide in laterally to SEATED xy, still at APPROACH height")
    move(SEATED["x"], SEATED["y"], APPROACH["z"], SEATED["rz"],
         SPEED_TRAVEL, "slide-in")

    print("4) torque baseline before the guarded settle-down")
    mean, band = baseline()

    print("5) step down onto the shelf/pins, watching torque every step")
    cur_z = APPROACH["z"]
    while cur_z > SEATED["z"] + 1e-6:
        next_z = max(SEATED["z"], cur_z - STEP_MM)
        move(SEATED["x"], SEATED["y"], next_z, SEATED["rz"],
             SPEED_SETTLE, "settle step")
        cur_z = next_z
        r = torque()
        j = [r["joints"][f"J{i}"] for i in (1, 2, 3, 4)]
        dev = [j[i] - mean[i] for i in range(4)]
        hit = [i for i in range(4) if abs(dev[i]) > band[i]]
        print(f"  Z {cur_z:7.2f}  J {[round(v) for v in j]}  "
              f"dev {[round(d) for d in dev]}"
              + ("  BREACH " + str([f"J{i+1}" for i in hit]) if hit else ""))
        if hit:
            print("UNEXPECTED CONTACT — retreating 1 mm and stopping. "
                  "Check the shelf alignment before continuing.")
            move(SEATED["x"], SEATED["y"], cur_z + 1.0, SEATED["rz"],
                 SPEED_SETTLE, "retreat")
            die("torque breach during settle — inspect before retrying")

    print("6) seated cleanly — releasing the plate")
    gripper_move(RELEASE_E1)
    time.sleep(0.3)
    print("gripper after release:", gripper_status())

    print("7) retreat out at SEATED height (no re-lift, clears the shelf "
          "above)")
    move(APPROACH["x"], APPROACH["y"], SEATED["z"], APPROACH["rz"],
         SPEED_TRAVEL, "retreat-out")

    print("8) back to STANDOFF")
    travel(STANDOFF, SPEED_TRAVEL, "standoff")

    print("DONE — verify visually that the plate is seated and the "
          "gripper is clear")


if __name__ == "__main__":
    main()
