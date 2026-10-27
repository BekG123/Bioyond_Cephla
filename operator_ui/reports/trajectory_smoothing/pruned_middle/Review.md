# Middle-loop removal

**Offline candidate only. No hardware movement or replay-setting changes.**

Two near-return loops at Z≈253.6–253.7 mm can be replaced by short connectors. TCP travel decreases from **1816.8 to 1066.8 mm**, saving **750.0 mm (41.3%)**.

Grouping the shorter route gives **78 commands**, using the original **0.25 mm / 0.1°** grouping tolerances and 50 mm arc cap. These bounds are relative to the proposed pruned route, not the deleted detours. The previous 70-point proposal merely simplified those detours; this candidate removes them.

The complete initial portion before the highest plateau and the final descent/Hamilton approach are preserved in the pruned polyline. Both forward and reverse IK checks pass. The original recording and its replay permission remain unchanged.

![Route comparison](comparison.png)

| Connector | Source point indices | Replaced travel | New travel | Yaw change |
|---|---|---:|---:|---:|
| 1 | 99 → 288 | 656.88 mm | 4.61 mm | 2.54° |
| 2 | 288 → 328 | 102.48 mm | 4.70 mm | 2.80° |

## Clearance review

Review the two red connectors near X225–231, Y3–8, Z254 mm, including the wrist/gripper and full arm swept volume. The plot describes TCP motion; no obstacle geometry was used. A hand-guided detour may have avoided an obstacle even when its endpoints are close.

The first connector reaches 2.19 mm from the old recorded corridor in the sampled check, exceeding its 2 mm monitor limit. A future approved route needs its own reviewed reference and permission; do not bypass or widen the existing monitor to execute this file.

Runtime replay is still bound to the original recording. This candidate is a separate artifact with execution disabled; it is not loaded into the controller. No speed or smoothness improvement is claimed until a supervised hardware test.

[Coordinates, retained source indices and IK results](candidate.json) · [Printable comparison](comparison.pdf)
