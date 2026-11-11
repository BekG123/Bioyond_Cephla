"""One validated vision runtime for the console and offline evaluations."""
import importlib.metadata
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv-realsense/Scripts/python.exe'
EXPECTED = {'opencv-python-headless': '4.14.0.94', 'numpy': '2.2.6'}


def verify():
    import cv2
    import numpy
    versions = {name: importlib.metadata.version(name) for name in EXPECTED}
    if versions != EXPECTED or cv2.__version__ != '4.14.0' or numpy.__version__ != '2.2.6':
        raise RuntimeError('Vision runtime differs from the validated pins; use operator_ui/requirements-realsense.txt.')
    if not Path(cv2.__file__).resolve().is_relative_to(PYTHON.parent.parent.resolve()):
        raise RuntimeError('OpenCV was loaded outside the validated environment.')
    return dict(python=sys.executable, opencv=cv2.__version__, numpy=numpy.__version__,
                packages=versions, validated=True)


def bootstrap():
    """Redirect legacy `py app.py` launches before creating any service objects."""
    if Path(sys.executable).resolve() != PYTHON.resolve():
        if not PYTHON.is_file():
            raise RuntimeError('Missing .venv-realsense: run operator_ui/setup_realsense.ps1.')
        os.execv(str(PYTHON), [str(PYTHON), '-B', '-u', str(ROOT/'operator_ui/app.py'), *sys.argv[1:]])
    return verify()
