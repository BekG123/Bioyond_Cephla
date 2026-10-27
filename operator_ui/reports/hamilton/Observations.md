# Hamilton test check — October 16, 2026

**2026-10-17 - Home queue initialization fix:** Publishing alone does not initialize the Lua version register. Home previously checked that register before its confirmed Auto preparation, incorrectly asking to publish again while the program was stopped. It now defers only the uninitialized-program check until after preparation and requires speed-137 support before any Home leg, including wrist rotation. Wrong running versions and read failures still block. 18 Home tests and 29 Lua queue tests pass; no hardware movement during implementation.

- Saved routine: `820cc19904d449cca2a8994990cc197a`, revision 7, saved 10:48:50 PDT. Original teaching data is unchanged.
- Reused Return Home's IK route planner: raise to at least Z300, rotate, translate, lower. Both Home-to-Hamilton and Grip-to-Hamilton are blocked by the current workspace.
- Hamilton: X175.629, Y−386.510, Z36.231 mm, Rz−5.316°. Extension from the J2 axis is 389.683 mm; automatic allowance is 383 mm. Being manually reachable does not validate the automatic path or its clearance.
- Descend snapshot: Z278.459 / E1≈0; Grip snapshot: Z72.139 / E1≈3.579. These snapshots omit 206.320 mm of descent and do not identify a valid stationary open-to-close grip.
- Continuous log **does** contain a closing movement at about 10:47:04–10:47:06 PDT, overlapping descent. The snapshots do not mean the operator never closed the gripper. Feedback here has no force/contact verification.
- Next: review/correct the pickup stages and commission the Hamilton travel/approach or teach a closer target. Do not silently substitute Grip's depth for Descend, expand workspace limits, or relax reach margins.
- New Researcher Run → **Check saved routine** performs read-only checks. Full pipeline execution is not implemented. No physical test was run.
