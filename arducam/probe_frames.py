"""Grab warmed-up frames from every camera index/backend and save snapshots
so we can see which one is the real Arducam feed (not a black virtual cam)."""

import sys
from pathlib import Path

import cv2

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
OUT.mkdir(parents=True, exist_ok=True)

BACKENDS = [("MSMF", cv2.CAP_MSMF), ("DSHOW", cv2.CAP_DSHOW)]

for name, backend in BACKENDS:
    for i in range(4):
        cap = cv2.VideoCapture(i, backend)
        if not cap.isOpened():
            cap.release()
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        frame = None
        for _ in range(15):  # warm up: some cams need frames to auto-expose
            ok, f = cap.read()
            if ok:
                frame = f
        cap.release()
        if frame is None:
            print(f"{name} index {i}: opens, no frames")
            continue
        mean = float(frame.mean())
        std = float(frame.std())
        path = OUT / f"cam_{name}_{i}.jpg"
        cv2.imwrite(str(path), frame)
        h, w = frame.shape[:2]
        print(f"{name} index {i}: {w}x{h} mean={mean:.1f} std={std:.1f} -> {path.name}")
