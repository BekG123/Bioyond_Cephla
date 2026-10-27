# Vertical-motion smoothing

The last hardware log shows vertical speed falling from about **21 mm/s to 4.5–4.7 mm/s** at Z155.7 and Z204.1. These coincide with intermediate MoveL endpoints on the otherwise straight Z110.97→253.80 lift. The 50 mm grouping cap inserted those boundaries.

Implemented a strict vertical-run coalescer: **78 → 75 commands**, in both directions. The 142.83 mm lift becomes one command; the 55.06 mm lift becomes one instead of two. Endpoints, real bends, Z reversals, and the first/last 10 mm waypoint detail remain intact. Maximum change for this route: **0.038 mm / 0.017°**. Full-segment IK passes in both directions.

Long segments are allowed only for separately reviewed, nearly vertical moves: ≤200 mm travel, ≤0.25 mm lateral endpoint drift and ≤0.1° endpoint yaw change. All other reviewed segments retain their 50 mm limit. The coalescer additionally bounds the whole intervening path change to 0.1 mm / 0.05°. The executor never silently regroups an approved artifact.

![Measured speed dips and prepared change](z_motion_comparison.png)

The native Lua executor still uses one final MOVFINISH and zone −1. Speed remains 40; acceleration, jerk and blending parameters were not guessed. The local Bioyond Works manual (PDF pages 47–50) lists SetAcc and SetAccTime but does not establish the required parameter units/ranges or zone −1 semantics.

**Prepared and tested offline; no hardware run of this version yet.** Horizontal corner slowdowns may remain. This removes specific artificial stops; it does not establish continuous velocity or jerk-limited motion throughout the whole route. A separate hash-bound approval is required for a future run, using `start-pruned` with `route: vertical` and the selected direction.

[75-point candidate](candidate.json) · [Measured baseline data](diagnosis.json)
