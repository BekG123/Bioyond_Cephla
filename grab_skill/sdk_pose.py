"""Faithful port of the Bioyond SDK pose math (from decompiled VCS.Vision.CVUtility).

Pose = [X, Y, Z, Rx, Ry, Rz]  (mm, degrees).
RotationMatrixFromEulerAngles(a,b,g) = Rz(g) @ Ry(b) @ Rx(a).
ComposePoses(p1,p2): R = R1@R2, t = R1@t2 + t1.
Grasp = ComposePoses(convergedCameraPose, TeachInTrigger).
"""
import numpy as np


def _rot(a, b, g):
    a, b, g = np.radians([a, b, g])
    Rx = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    Ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
    Rz = np.array([[np.cos(g), -np.sin(g), 0], [np.sin(g), np.cos(g), 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def _to_euler(R):
    sy = np.hypot(R[0, 0], R[1, 0])
    if sy > 1e-6:
        rx = np.arctan2(R[2, 1], R[2, 2])
        ry = np.arctan2(-R[2, 0], sy)
        rz = np.arctan2(R[1, 0], R[0, 0])
    else:
        rx = np.arctan2(-R[1, 2], R[1, 1])
        ry = np.arctan2(-R[2, 0], sy)
        rz = 0.0
    return np.degrees([rx, ry, rz])


def _norm360(a):
    while a > 360.0:
        a -= 360.0
    while a < 0.0:
        a += 360.0
    return a


def compose(p1, p2):
    p1, p2 = np.asarray(p1, float), np.asarray(p2, float)
    R1 = _rot(p1[3], p1[4], p1[5])
    R = R1 @ _rot(p2[3], p2[4], p2[5])
    t = R1 @ p2[:3] + p1[:3]
    e = _to_euler(R)
    return np.array([t[0], t[1], t[2], _norm360(e[0]), _norm360(e[1]), _norm360(e[2])])


def invert(p):
    p = np.asarray(p, float)
    T = np.eye(4)
    T[:3, :3] = _rot(p[3], p[4], p[5])
    T[:3, 3] = p[:3]
    Ti = np.linalg.inv(T)
    e = _to_euler(Ti[:3, :3])
    return np.array([Ti[0, 3], Ti[1, 3], Ti[2, 3], e[0], e[1], e[2]])


def wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


if __name__ == "__main__":
    # --- VALIDATION against run 6 (known-good grasp that lifted the board) ---
    TEACH_IN_TRIGGER = [-2.92389023263826, -91.8046466302631, -223.593, 0, 0, 81.8629]
    grasp_run6 = [217.081721556673, -321.412455335999, 41.863, 0, 0, 0.3476]

    # run-6 converged camera pose implied by grasp = compose(C, T):  C = compose(grasp, inv(T))
    C_implied = compose(grasp_run6, invert(TEACH_IN_TRIGGER))
    print("run-6 converged camera pose implied by the math:")
    print(f"  X={C_implied[0]:.2f} Y={C_implied[1]:.2f} Z={C_implied[2]:.2f} "
          f"Rz={wrap180(C_implied[5]):.2f}")
    print("  (run-6 fine-tune actually converged near 308.7, -310.3, 264, Rz -81.8)")

    # forward check: compose(that camera pose, T) must return the grasp
    back = compose(C_implied, TEACH_IN_TRIGGER)
    print("\nforward check compose(C_implied, TeachInTrigger) -> grasp:")
    print(f"  X={back[0]:.3f} Y={back[1]:.3f} Z={back[2]:.3f} Rz={wrap180(back[5]):.3f}")
    print(f"  expected                                          "
          f"X={grasp_run6[0]:.3f} Y={grasp_run6[1]:.3f} Z={grasp_run6[2]:.3f} Rz={grasp_run6[5]:.3f}")
