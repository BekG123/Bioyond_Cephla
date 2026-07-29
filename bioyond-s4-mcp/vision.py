"""Arducam capture for the Bioyond S4 cell.

The camera (Arducam B0478 USB3 48MP) is selected by DirectShow device name
so virtual cameras (NVIDIA Broadcast, ToDesk) can never be picked by
accident. Frames are BGR numpy arrays at 1920x1080.

Object DETECTION is deliberately NOT done here — the agent views the
captured images itself (multimodal) and reads pixel coordinates from the
grid overlays this module draws.

Only one process can hold the camera at a time — the MCP server keeps it
open between captures for speed; call release() to free it for other apps.
"""

from __future__ import annotations

import os
import time
from typing import Optional

import cv2
import numpy as np

CAMERA_NAME_SUBSTRING = os.environ.get("BIOYOND_CAMERA_NAME", "Arducam")
CAPTURE_WIDTH = int(os.environ.get("BIOYOND_CAMERA_WIDTH", "1920"))
CAPTURE_HEIGHT = int(os.environ.get("BIOYOND_CAMERA_HEIGHT", "1080"))
WARMUP_SECONDS = float(os.environ.get("BIOYOND_CAMERA_WARMUP", "3"))


class CameraError(Exception):
    pass


def find_camera_index(ordinal: int = 0) -> int:
    """Resolve a physical camera's DirectShow index by device name.

    ordinal selects among multiple devices with matching names (0 = first
    match in enumeration order). NOTE: enumeration order of identical
    devices can change across reboots/replugs — verify by image which
    physical camera an ordinal maps to.
    """
    try:
        from pygrabber.dshow_graph import FilterGraph
        names = FilterGraph().get_input_devices()
    except Exception as ex:  # pragma: no cover - depends on host
        raise CameraError(f"could not enumerate cameras: {ex}") from ex
    matches = [i for i, name in enumerate(names)
               if CAMERA_NAME_SUBSTRING.lower() in name.lower()]
    if len(matches) <= ordinal:
        raise CameraError(
            f"need camera #{ordinal + 1} matching '{CAMERA_NAME_SUBSTRING}' "
            f"but found {len(matches)}; devices: {names}"
        )
    return matches[ordinal]


class Camera:
    def __init__(self, ordinal: int = 0) -> None:
        self._cap: Optional[cv2.VideoCapture] = None
        self._index: Optional[int] = None
        self.ordinal = ordinal

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def open(self) -> None:
        if self.is_open:
            return
        idx = find_camera_index(self.ordinal)
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            raise CameraError(f"failed to open camera index {idx}")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
        # warm up so auto-exposure settles (first frames are black)
        t0 = time.time()
        got = False
        while time.time() - t0 < WARMUP_SECONDS:
            ok, f = cap.read()
            got = got or (ok and f is not None and f.mean() > 5)
        if not got:
            cap.release()
            raise CameraError(
                "camera opened but frames are black — check lens cap/lighting"
            )
        self._cap = cap
        self._index = idx

    def capture(self, discard: int = 3) -> np.ndarray:
        """Grab a fresh frame (discards buffered frames first)."""
        self.open()
        assert self._cap is not None
        frame = None
        for _ in range(discard + 1):
            ok, f = self._cap.read()
            if ok and f is not None:
                frame = f
        if frame is None:
            self.release()
            raise CameraError("failed to read a frame — camera disconnected?")
        return frame

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


def _label(img, text, org, scale=0.6, color=(0, 255, 255)):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale,
                (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale,
                color, 1, cv2.LINE_AA)


def draw_grid(frame: np.ndarray, step: int = 100,
              origin: tuple[int, int] = (0, 0)) -> np.ndarray:
    """Overlay a labeled pixel-coordinate grid so the viewing agent can read
    off coordinates. `origin` offsets the labels (used for crops so labels
    show FULL-FRAME coordinates)."""
    out = frame.copy()
    h, w = out.shape[:2]
    ox, oy = origin
    for x in range(0, w, step):
        cv2.line(out, (x, 0), (x, h), (255, 255, 0), 1)
        _label(out, str(x + ox), (x + 3, 18))
    for y in range(0, h, step):
        cv2.line(out, (0, y), (w, y), (255, 255, 0), 1)
        _label(out, str(y + oy), (3, y + 18))
    # center crosshair of the full frame (only meaningful when origin is 0,0)
    if origin == (0, 0):
        cv2.drawMarker(out, (w // 2, h // 2), (255, 255, 255),
                       cv2.MARKER_CROSS, 40, 2)
    return out


def crop_zoom(frame: np.ndarray, cx: int, cy: int, size: int = 300,
              zoom: int = 3, grid_step: int = 20) -> tuple[np.ndarray, tuple[int, int]]:
    """Crop a square around (cx, cy), upscale it, and overlay a fine grid
    labeled in FULL-FRAME pixel coordinates. Returns (image, (x0, y0))."""
    h, w = frame.shape[:2]
    half = size // 2
    x0 = max(0, min(w - size, cx - half))
    y0 = max(0, min(h - size, cy - half))
    crop = frame[y0:y0 + size, x0:x0 + size]
    big = cv2.resize(crop, None, fx=zoom, fy=zoom,
                     interpolation=cv2.INTER_NEAREST)
    out = big.copy()
    bh, bw = out.shape[:2]
    for gx in range(0, size + 1, grid_step):
        x = gx * zoom
        if x < bw:
            cv2.line(out, (x, 0), (x, bh), (255, 255, 0), 1)
            _label(out, str(x0 + gx), (x + 2, 16), 0.45)
    for gy in range(0, size + 1, grid_step):
        y = gy * zoom
        if y < bh:
            cv2.line(out, (0, y), (bw, y), (255, 255, 0), 1)
            _label(out, str(y0 + gy), (2, y + 16), 0.45)
    # mark the requested center point
    cv2.drawMarker(out, ((cx - x0) * zoom, (cy - y0) * zoom), (0, 0, 255),
                   cv2.MARKER_CROSS, 30, 2)
    return out, (x0, y0)
