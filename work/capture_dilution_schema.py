"""GET-only native schema fixtures; never creates, simulates or runs a protocol."""
import json
from pathlib import Path
import sys
from datetime import datetime,timezone

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'operator_ui'))
from hamilton_prep import HamiltonPrep
h=HamiltonPrep()
folder=root/'operator_ui/tests/fixtures/dilution'
folder.mkdir(parents=True,exist_ok=True)
result=dict(captured_at=datetime.now(timezone.utc).isoformat(),read_only=True,
    catalog=h.call('GET','protocols'),labware={str(i):h.call('GET',f'labware/{i}') for i in (128,8)},
    protocols={str(i):h.call('GET',f'protocols/{i}') for i in (12,13)})
(folder/'native_catalog.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
old=root/'operator_ui/reports/hamilton_api/simulation_3d6712d222124c73ba4f0a04ad03d531'
for name in ('result.json','load_instructions.json'):
    value=json.loads((old/name).read_text(encoding='utf-8'))
    (folder/('historical_'+name)).write_text(json.dumps(value,indent=2),encoding='utf-8')
print(json.dumps(dict(saved=str(folder),protocols=[12,13],labware=[128,8],live_methods=['GET'],historical_simulation=True)))
