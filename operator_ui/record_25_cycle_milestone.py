"""Record the verified 25-cycle milestone; no hardware commands."""
from datetime import datetime, timezone
import json
from pathlib import Path

from lacry_memory import LacryMemory

ROOT = Path(__file__).resolve().parent
folder = ROOT/'reports/autonomous_squid/20261024T095731_febc7c11'
source = folder/'workflow.json'
run = json.loads(source.read_text(encoding='utf-8'))
assert run['status'] == 'completed' and run['result']['ok'] is True
assert run['completed_cycles'] == run['plan']['repetitions'] == len(run['cycles']) == 25
assert all(c['status'] == 'completed' for c in run['cycles'])
images = sum(c['ticket']['last_observation']['job']['stats']['total_images'] for c in run['cycles'])
profile = run['plan']['imaging']['profile']
assert profile['stage_simulated'] is False and profile['camera_simulated'] is True
note = (
    'Verified milestone on 2026-10-24: 25/25 consecutive agentic Squid cycles completed '
    'after one initial calibration, alignment, descent, grip and return Home. '
    'Each cycle delivered and released the plate at Squid, returned Home empty, '
    'ran imaging, waited for verified imaging completion and loading-position return, '
    'retrieved the plate and returned Home. All 332 steps completed; total duration '
    '35 minutes 56 seconds. Physical robot and physical Squid XYZ stage; simulated '
    f'camera, {images} simulated images (5 per cycle). Operator reported success. '
    'Historical result only; not optical imaging validation or authorization for future motion.'
)
memory = LacryMemory(ROOT/'logs/lacry_memory/memory.sqlite3')
row = memory.add('Milestone: 25 successful agentic Squid rounds', note,
                 kind='observation', status='observed', source=str(source.relative_to(ROOT)),
                 unique_key='milestone:25-squid-rounds:20261024T095731_febc7c11')
report = dict(schema_version=1, status='verified_success', title=row['title'],
              recorded_at=datetime.now(timezone.utc).isoformat(), summary=note,
              workflow_report=str(source.relative_to(ROOT)), plan_id=run['plan_id'],
              completed_cycles=25, completed_steps=len(run['result']['done']),
              duration_seconds=run['finished_at']-run['confirmed_at'],
              physical_arm=True, physical_squid_stage=True, camera_simulated=True,
              simulated_images=images, memory_id=row['id'], motion_authorized=False)
path = folder/'milestone_25_rounds.json'
temporary = path.with_suffix('.tmp')
temporary.write_text(json.dumps(report, indent=2), encoding='utf-8')
temporary.replace(path)
print(json.dumps(dict(report=str(path),memory_id=row['id'],cycles=25,images=images)))
