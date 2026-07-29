"""Realtime click-to-segment on the Arducam feed using SAM 2.1.

Click an object in the window: SAM 2 segments whatever is under the clicked
point on every new frame (the point is re-used until you click elsewhere).

Usage:
  python realtime_sam2.py [--camera 0]

Keys:
  q  quit
  c  clear the point
"""

import argparse
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--model", type=str, default=str(MODELS_DIR / "sam2.1-hiera-small"))
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    args = ap.parse_args()

    from transformers import Sam2Model, Sam2Processor

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    print(f"Loading SAM 2.1 from {args.model} on {device}...")
    model = Sam2Model.from_pretrained(args.model, dtype=dtype).to(device).eval()
    processor = Sam2Processor.from_pretrained(args.model)

    from camutil import open_camera

    cap = open_camera(args.camera, args.width, args.height)

    point = {"xy": None}

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            point["xy"] = (x, y)
            print(f"Point set: {point['xy']}")

    win = "SAM 2 click-to-segment"
    cv2.namedWindow(win)
    cv2.setMouseCallback(win, on_mouse)

    fps = 0.0
    print("Running. Click an object. Keys: q=quit, c=clear point.")
    with torch.inference_mode():
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            shown = frame
            if point["xy"] is not None:
                t0 = time.perf_counter()
                image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                inputs = processor(
                    images=image,
                    input_points=[[[list(point["xy"])]]],
                    input_labels=[[[1]]],
                    return_tensors="pt",
                ).to(device, dtype=dtype)
                outputs = model(**inputs)
                masks = processor.post_process_masks(
                    outputs.pred_masks.float().cpu(),
                    inputs["original_sizes"].cpu(),
                )[0]
                scores = outputs.iou_scores.float().cpu().numpy().ravel()
                best = int(scores.argmax())
                mask = masks[0, best].numpy().astype(bool)
                dt = time.perf_counter() - t0
                fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps else 1.0 / dt

                shown = frame.copy()
                shown[mask] = 0.5 * shown[mask] + 0.5 * np.array((52, 168, 83))
                cv2.circle(shown, point["xy"], 5, (0, 0, 255), -1)
                cv2.putText(shown, f"{fps:.1f} FPS  iou={scores[best]:.2f}",
                            (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            else:
                cv2.putText(shown, "Click an object to segment it",
                            (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            cv2.imshow(win, shown)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("c"):
                point["xy"] = None

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
