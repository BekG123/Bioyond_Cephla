# Adapting descent after the plate moves

The placement adapter is saved in `operator_ui/prepare_adapted_descent.py`.
It transfers the original successful claw correction to a fresh converged
Wide calibration: `T_new_plate * inverse(T_original_plate) * T_original_endpoint`.
It keeps the taught Z only for the same supporting surface and plate/tool
geometry. Each candidate starts from the original demonstration, so repeated
adjustments do not accumulate offsets.

1. Calibrate and Align to Z300 for the current plate placement.
2. Run `prepare_adapted_descent.py`. It saves a candidate and checks the
   correction, descent, IK, and existing joint/workspace limits without moving.
3. Confirm the supporting surface and clearance, then use
   `execute_adapted_descent.py <review.json> --operator-confirmed`.
   It records the supervised trial, leaves jaws open, and restores the old
   default while awaiting visual inspection. It never grips.
4. After explicit visual acceptance, run
   `accept_adapted_descent.py <trial-folder> --feedback "<operator feedback>"`.
   This promotes the tested endpoint to the shared GUI profile without motion.

Accepted trial: `adapted_20261020T050727394171Z`.
Endpoint: X309.5081, Y-66.0734, Z70.461 mm, Rz89.1737 degrees.
Operator confirmed both jaws centered at the correct height.
Trial completed in 34.67 seconds with open jaws and no controller errors.
Grip and load-bearing ability were not validated by this descent.

The reusable method is saved; arbitrary future placements are not automatically
approved. A new placement needs fresh calibration, a checked candidate and a
supervised trial. Full JSON evidence is in `operator_ui/reports/descent_trials/`.
