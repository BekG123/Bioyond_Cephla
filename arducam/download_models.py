"""Download DINOv3, SAM 2, and SAM 3 model weights into ../models.

DINOv3 and SAM 3 are *gated* on Hugging Face: you must accept the license on
the model page first, and be logged in (`hf auth login`), or the download
will fail with 401/403.

  DINOv3:  https://huggingface.co/facebook/dinov3-vits16-pretrain-lvd1689m
  SAM 3:   https://huggingface.co/facebook/sam3

SAM 2.1 is not gated and downloads without a login.
"""

import sys
from pathlib import Path

from huggingface_hub import snapshot_download

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

# (repo_id, local folder name, gated?)
MODELS = [
    ("facebook/sam2.1-hiera-small", "sam2.1-hiera-small", False),
    ("facebook/sam3", "sam3", True),
    ("facebook/dinov3-vits16-pretrain-lvd1689m", "dinov3-vits16", True),
]


def main() -> int:
    MODELS_DIR.mkdir(exist_ok=True)
    failures = []
    for repo_id, folder, gated in MODELS:
        target = MODELS_DIR / folder
        print(f"\n=== {repo_id} -> {target} ===")
        try:
            snapshot_download(repo_id=repo_id, local_dir=target)
            print(f"OK: {repo_id}")
        except Exception as exc:  # noqa: BLE001
            failures.append((repo_id, gated, exc))
            print(f"FAILED: {repo_id}: {exc}")

    if failures:
        print("\n--- Some downloads failed ---")
        for repo_id, gated, exc in failures:
            print(f"* {repo_id}: {type(exc).__name__}")
            if gated:
                print(
                    f"  This model is gated. Visit https://huggingface.co/{repo_id} ,\n"
                    "  accept the license, then run:  hf auth login\n"
                    "  and re-run this script."
                )
        return 1
    print("\nAll models downloaded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
