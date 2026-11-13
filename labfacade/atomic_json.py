"""Retry Windows file-sharing conflicts only; never rerun a physical operation."""
import json
import os
from pathlib import Path
import tempfile
import time


def write_json(path, value):
    path = Path(path)
    encoded = json.dumps(value, indent=2, allow_nan=False)
    fd, name = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(.01 * (attempt+1))
    finally:
        if temporary.exists():
            temporary.unlink()
