"""Realtime DINOv3 similarity highlighting on the Arducam feed.

DINOv3 is a vision backbone (features, not a detector). This demo: click an
object and every region of the frame with similar DINOv3 features lights up --
a quick way to "find more of the same thing" with no training.

Usage:
  python realtime_dinov3.py [--camera 0]

Keys:
  q  quit
  c  clear the reference point
"""

import argparse
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
PATCH = 16
INPUT = 640  # frames are resized to INPUT x INPUT for the backbone


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--model", type=str, default=str(MODELS_DIR / "dinov3-vits16"))
    ap.add_argument("--sim-threshold", type=float, default=0.6)
    args = ap.parse_args()

    from transformers import AutoImageProcessor, AutoModel

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading DINOv3 from {args.model} on {device}...")
    model = AutoModel.from_pretrained(args.model).to(device).eval()
    processor = AutoImageProcessor.from_pretrained(args.model)

    from camutil import open_camera

    cap = open_camera(args.camera)

    grid = INPUT // PATCH
    ref = {"xy": None}

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            ref["xy"] = (x, y)

    win = "DINOv3 similarity"
    cv2.namedWindow(win)
    cv2.setMouseCallback(win, on_mouse)

    print("Running. Click an object to highlight similar regions. q=quit, c=clear.")
    with torch.inference_mode():
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            h, w = frame.shape[:2]
            shown = frame
            if ref["xy"] is not None:
                image = Image.fromarray(
                    cv2.cvtColor(cv2.resize(frame, (INPUT, INPUT)), cv2.COLOR_BGR2RGB)
                )
                inputs = processor(images=image, return_tensors="pt").to(device)
                out = model(**inputs)
                feats = out.last_hidden_state[0]
                # drop CLS + register tokens; keep the patch grid
                n_special = feats.shape[0] - grid * grid
                patches = feats[n_special:]
                patches = torch.nn.functional.normalize(patches, dim=-1)

                px = min(int(ref["xy"][0] / w * grid), grid - 1)
                py = min(int(ref["xy"][1] / h * grid), grid - 1)
                ref_vec = patches[py * grid + px]
                sim = (patches @ ref_vec).reshape(grid, grid).float().cpu().numpy()

                heat = cv2.resize(sim, (w, h), interpolation=cv2.INTER_CUBIC)
                mask = heat > args.sim_threshold
                shown = frame.copy()
                shown[mask] = 0.45 * shown[mask] + 0.55 * np.array((5, 188, 251))
                cv2.circle(shown, ref["xy"], 5, (0, 0, 255), -1)
                cv2.putText(shown, f"similarity > {args.sim_threshold}", (10, 24),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            else:
                cv2.putText(shown, "Click an object to find similar regions", (10, 24),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            cv2.imshow(win, shown)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("c"):
                ref["xy"] = None

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
