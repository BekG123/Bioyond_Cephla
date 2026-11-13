"""Save the operator's accepted experiment and repository skill copy; no hardware."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

root=Path(__file__).resolve().parents[1]
name='hamilton-squid-roundtrip-v1'
installed=Path.home()/'.codex/skills'/name
destination=root/'Codex SKILLS'/name
shutil.copytree(installed,destination,dirs_exist_ok=True)
folder=root/'operator_ui/reports/squid_48well_approach/hamilton_squid_full_repeat03_20261109'
run=json.loads((folder/'run.json').read_bytes())
assert run['status']=='completed_pending_operator_assessment'
assert not run['final_robot']['errors']
ham=root/'operator_ui/reports/trajectory_smoothing/hamilton_reteach_20261108'
paths=sorted(p for p in folder.rglob('*.json') if p.name!='operator_acceptance.json')
paths += [ham/'reverse_squid_full_repeat03_20261109.json',ham/'forward_squid_full_repeat03_20261109.json']
sources=[root/'operator_ui'/p for p in ('hamilton_squid_full_repeat03_20261109.py',
    'hamilton_reteach_trial.py','squid_handling_route.py','dropoff_approach_20261103.py',
    'release_empty_home_20261103.py','pickup_squid_home_20261103.py','execute_continuous_squid_return_20261103.py')]
def hashes(items):
    return {str(p.relative_to(root)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in items}
acceptance=dict(schema='cephla.operator-accepted-workflow.v1',
    recorded_at_utc=datetime.now(timezone.utc).isoformat(),
    operator_statement='Save this full workflow as a skill, it worked succesfully',
    outcome='Operator accepted full Hamilton/Squid drop-off and retrieval round trip',
    elapsed_s=round(run['finished_at']-run['at'],2),completed_round_trips=1,
    final_pose=run['final_robot']['pose_mm'],final_e1_mm=run['final_robot']['external_axes']['E1'],
    controller_errors=run['final_robot']['errors'],final_plate_state='Held at Hamilton; no final release',
    sequence=['Hamilton','Home','Squid release','empty Home','Squid pickup','loaded Home','Hamilton'],
    artifact_sha256=hashes(paths),implementation_sha256=hashes(sources),
    telemetry_modified=False,skill=str(destination.relative_to(root)).replace('\\','/'),
    runtime_dependencies='Existing local Flask owner, published Lua trajectory program, robot configuration and pinned November 8 station geometry; this record does not certify a clean deployment.')
target=folder/'operator_acceptance.json'
with target.open('x',encoding='utf-8') as stream:
    json.dump(acceptance,stream,indent=2);stream.write('\n')
obs=root/'operator_ui/reports/trajectory_smoothing/Observations.md'
heading='## Hamilton–Squid full handling round trip accepted — 9 November 2026'
assert heading not in obs.read_text(encoding='utf-8')
with obs.open('a',encoding='utf-8') as stream:
    stream.write('\n'+heading+'\n\n'
        '- Operator confirmed the full workflow worked successfully and requested a reusable skill. One complete round took **102.09 seconds**, with no controller errors.\n'
        '- Sequence: held plate at Hamilton -> Home -> Squid release to 7 mm -> empty Home -> Squid pickup to 3.9 mm -> loaded Home -> Hamilton, ending with jaws closed. Accepted November 8 routes; Hamilton/transit 137, Squid descent/lift and gripper 5.\n'
        '- Final Hamilton X186.420/Y-366.270/Z45.200/Rz-1.100; E1 approximately 3.893 mm. No imaging, dispensing, calibration or Hamilton release in this round.\n'
        '- [Operator acceptance and evidence hashes](../squid_48well_approach/hamilton_squid_full_repeat03_20261109/operator_acceptance.json), [original run](../squid_48well_approach/hamilton_squid_full_repeat03_20261109/run.json). Telemetry remains unchanged. Skill: `hamilton-squid-roundtrip-v1`, installed and mirrored in `Codex SKILLS`. Existing local controller/configuration dependencies apply.\n')
assert (installed/'SKILL.md').read_bytes()==(destination/'SKILL.md').read_bytes()
print(json.dumps(dict(skill=str(destination),installed=str(installed),acceptance=str(target),motion_sent=False)))
