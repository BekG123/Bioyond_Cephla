"""Save the operator's confirmed result; no hardware access."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil

root=Path(__file__).resolve().parents[1]
folder=root/'operator_ui/reports/plate_session/cellvis24_workflows/2094a75669894864bf1efdfcb4f2c807'
scan=folder/'supervised_grip/proof_lift/scanner_transfer'
now=datetime.now(timezone.utc).isoformat()
paths=[folder/'run.json',folder/'supervised_grip/run.json',folder/'supervised_grip/operator_observation.json',
       folder/'supervised_grip/proof_lift/run.json',scan/'run.json',scan/'arrival_verification.json']
hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
assert json.loads((scan/'run.json').read_bytes())['status']=='completed'
observation=dict(status='operator_accepted',recorded_at=now,
    user_statement='Great it worked, yes. Log this, save it as a skill, and give me args pars so i can execute myself',
    confirmed_question='Did the Cellvis plate remain level and securely held through the scanner transfer?',
    plate_level_and_secure=True,scope='Completed loaded Cellvis scanner transfer',
    motion_record_sha256=hashes[str((scan/'run.json').relative_to(root))])
with (scan/'operator_success.json').open('x',encoding='utf-8') as f:json.dump(observation,f,indent=2)
hashes[str((scan/'operator_success.json').relative_to(root))]=hashlib.sha256((scan/'operator_success.json').read_bytes()).hexdigest()
acceptance=dict(status='operator_accepted',recorded_at=now,plate='Cellvis P24-1.5H-N, lid off',
    trial_id=folder.name,sources=hashes,grip_e1_mm=3.9,
    closure=dict(approach_target_mm=4.9,approach_speed=10,final_speed=5),proof_lift=dict(mm=5,speed=5),
    scanner=dict(speed=137,queues=1,target=dict(X=80.88,Y=-143.51,Z=189.16,Rz=-1.63)),
    final_payload='Plate held',physical_retention_confirmed=True,
    validation_scope='Accepted separately supervised stages; combined reusable CLI offline-tested, not yet run live.',
    excluded=['barcode trigger','scanner return','station handling','endurance repetitions'])
with (folder/'accepted_scanner_workflow.json').open('x',encoding='utf-8') as f:json.dump(acceptance,f,indent=2)
obs=root/'Pick and Hold/Calibration/Observations.md'
with obs.open('a',encoding='utf-8') as f:
    f.write('\n\n**2026-11-11 Cellvis pickup-to-scanner accepted:** Operator confirmed the plate remained level and securely held through trial2094’s scanner transfer. Saved additive `operator_success.json` and `accepted_scanner_workflow.json` with source hashes; original motion receipts remain unchanged. Accepted sequence: shared projected calibration/alignment, Cellvis Z75.72, E1 closure to4.9 at10 then3.9 at5, proof lift5mm at5, then one Lua queue viaZ300 to scanner at137 (6.89seconds). No release or barcode trigger. New `run_cellvis24_scanner.py --full-calibration --execute` reuses these stages with visual alignment/retention checks; its combined invocation has not yet been live-tested. Skill: `cellvis24-calibration-scanner-v1`.\n')
skill=root/'Codex SKILLS/cellvis24-calibration-scanner-v1/SKILL.md'
target=Path.home()/'.codex/skills/cellvis24-calibration-scanner-v1'
target.mkdir(parents=True,exist_ok=True);shutil.copy2(skill,target/'SKILL.md')
print(json.dumps(dict(acceptance=str(folder/'accepted_scanner_workflow.json'),skill=str(target/'SKILL.md'))))
