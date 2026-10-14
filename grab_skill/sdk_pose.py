"""Compatibility import for vendor pose math, now in Calibration/fast_disk.py."""
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "operator_ui"))
from pick_and_hold.Calibration.fast_disk import (
    _rot, _to_euler, _norm360, compose, invert, wrap180,
)

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
