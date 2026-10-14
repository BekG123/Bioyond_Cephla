# Pick and Hold

The active stage implementations live here. Start the existing console with
`py operator_ui/app.py` from the repository root. It remains at localhost:5002.

| Stage | Implementation | Purpose |
|---|---|---|
| Calibration | `Calibration/fast_disk.py` | Complete two-disk algorithm: loop, vision/pose math, planning, guards and convergence |
| Align | `Align/motion.py` | Existing guarded hover / wrist rotation / XY alignment |
| Align | `Align/ic.py`, `Align/references.py` | New inverse-compositional image alignment, reference batches and preview |
| Descend | `Descend/motion.py` | Existing torque-guarded approach and descent |
| Grip | `Grip/motion.py` | Existing torque and position-stall grip confirmation |
| Hold | `Hold/pickup.py` | Existing supervised lift verification; requires its commissioned ArUco marker |

`operator_ui/pick_and_hold` bridges Python imports to this folder (whose name
contains spaces). The old `fast_disk` and `pickup` module names are compatibility
imports, and `sequences.py` delegates the three extracted motion functions.
There is one implementation of each extracted stage. Calibration's shared guard
and vendor-math imports delegate to `Calibration/fast_disk.py`. Hardware drivers,
settings, Runner and legacy calibration adapters remain in `operator_ui`;
historical JSON calibration data stays at its existing paths.

The IC workflow is documented in [Align/README.md](Align/README.md).
No live reference has been captured or robot motion tested by this implementation.
IC is an image measurement/preview stage. It does not yet drive robot corrections.
The existing Align button still executes the saved vendor/ArUco grasp target.

Tests from the repository root:

```powershell
py -B -m unittest discover -s operator_ui/tests -p 'test_ic*.py' -v
py -B -m unittest discover -s operator_ui/tests -p test_fast_disk.py -v
py -B -m unittest discover -s operator_ui/tests -p test_alignment.py -v
py -B -m unittest discover -s operator_ui/tests -p test_pickup.py -v
py -B -m unittest discover -s operator_ui/tests -p test_transfer.py -v
```
