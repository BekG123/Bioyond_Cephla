"""Compatibility import; implementation: Pick and Hold/Calibration."""
import sys
from pick_and_hold.Calibration import fast_disk as _implementation
sys.modules[__name__] = _implementation
