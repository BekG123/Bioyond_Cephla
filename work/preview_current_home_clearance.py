"""Read-only recovery review through the existing controller's telemetry."""
import json
from pathlib import Path
from urllib.request import urlopen

from home_clearance_recovery import preview

BASE = 'http://127.0.0.1:5002'


def get(path):
    with urlopen(BASE + path, timeout=10) as response:
        return json.load(response)


class Telemetry:
    def __init__(self):
        state = get('/state')
        if state['sequence']['active']:
            raise RuntimeError('A workflow is active.')
        self.envelope_enabled = state['envelope']['enabled']
        self.envelope = {k: [state['envelope'][k]['min'], state['envelope'][k]['max']] for k in ('X', 'Y', 'Z')}
    def status(self): return get('/state')['robot']
    def _preflight(self): return None
    def _endpoint_addr(self):
        host, port = self.status()['endpoint'].split(':')
        return host, int(port)


plan = preview(Telemetry(), get('/robot_params'))
path = Path(__file__).with_name('current_home_clearance_recovery_plan.json')
path.write_text(json.dumps(plan, indent=2), encoding='utf-8')
print(json.dumps(dict(plan=str(path), start=plan['start'], axes=plan['axes'],
                     steps=[s['label'] for s in plan['steps']], target=plan['target']), indent=2))
