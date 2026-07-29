"""Shared camera-opening helper: tries MSMF, then DSHOW, then default."""

import cv2

BACKENDS = [
    ("MSMF", cv2.CAP_MSMF),
    ("DSHOW", cv2.CAP_DSHOW),
    ("ANY", cv2.CAP_ANY),
]


def _try_open(index: int, width: int, height: int):
    for name, backend in BACKENDS:
        cap = cv2.VideoCapture(index, backend)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            frame = None
            for _ in range(10):  # warm up auto-exposure before judging content
                ok, f = cap.read()
                if ok:
                    frame = f
            # NVIDIA Broadcast's virtual cameras open fine but emit pure
            # black frames — reject anything with no image content.
            if frame is not None and frame.std() > 3.0:
                print(f"Camera {index} opened via {name} (mean={frame.mean():.0f})")
                return cap
            if frame is not None:
                print(f"Camera {index} via {name}: black/blank feed, skipping")
        cap.release()
    return None


def open_camera(index: int, width: int = 1280, height: int = 720) -> cv2.VideoCapture:
    """Open the requested index; if it fails, scan 0-5 for the first live feed.

    Camera indices shift between runs on this machine (NVIDIA Broadcast's
    virtual camera comes and goes), so a fixed index is unreliable.
    """
    cap = _try_open(index, width, height)
    if cap is not None:
        return cap
    print(f"Camera {index} unavailable, scanning other indices...")
    for i in range(6):
        if i == index:
            continue
        cap = _try_open(i, width, height)
        if cap is not None:
            return cap
    raise SystemExit(
        "No working camera found. Close the Windows Camera app "
        "(or anything else using the camera) and retry."
    )
