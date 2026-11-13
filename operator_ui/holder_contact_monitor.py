"""Phase-specific E2 feedback: precise setup, bounded contact deflection.

Never rotates a held plate or retries a robot command. Fresh settled readings
are required again before calibration or a new pickup.
"""
import math
from calibration_e2 import accepted

CONTACT_TOLERANCE_DEG = .5

def holder_ok(value, target, contact=False):
    if type(value) not in (int,float) or not math.isfinite(value):return False
    if contact or target != 1.77:return abs(value-target)<=CONTACT_TOLERANCE_DEG
    return accepted(value)
