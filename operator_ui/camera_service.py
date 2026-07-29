"""GigE eye-in-hand camera service for the S4 operator console.

Wraps bioyond-s4-mcp/hikcam.py (MVS SDK). GigE Vision allows ONE control
connection — close the MVS client's live view before using the console, and
press Release in the UI to hand the camera back.

Capture model: on-demand with a freshness cache. The browser's live view
polls frame_jpeg(); sequences call snap() which always grabs fresh frames
(discarding one, since free-run grabbing can hand back a buffered stale
frame right after a motion).
"""

from __future__ import annotations

import os
import sys
import threading
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_DIR = os.path.join(os.path.dirname(HERE), "bioyond-s4-mcp")
if MCP_DIR not in sys.path:
    sys.path.insert(0, MCP_DIR)

import hikcam  # noqa: E402

CAPTURE_DIR = os.path.join(HERE, "captures")
os.makedirs(CAPTURE_DIR, exist_ok=True)


class CameraService:
    def __init__(self) -> None:
        self.cam = hikcam.HikCamera()
        self.lock = threading.Lock()
        self.enabled = True   # False after Release, until Resume
        self.last_frame: np.ndarray | None = None   # BGR, native resolution
        self.last_jpeg: bytes | None = None
        self.last_ts: float = 0.0
        self.error: str = ""
        self._counter = 0

    # ----------------------------------------------------------- capture

    def _grab(self, discard: int = 0) -> np.ndarray:
        """Grab a frame (caller holds the lock). Errors drop the handle so
        the next attempt reopens cleanly."""
        try:
            for _ in range(discard):
                self.cam.capture()
            frame = self.cam.capture()
            self.last_frame = frame
            ok, buf = cv2.imencode(".jpg", frame,
                                   [cv2.IMWRITE_JPEG_QUALITY, 82])
            if ok:
                self.last_jpeg = buf.tobytes()
            self.last_ts = time.time()
            self.error = ""
            return frame
        except Exception as ex:
            self.error = str(ex)[:300]
            try:
                self.cam.release()
            except Exception:
                pass
            raise

    def frame_jpeg(self, max_age: float = 0.6) -> tuple[bytes | None, str]:
        """Cached-or-fresh JPEG for the live view."""
        with self.lock:
            if not self.enabled:
                return self.last_jpeg, "camera released — press Resume"
            if (self.last_jpeg is not None
                    and time.time() - self.last_ts < max_age):
                return self.last_jpeg, ""
            try:
                self._grab()
                return self.last_jpeg, ""
            except Exception:
                return self.last_jpeg, self.error

    def snap(self) -> np.ndarray:
        """Guaranteed-fresh frame for vision solving (raises on failure)."""
        with self.lock:
            if not self.enabled:
                raise RuntimeError("camera is released — press Camera Resume")
            return self._grab(discard=1)

    # ------------------------------------------------------------- extras

    def crop_jpeg(self, cx: int, cy: int, size: int = 240,
                  scale: int = 3) -> bytes | None:
        """Zoomed crop around a full-frame pixel, from the latest frame."""
        with self.lock:
            frame = self.last_frame
            if frame is None:
                return None
            h, w = frame.shape[:2]
            half = size // 2
            x0 = max(0, min(w - size, cx - half))
            y0 = max(0, min(h - size, cy - half))
            crop = frame[y0:y0 + size, x0:x0 + size]
            big = cv2.resize(crop, (size * scale, size * scale),
                             interpolation=cv2.INTER_NEAREST)
            ok, buf = cv2.imencode(".jpg", big,
                                   [cv2.IMWRITE_JPEG_QUALITY, 88])
            return buf.tobytes() if ok else None

    def save(self, frame: np.ndarray | None = None,
             prefix: str = "snap") -> str:
        """Save a frame (default: latest) as PNG; returns the path."""
        with self.lock:
            if frame is None:
                frame = self.last_frame
            if frame is None:
                raise RuntimeError("no frame captured yet")
            self._counter += 1
            path = os.path.join(CAPTURE_DIR,
                                f"{prefix}_{self._counter:04d}.png")
            cv2.imwrite(path, frame)
            return path

    def release(self) -> None:
        with self.lock:
            self.enabled = False
            try:
                self.cam.release()
            finally:
                self.error = "released"

    def resume(self) -> None:
        with self.lock:
            self.enabled = True
            self.error = ""

    def info(self) -> dict:
        return {
            "open": self.cam.is_open,
            "enabled": self.enabled,
            "error": self.error,
            "age_s": (round(time.time() - self.last_ts, 1)
                      if self.last_ts else None),
            "device": self.cam.info,
        }
