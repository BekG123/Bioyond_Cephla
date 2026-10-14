"""Compatibility import; implementation: Pick and Hold/Hold."""
import sys
from pick_and_hold.Hold import pickup as _implementation
sys.modules[__name__] = _implementation
