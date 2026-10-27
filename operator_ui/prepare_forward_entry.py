"""Prepare the operator-requested 3 mm forward entrance and its reset route."""
import hashlib
import json
from pathlib import Path
from straight_transfer import plan_forward_entry
from trajectory_queue import prepare_points

HERE=Path(__file__).resolve().parent
def main():
    root=HERE/'reports/trajectory_smoothing'
    baseline_raw=(root/'straight_transfer_212/candidate.json').read_bytes()
    baseline=json.loads(baseline_raw)
    data=json.loads((HERE/'demonstrations/return_home_20261016_130748/return_path.json').read_text())
    cfg=json.loads((HERE/'robot_params.json').read_text())
    home,ham=data['trajectory'][-1],data['trajectory'][0]
    route=plan_forward_entry(home['pose_mm'],ham['pose_mm'],home['joints'],cfg)
    prepare_points(home['pose_mm'],home['joints'],route['points'],cfg,reviewed=True,forward_entry=True)
    new=dict(schema='cephla.forward-entry-review.v1',source_sha256=baseline['source_sha256'],
             parent_candidate_sha256=baseline['parent_candidate_sha256'],
             baseline_candidate_sha256=hashlib.sha256(baseline_raw).hexdigest(),
             routes=dict(to_hamilton=route),height_mm=212,execution_authorized=False,
             operator_feedback='Slight backward motion upon entrance; advance 3 mm toward Hamilton instead.',
             interpretation='Hover 3 mm short along the approach; advance during descent; preserve taught endpoint.')
    for name,candidate,direction in [('straight_212_return',baseline,'toward_home'),('entry_forward_3mm',new,'to_hamilton')]:
        folder=root/name
        if (folder/'candidate.json').exists():raise RuntimeError('Preserve existing trial: '+name)
        folder.mkdir(parents=True,exist_ok=True)
        raw=json.dumps(candidate,indent=2).encode('utf-8');ident=hashlib.sha256(raw).hexdigest()
        (folder/'candidate.json').write_bytes(raw)
        grant=dict(path_sha256=ident,source_sha256=baseline['source_sha256'],attempt_available=True,
                   clearance_approved=True,workspace_box_exception=True,allow_explicit_repeats=False,
                   direction=direction,speed=40,status='approved_once',
                   authorization='Try this again; Yes—3 mm toward Hamilton. Existing supervised setup and cleared Z212 route.')
        (folder/'replay_permission.json').write_text(json.dumps(grant,indent=2),encoding='utf-8')
        print(json.dumps(dict(variant=name,path_id=ident,direction=direction)))
    print(json.dumps(route['points']))

if __name__=='__main__':main()
