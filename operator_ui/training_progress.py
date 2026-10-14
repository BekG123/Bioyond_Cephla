"""Atomic, read-only-dashboard-friendly progress for local depth training."""
import json
import os
from pathlib import Path
import time


class TrainingProgress:
    def __init__(self, output, epochs, synthetic=False, enabled=True):
        self.output = Path(output)
        self.enabled = enabled
        self.started = time.time()
        self.state = dict(run=self.output.name, status='starting', epochs=epochs,
                          epoch=0, step=0, steps=0, history=[], pid=os.getpid(),
                          synthetic=synthetic, started_at=self.started,
                          checkpoint=None, best_mae_mm=None)

    def __enter__(self):
        if self.enabled:
            self.output.mkdir(parents=True, exist_ok=True)
            if any((self.output / name).exists() for name in ('progress.json', 'history.jsonl', 'best.pt')):
                raise ValueError('Output already contains a run; use a new run directory')
            self.update()
        return self

    def update(self, **values):
        if not self.enabled:
            return
        self.state.update(values)
        self.state.update(updated_at=time.time(), elapsed_seconds=round(time.time() - self.started, 1))
        temporary = self.output / 'progress.tmp'
        temporary.write_text(json.dumps(self.state, allow_nan=False), encoding='utf-8')
        # Readers close the file before each update; a brief retry covers Windows sharing races.
        for attempt in range(5):
            try:
                temporary.replace(self.output / 'progress.json')
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(.02)

    def __exit__(self, kind, error, traceback):
        if error is not None:
            self.update(status='stopped' if kind is KeyboardInterrupt else 'failed', error=str(error))
        else:
            self.update(status='completed')
        return False
