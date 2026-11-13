"""Read-only preview against existing console telemetry; no control client."""
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

from capability_workflow import CapabilityAdapter
from plate_registry import PlateRegistry


def get(path):
    with urlopen('http://127.0.0.1:5002'+path,timeout=10) as response:
        return json.load(response)


class Telemetry:
    def __init__(self):
        current=get('/state')
        if current['sequence']['active']:raise RuntimeError('Another workflow is active.')
        self.envelope_enabled=current['envelope']['enabled']
        self.envelope={k:[current['envelope'][k]['min'],current['envelope'][k]['max']] for k in ('X','Y','Z')}
    def status(self):return get('/state')['robot']
    def _preflight(self):return None
    def _endpoint_addr(self):
        host,port=self.status()['endpoint'].split(':')
        return host,int(port)


backend=SimpleNamespace(s=Telemetry(),params=lambda:get('/robot_params'))
adapter=CapabilityAdapter(backend=backend,registry=PlateRegistry())
spec=adapter.preview(['retrieve_squid','return_HOME'])
path=Path(__file__).with_name('capability_retrieval_live_preview.json')
path.write_text(json.dumps(spec,indent=2),encoding='utf-8')
print(json.dumps(dict(plate_id=spec['plate_id'],profile=spec['plate_profile'],
    initial=spec['source']['state'],final=spec['capability_chain']['final'],
    capabilities=[c['capability']['id'] for c in spec['capability_chain']['capabilities']],
    trace=spec['capability_chain']['trace'],motion_steps=[s['label'] for s in spec['motion_steps']],
    preview=str(path)),indent=2))
