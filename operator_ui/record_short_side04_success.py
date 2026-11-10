"""Save operator-confirmed pickup/Hamilton/Home result; no hardware access."""
import hashlib
import json
import time
from short_side_full_trial import receipt,reference
from short_side_direct_transfer import SELECTION
from hamilton_short_side_trial import ROOT,FOLDER

p,parent,grip=reference('04')
sources={phase:receipt(phase,'04') for phase in ('approach','grip_lift','hamilton','operator_acceptance','departure','return_plan','return_home')}
data={name:json.loads(path.read_bytes()) for name,path in sources.items()}
assert all(data[name]['status']=='completed' for name in ('approach','grip_lift','hamilton','departure'))
assert data['operator_acceptance']['accepted'] is True
returned=data['return_home']
assert returned['status']=='completed_awaiting_operator_inspection'
assert returned['home']['result']['ok'] and returned['home']['state']=='done'
assert not returned['final_state']['robot']['errors'] and not returned['final_native']['moving']
assert abs(returned['final_native']['external_axes']['E1']-25)<.07
assert max(abs(returned['final_state']['robot']['pose_mm'][k]-parent['home'][k]) for k in ('X','Y','Z','Rz'))<.1
out=FOLDER/'successful_short_side_hamilton04.json'
record=dict(status='operator_confirmed_success',at=time.time(),revision='04',
    accepted_sequence=['Home','open_jaws_28','taught_pickup_approach_and_descent','grip_25','lift_5mm_speed5','Hamilton_overhead_entry_and_seating','reverse_entry_to_taught_turn','IK_return_true_Home'],
    operator_arrival_quote=data['operator_acceptance']['operator_quote'],
    operator_return_quote='Yes—level and secure throughout',
    retained_plate=True,release_performed=False,grip_target_e1_mm=25,
    actual_hamilton_pose=data['hamilton']['final_robot']['pose_mm'],
    actual_home_pose=returned['final_state']['robot']['pose_mm'],
    forward_route=p['routes']['forward'],departure_route=p['routes']['departure'],
    home_stages=returned['home_plan']['stages'],home_translation_speed=137,home_wrist_speed=30,
    route_plan_sha256=hashlib.sha256((FOLDER/'hamilton_short_side_hover04_plan.json').read_bytes()).hexdigest(),
    evidence={name:dict(path=str(path.relative_to(ROOT.parent)),sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for name,path in sources.items()},
    validation='Dense IK and winding checks; published Lua220109 protocol tested with fake hardware; physical arrival and loaded Home return accepted by operator.',
    limitations=['This verifies retained-plate travel, not release/retrieval at Hamilton.',
                 'Home-to-Hamilton direct travel was not tested; outbound begins after holder pickup.',
                 'Evidence does not grant unattended future motion or general clearance for other setups.'])
with out.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2,ensure_ascii=False)
selection=json.loads(SELECTION.read_bytes());assert selection['revision']=='04'
selection.update(status='operator_confirmed_pickup_hamilton_home_success',
    accepted_result_path=str(out.relative_to(ROOT.parent)),accepted_result_sha256=hashlib.sha256(out.read_bytes()).hexdigest(),
    forward_hardware_verified=True,departure_and_home_hardware_verified=True,
    runtime_revision='04',execution_enabled=False,
    execution_note='One-shot trial permissions consumed; this accepted geometry is the reference for a freshly checked future run.')
selection.pop('runtime_revision_unchanged',None)
SELECTION.write_text(json.dumps(selection,indent=2),encoding='utf-8')
note='''

### 2026-11-10 - Accepted short-side pickup -> Hamilton -> Home, revision04
- Operator accepted corrected Hamilton placement and confirmed the plate stayed level and secure throughout the loaded return Home. No reported controller faults; jaws remained at E1 about25 mm. No release was performed.
- Taught endpoint X372.426/Y-186.666/Z51.718/Rz-93.017; commanded X372.43/Y-186.67/Z51.72/Rz-93.02. Retain taught turn X312.57/Y-43.52/Z117.93/Rz-56.32 and overhead crossing at Z137.93. Outbound five-point Lua queue: speeds137 to Z55, then5 to seat. No Home detour after pickup.
- Departure reverses the entry to the taught turn: four queued points, speeds[5,137,137,137]. Existing loaded IK Home return then lifts to Z300, turns at wrist speed30, crosses and lowers at137 to X289.97/Y62.63/Z248.02. Actual final Z248.019; plate remained secure per operator.
- Holder angle is checked/restored before pickup and monitored through grasp; its telemetry does not stop loaded lift/travel. E1, faults, IK, joints, corridor and Stop checks remain. Global workspace unchanged; exact taught Hamilton station endpoint exception retained.
- 12 focused offline checks pass, including corrected endpoint, reversed departure, mixed speeds in published Lua220109, rejection of stale endpoints/fast seating, acceptance gating and grip preservation. Earlier stopped/uncertain trials and original teachings retained. Successful reference: holder_short_side/alignment/successful_short_side_hamilton04.json.
'''
with (ROOT/'reports/trajectory_smoothing/Observations.md').open('ab') as stream:stream.write(note.encode('ascii'))
print(json.dumps(dict(saved=str(out),selection=str(SELECTION),status=record['status'])))
