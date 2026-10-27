# Home versus taught replay

| Property | Vendor Home | Previous queued replay | Grouped replay |
|---|---:|---:|---:|
| Motion command | MoveAbsJ | MoveL | MoveL |
| Commands to Hamilton | 1, different destination/path | 543 | 132 |
| Upload batches | N/A | 181 | 44 |
| Median translation per command | N/A | 3.63 mm | 13.00 mm |
| Commands shorter than 1 mm | N/A | 43 | 4 |
| Zone setting | −1 | −1 | −1 (unchanged) |
| Hardware result | No matched benchmark captured | Ran to 64.5%, then monitoring stop | Not yet run |

Grouping removes 75.7% of command boundaries. Maximum
planned deviation from the quantized reference is 0.248 mm and
0.096°. Endpoints and protected corners/reversals remain.
The first 5 mm and final 10 mm retain their original points. Full-path kinematic
checks pass in both directions. Live monitoring continues against the original path.

The previous partial hardware trial took 246.7 s including
upload/preparation (61.5 s).
Near-stationary telemetry intervals totalled 12.1 s during the
motion window; 5 Hz sampling cannot resolve every brief stop or controller jerk.
This is a measured baseline, not a forecast of the grouped trajectory's duration.

No Lua republish is needed. This groups points on the host before uploading them
to the already-published version 220101. A hardware trial is still required to
judge smoothness; no claim of Home-equivalent smoothness is made.
