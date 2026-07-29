"""Realtime text-prompted object detection on the Arducam feed using SAM 3.

SAM 3 takes a text concept (e.g. "person", "red bottle") and finds every
instance in the frame -- boxes + masks + scores.

Usage (venv activated, models downloaded):
  python realtime_sam3.py --prompt "person"
  python realtime_sam3.py --camera 1 --prompt "bottle" --threshold 0.4

Keys:
  q  quit
  p  type a new text prompt in the console
"""

import argparse
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

COLORS = [
    (66, 133, 244), (52, 168, 83), (251, 188, 5), (234, 67, 53),
    (168, 82, 217), (0, 172, 193), (255, 112, 67), (124, 179, 66),
]


def load_model(model_path: str, device: str):
    from transformers import Sam3Model, Sam3Processor

    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    print(f"Loading SAM 3 from {model_path} on {device} ({dtype})...")
    model = Sam3Model.from_pretrained(model_path, dtype=dtype).to(device).eval()
    processor = Sam3Processor.from_pretrained(model_path)
    return model, processor


@torch.inference_mode()
def detect(model, processor, frame_bgr, prompt: str, threshold: float, device: str):
    image = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    inputs = processor(images=image, text=prompt, return_tensors="pt").to(
        device, dtype=model.dtype
    )
    outputs = model(**inputs)
    results = processor.post_process_instance_segmentation(
        outputs,
        threshold=threshold,
        mask_threshold=0.5,
        target_sizes=[image.size[::-1]],
    )[0]
    return results  # dict with "masks", "boxes", "scores"


def draw(frame, results, prompt: str, fps: float):
    masks = results.get("masks")
    boxes = results.get("boxes")
    scores = results.get("scores")
    n = 0 if boxes is None else len(boxes)
    overlay = frame.copy()
    for i in range(n):
        color = COLORS[i % len(COLORS)]
        if masks is not None:
            mask = masks[i]
            if isinstance(mask, torch.Tensor):
                mask = mask.cpu().numpy()
            mask = mask.astype(bool)
            overlay[mask] = 0.5 * overlay[mask] + 0.5 * np.array(color)
        box = boxes[i]
        if isinstance(box, torch.Tensor):
            box = box.cpu().numpy()
        x1, y1, x2, y2 = box.astype(int)
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 2)
        score = float(scores[i]) if scores is not None else 0.0
        cv2.putText(overlay, f"{prompt} {score:.2f}", (x1, max(y1 - 6, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    cv2.putText(overlay, f"{fps:.1f} FPS | prompt: {prompt} | {n} found",
                (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return overlay


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--prompt", type=str, default="person")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--model", type=str, default=str(MODELS_DIR / "sam3"))
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        print("WARNING: no CUDA GPU detected -- this will be far from realtime.")
    model, processor = load_model(args.model, device)

    from camutil import open_camera

    cap = open_camera(args.camera, args.width, args.height)

    prompt = args.prompt
    fps = 0.0
    print("Running. Keys: q=quit, p=change prompt (in console).")
    while True:
        ok, frame = cap.read()
        if not ok:
            print("Frame grab failed.")
            break
        t0 = time.perf_counter()
        try:
            results = detect(model, processor, frame, prompt, args.threshold, device)
        except Exception as exc:  # noqa: BLE001
            print(f"Inference error: {exc}")
            break
        dt = time.perf_counter() - t0
        fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps else 1.0 / dt

        cv2.imshow("SAM 3 realtime detection", draw(frame, results, prompt, fps))
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("p"):
            new = input("New prompt: ").strip()
            if new:
                prompt = new

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
