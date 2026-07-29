# Arducam realtime object detection

Realtime detection/segmentation on the Arducam feed with **SAM 3**, **SAM 2.1**
and **DINOv3**, running on the local RTX 4070 GPU.

## Setup (one time)

```powershell
cd C:\Users\raman\Desktop\test1
.\venv\Scripts\Activate.ps1
```

Two of the three models are **gated** on Hugging Face — accept the license on
each page (free, instant for SAM 3; DINOv3 may need approval), then log in:

1. https://huggingface.co/facebook/sam3 → "Agree and access"
2. https://huggingface.co/facebook/dinov3-vits16-pretrain-lvd1689m → request access
3. `hf auth login`  (paste a token from https://huggingface.co/settings/tokens)

Then download everything into `..\models`:

```powershell
python arducam\download_models.py
```

## Find your camera

Close the **Windows Camera app** first (only one program can use the camera).

```powershell
python arducam\camera_test.py --list      # which index is the Arducam?
python arducam\camera_test.py --camera 0  # live preview, q to quit
```

## Run realtime detection

| Script | What it does |
|---|---|
| `realtime_sam3.py` | Text-prompted detection: type "person", "bottle", ... → boxes + masks on every instance. Keys: `p` new prompt, `q` quit. |
| `realtime_sam2.py` | Click any object → it gets segmented live. Keys: `c` clear, `q` quit. |
| `realtime_dinov3.py` | Click an object → all visually similar regions light up. Keys: `c` clear, `q` quit. |

```powershell
python arducam\realtime_sam3.py --prompt "person"
python arducam\realtime_sam2.py
python arducam\realtime_dinov3.py
```

Common flags: `--camera N`, `--width/--height`, `--threshold` (SAM 3).

## Notes

- SAM 3 is a large model (~3.4 GB); on the 8 GB RTX 4070 expect a few FPS —
  smooth enough to feel live, but not 30 FPS. SAM 2.1-small and DINOv3-S are
  much faster. For high-FPS classic object detection, a YOLO-class model is
  the usual choice — easy to add later.
- If the camera won't open: wrong index (`--list`), or another app holds it.
