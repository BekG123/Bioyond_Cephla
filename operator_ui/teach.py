"""Compatibility import: two-disk vision and calibration live in one file."""
import sys
from pick_and_hold.Calibration import fast_disk as _implementation
# Preserve the historical import path used by existing standalone helpers.
if _implementation.GRAB_DIR not in sys.path:
    sys.path.insert(0, _implementation.GRAB_DIR)
sys.modules[__name__] = _implementation
