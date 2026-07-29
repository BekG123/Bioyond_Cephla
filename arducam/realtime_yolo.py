"""Realtime object detection on the Arducam feed with Ultralytics YOLO11.

Fastest option here (well above 30 FPS on the RTX 4070): 80 COCO classes,
boxes + labels on every frame.

Usage:
  python realtime_yolo.py [--camera 0] [--model ../models/yolo11n.pt]

Keys:
  q  quit
"""

import argparse
import time
from pathlib import Path

import cv2

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--model", type=str, default=str(MODELS_DIR / "yolo26n.pt"))
    ap.add_argument("--conf", type=float, default=0.4)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--snapshot", type=str, default="",
                    help="write the latest annotated frame to this file every ~2s")
    args = ap.parse_args()

    from ultralytics import YOLO

    print(f"Loading {args.model}...")
    model = YOLO(args.model)

    from camutil import open_camera

    cap = open_camera(args.camera, args.width, args.height)

    fps = 0.0
    last_snap = 0.0
    print("Running. q to quit.", flush=True)
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t0 = time.perf_counter()
        results = model.predict(frame, conf=args.conf, verbose=False)
        dt = time.perf_counter() - t0
        fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps else 1.0 / dt

        shown = results[0].plot()
        cv2.putText(shown, f"{fps:.1f} FPS", (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.imshow("YOLO11 realtime detection", shown)
        if args.snapshot and time.perf_counter() - last_snap > 2.0:
            cv2.imwrite(args.snapshot, shown)
            last_snap = time.perf_counter()
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
