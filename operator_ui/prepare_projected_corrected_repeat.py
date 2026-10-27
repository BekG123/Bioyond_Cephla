"""Read-only IK review of a repeat to the operator-confirmed corrected hover.

Fresh camera alignment must agree with the prior uncorrected alignment. Reuse
the absolute corrected endpoint so neither the 2 mm nor 5 mm adds up again.
"""
import json,math,time
from pathlib import Path
from urllib.request import urlopen
from autonomy import check_path,ensure_arrival,TransferError,wrap
from sequences import get_robot_params
from projected_pickup import ROOT,load,sha

def main():
    profile,digest=load()
    if digest!='24a49a6e27919aece2e0b47e8843afd1e843ca0026e28445f3e38cca9342d09e':
        raise TransferError('Confirmed corrected profile changed.')
    with urlopen('http://127.0.0.1:5002/state',timeout=8) as r:s=json.load(r)
    with urlopen('http://127.0.0.1:5002/seq',timeout=8) as r:q=json.load(r)
    r=s['robot']
    if not r.get('connected') or not r.get('ok') or r.get('errors') or not s['envelope']['enabled']:
        raise TransferError('Healthy controller and active workspace required.')
    if q['active'] or q['name']!='projected_alignment' or q['state']!='done' or not q['result']['ok']:
        raise TransferError('Fresh completed alignment required.')
    prior_path=ROOT/'operator_ui/reports/projected_alignment/alignment_outward_trial_20261027.json'
    prior=json.loads(prior_path.read_bytes())['source_alignment_pose']
    pose=r['pose_mm'];target=q['result']['route']['target']
    ensure_arrival(pose,dict(X=target['x'],Y=target['y'],Z=300.,Rz=target['rz']))
    deviation=math.hypot(pose['X']-prior['X'],pose['Y']-prior['Y'])
    if deviation>.5 or abs(wrap(pose['Rz']-prior['Rz']))>.2:
        raise TransferError('Fresh alignment differs from the corrected placement; review before adapting.')
    goal=profile['alignment_pose_mm'];env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
    joints=check_path(pose,goal,r['joints'],get_robot_params(),env)
    log=Path(q['result']['log_file'])
    record=dict(at=time.time(),source=pose,target=goal,endpoint=profile['candidate_endpoint'],
        profile_sha256=digest,prior_raw_alignment=prior,fresh_alignment_difference_mm=deviation,
        alignment_log=log.relative_to(ROOT).as_posix(),alignment_log_sha256=sha(log.read_bytes()),
        operator_feedback='Gaps are even; repeat calibration, alignment and descent.',
        reported_gap_mm=25,gap_unit_confirmed=True,
        feedback_usage='Operator confirmed 25 mm on each side; retain corrected endpoint.',
        correction_strategy='Reuse confirmed absolute corrected hover; no cumulative offsets.',
        planned_joints=joints,speed=5,motion_started=False)
    out=ROOT/'operator_ui/reports/projected_alignment/corrected_repeat_plan_20261027.json'
    if out.exists():raise TransferError('Do not overwrite repeat plan.')
    out.write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(dict(report=str(out),start=pose,target=goal,fresh_alignment_difference_mm=deviation)))

if __name__=='__main__':main()
