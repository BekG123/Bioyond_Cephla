"""Prepare one 2 mm outward correction from a fresh completed alignment.

Read-only with respect to hardware. Writes a checked plan for explicit dispatch.
"""
import json,math,time
from pathlib import Path
from urllib.request import urlopen
from autonomy import check_path,ensure_arrival
from sequences import get_robot_params
from projected_pickup import ROOT,sha

def main():
    with urlopen('http://127.0.0.1:5002/state',timeout=8) as r:s=json.load(r)
    with urlopen('http://127.0.0.1:5002/seq',timeout=8) as r:q=json.load(r)
    r=s['robot']
    assert r.get('connected') and r.get('ok') and not r['errors'] and s['envelope']['enabled']
    assert not q['active'] and q['name']=='projected_alignment' and q['state']=='done' and q['result']['ok']
    pose={k:r['pose_mm'][k] for k in ('X','Y','Z','Rz')}
    target=q['result']['route']['target']
    ensure_arrival(pose,dict(X=target['x'],Y=target['y'],Z=300.,Rz=target['rz']))
    cfg=get_robot_params();dx=pose['X']-cfg['base_x_mm'];dy=pose['Y']-cfg['base_y_mm']
    radius=math.hypot(dx,dy);assert radius>2
    goal=dict(pose,X=pose['X']+2*dx/radius,Y=pose['Y']+2*dy/radius)
    env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
    joints=check_path(pose,goal,r['joints'],cfg,env)
    log=Path(q['result']['log_file'])
    record=dict(at=time.time(),direction='away_from_robot_base',distance_mm=2,
        operator_authorized_open_claw_trial=True,
        operator_request='Retry calibration, alignment and descent with 2 mm outward from fresh alignment, replacing the mistaken 2 mm inward correction.',
        source_alignment_pose=pose,commanded_pose=goal,checked_joints=joints,
        alignment_log=log.relative_to(ROOT).as_posix(),alignment_log_sha256=sha(log.read_bytes()),
        base_mm=dict(X=cfg['base_x_mm'],Y=cfg['base_y_mm']),speed=5,
        arrival_verified=False,motion_started=False,visual_alignment_accepted=False)
    out=ROOT/'operator_ui/reports/projected_alignment/prepared_outward_2mm_20261027.json'
    if out.exists():raise RuntimeError('Existing plan must not be overwritten or reapplied.')
    out.write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(dict(report=str(out),start=pose,target=goal,delta_xy=[goal['X']-pose['X'],goal['Y']-pose['Y']])))

if __name__=='__main__':main()
