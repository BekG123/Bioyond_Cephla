"""Record user acceptance and install the skill. No hardware calls."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib,json,shutil
root=Path(__file__).resolve().parents[1]
folder=root/'operator_ui/reports/squid_48well_approach/station_handling_five_20261110'
batches=[json.loads((folder/n/'run.json').read_bytes()) for n in ('cycles_1_1','cycles_2_5')]
assert [c for b in batches for c in b['completed_cycles']]==[1,2,3,4,5]
assert all(b['status']=='completed_pending_operator_assessment' for b in batches)
final=batches[-1]['final_state']['robot']
assert not final['errors']
files=sorted(p for p in folder.rglob('*.json') if p.name!='operator_acceptance.json')
files+=sorted((root/'operator_ui/reports/trajectory_smoothing/hamilton_reteach_20261108').glob('*handling5_c*_20261110.json'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
record=dict(schema='cephla.operator-accepted-workflow.v1',recorded_at_utc=datetime.now(timezone.utc).isoformat(),operator_statement='Yes, this was succeseful. Save it as a skill as well.',scope='All five cycles: clean releases and secure pickups at Hamilton and Squid',completed_cycles=[1,2,3,4,5],elapsed_s=round(sum(b['finished_at']-b['at'] for b in batches),2),final_robot=final,final_plate_state='Held at true Home; operator confirmed secure',telemetry_modified=False,instrument_processing_performed=False,artifact_sha256={p.relative_to(root).as_posix():sha(p) for p in files})
target=folder/'operator_acceptance.json'
with target.open('x',encoding='utf-8') as f:json.dump(record,f,indent=2)
name='two-station-plate-handling-v1'
source=root/'Codex SKILLS'/name
installed=Path.home()/'.codex/skills'/name
shutil.copytree(source,installed,dirs_exist_ok=True)
assert sha(source/'SKILL.md')==sha(installed/'SKILL.md')
with (root/'operator_ui/reports/trajectory_smoothing/Observations.md').open('a',encoding='utf-8') as f:
 f.write('\n## Five two-station handling cycles accepted - November 9 local / 10 UTC 2026\n\n- Operator accepted all five Hamilton and Squid release/pickup cycles. Clean releases, secure level pickups, no controller errors; 611.95 seconds excluding inspection. Final true Home, E1 3.899 mm.\n- November 8 geometry, Squid one-queue protocol220109, transit137/vertical5, release7/grip3.9mm. No dispensing or imaging.\n- [Acceptance and hashes](../squid_48well_approach/station_handling_five_20261110/operator_acceptance.json). Telemetry unchanged. Skill `two-station-plate-handling-v1` installed and mirrored in `Codex SKILLS`.\n')
print(json.dumps(dict(skill=str(installed),acceptance=str(target),elapsed_s=record['elapsed_s'],motion_sent=False)))
