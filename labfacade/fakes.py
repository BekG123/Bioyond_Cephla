"""A scriptable fake machine. No sockets, no hardware.

Every command it receives is appended to .commands, which is the ground truth
a test checks. Behaviours per operation:

    FakeMachine(behaviors={'park': dict(hang=1.0)})              # never answers in time
    FakeMachine(behaviors={'park': dict(raises='jaw slipped')})  # fails
    FakeMachine(behaviors={'park': dict(result={'parked': True},
                                        conditions_after={'parked': True},
                                        state_after='idle')})
"""
from __future__ import annotations

import threading
import time


class FakeMachine:
    def __init__(self, state='idle', detail='', sensors=None, conditions=None, behaviors=None,
                 unbound=(), clock=time.time, frames=True):
        self.state, self.detail = state, detail
        self.sensor_values = dict(sensors or {})
        self.conditions = dict(conditions or {})
        self.behaviors = dict(behaviors or {})
        self.unbound = set(unbound)
        self.clock = clock
        self.status_age_s = 0           # set > stale limit to simulate a stale reading
        self.sources = {}               # e.g. {'counter': 'idle', 'encoder': 'busy'}
        self.status_fails = False
        self.commands = []
        self.aborts = 0
        self.release = threading.Event()
        if not frames:
            self.capture_frame = None

    def read_status(self):
        if self.status_fails:
            raise ConnectionError('fake: connection dropped')
        return dict(state=self.state, detail=self.detail, read_at=self.clock() - self.status_age_s,
                    sources=dict(self.sources), source='fake')

    def sensors(self):
        return dict(self.sensor_values)

    def check(self, text):
        return self.conditions.get(text)

    def bound(self, name):
        return name not in self.unbound

    def run(self, name, params, timeout_s):
        self.commands.append(dict(name=name, params=dict(params)))
        behavior = self.behaviors.get(name, {})
        if behavior.get('hang'):
            self.release.wait(behavior['hang'])
            raise TimeoutError('fake: no reply')
        if behavior.get('delay'):
            time.sleep(behavior['delay'])
        if behavior.get('raises'):
            raise RuntimeError(behavior['raises'])
        self.conditions.update(behavior.get('conditions_after', {}))
        self.state = behavior.get('state_after', self.state)
        return dict(behavior.get('result', {'ok': True}))

    def abort(self):
        self.aborts += 1
        self.release.set()
        return dict(aborted=True)

    def capture_frame(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        from PIL import Image
        image = Image.new('L', (64, 64))
        image.putdata([255 * ((x // 8 + y // 8) % 2) for y in range(64) for x in range(64)])
        image.save(path, 'PNG')
        return True
