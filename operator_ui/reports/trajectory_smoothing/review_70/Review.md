# 70-waypoint clearance review

**Prepared offline only. No robot motion; this candidate is not enabled for replay.**

- Direction: Hamilton → recorded Home-area start (not saved Home).
- 544 dense segments → 132 current commands → **70 candidate commands**.
- Ordered-path deviation: at most **3.143 mm / 1.598°**, versus current planning tolerances of 0.25 mm / 0.1°.
- Maximum grouped source arc: **100 mm**, increased from 50 mm.
- IK checks pass for every candidate segment. **17 segments exceed the existing 2 mm / 2° runtime monitor** in the sampled check.
- Production settings, replay permission, original recording and saved Home are unchanged.

![Path comparison](review.png)

## Segments needing particular clearance review

| Segment | Max sampled position deviation (mm) | Location of maximum (X, Y, Z mm) |
|---|---:|---|
| 6 | 2.157 | 195.92, -335.94, 111.03 |
| 11 | 3.058 | 214.23, -157.32, 111.05 |
| 12 | 2.422 | 224.42, -133.15, 111.06 |
| 13 | 2.916 | 247.37, -107.63, 111.02 |
| 19 | 2.553 | 283.00, -32.72, 253.71 |
| 26 | 2.784 | 231.35, -1.61, 253.71 |
| 37 | 2.046 | 258.48, -29.58, 253.63 |
| 38 | 2.735 | 352.20, -71.52, 253.62 |
| 39 | 3.023 | 384.69, -82.98, 253.62 |
| 40 | 2.893 | 399.72, -66.85, 253.62 |
| 41 | 2.995 | 393.59, -12.09, 253.62 |
| 45 | 2.057 | 343.93, 115.81, 253.62 |
| 52 | 2.317 | 191.92, 0.00, 232.04 |
| 55 | 2.665 | 239.51, -9.80, 193.81 |
| 56 | 2.547 | 264.57, -14.94, 170.53 |
| 61 | 2.643 | 340.36, 5.25, 166.41 |
| 63 | 3.136 | 334.83, 58.98, 166.41 |

Review these chords against the actual Hamilton fixtures and the full arm/gripper swept volume. The plot shows TCP geometry, not measured obstacle clearance. IK feasibility does not establish collision clearance. The runtime comparison samples at ≤1 mm translation / 0.1° yaw; the ordered-path geometric bound covers the full segments.

No velocity/acceleration/jerk improvement has been measured for this candidate. Fewer waypoints alone do not establish smoother motion.

[All 70 waypoints, segment checks and source hash](candidate.json) · [Printable plots](review.pdf)
