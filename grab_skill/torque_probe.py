"""Soft-contact detection from the J1-J4 torque report (SysVarI 13-16, x1000).

Usage:
  py torque_probe.py baseline S1 S2 ... Sn     n samples of "j1,j2,j3,j4" -> stats json
  py torque_probe.py check BASELINE_JSON j1,j2,j3,j4   -> contact verdict

Baseline: mean and spread per joint from a few stationary reports at hover.
Check: flags a joint when |sample - mean| > max(3*std, MIN_BAND) — the noise
band is measured, not assumed. MIN_BAND guards against a degenerate zero-std
baseline (identical samples).
"""
import json
import sys

import numpy as np

MIN_BAND = 25.0  # x1000 normalized-torque counts; ~1.5% of E1's free-motion level


def parse(s):
    return np.array([float(v) for v in s.split(",")], float)


if sys.argv[1] == "baseline":
    samples = np.array([parse(s) for s in sys.argv[2:]])
    stats = {
        "mean": samples.mean(axis=0).tolist(),
        "std": samples.std(axis=0).tolist(),
        "band": np.maximum(3.0 * samples.std(axis=0), MIN_BAND).tolist(),
        "n": len(samples),
    }
    print(json.dumps(stats))
elif sys.argv[1] == "check":
    stats = json.loads(sys.argv[2])
    x = parse(sys.argv[3])
    mean = np.array(stats["mean"])
    band = np.array(stats["band"])
    dev = x - mean
    hits = [f"J{i+1}" for i in range(4) if abs(dev[i]) > band[i]]
    print(json.dumps({
        "contact": bool(hits), "joints": hits,
        "deviation": [round(float(d), 1) for d in dev],
        "band": [round(float(b), 1) for b in band],
    }))
