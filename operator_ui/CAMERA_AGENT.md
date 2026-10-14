# Scene camera agent

The former Calibrate/Align/Descend/Grip agent tools have been removed.

Use **Scene camera agent** in Flask:
- **Save training capture**: lossless camera image and metadata, no API key.
- **Local depth**: capture plus local Depth Anything V2 Small inference.
- **Analyze with Haiku**: capture, local depth, then one text-only Haiku scene description.

Haiku receives the image, a normalized depth visualization, depth metadata and
available robot coordinates. It has no tools and cannot execute robot commands.
The manual robot console remains separate.

Start with `.venv-depth/Scripts/python.exe operator_ui/app.py`.
Setup, dataset format, measured labeling, fine-tuning commands and evaluation:
[DEPTH_TRAINING.md](DEPTH_TRAINING.md).

The pretrained model estimates relative inverse depth, not millimeters, camera
intrinsics or safe robot clearance. Training requires independently measured
depth labels; images alone and model predictions are not ground truth.
