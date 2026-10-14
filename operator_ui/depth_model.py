"""Load the official V2 Small implementation without modifying its checkout."""
import importlib
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / 'third_party' / 'Depth-Anything-V2'
CHECKPOINT = ROOT / 'models' / 'depth_anything_v2' / 'depth_anything_v2_vits.pth'
SOURCE_COMMIT = 'a561b849ebae10a6f5ef49e26c83cbbcd36c71bf'
SMALL = dict(encoder='vits', features=64, out_channels=[48, 96, 192, 384])


def build_model(metric=False, max_depth=2.0):
    # Isolated package names allow relative and metric heads in one test process.
    path = REPO / ('metric_depth/depth_anything_v2' if metric else 'depth_anything_v2')
    if not (path / 'dpt.py').is_file():
        raise RuntimeError('Depth Anything source missing; run operator_ui/setup_depth.ps1')
    name = '_bioyond_depth_metric' if metric else '_bioyond_depth_relative'
    if name not in sys.modules:
        package = ModuleType(name)
        package.__path__ = [str(path)]
        sys.modules[name] = package
    cls = importlib.import_module(name + '.dpt').DepthAnythingV2
    return cls(**SMALL, **({'max_depth': max_depth} if metric else {}))
