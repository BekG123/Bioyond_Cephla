"""Save the explicitly cleared Z212 trial and return; no motion commands."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen
from straight_transfer import plan_straight_transfer
from trajectory_queue import prepare_points

HERE=Path(__file__).resolve().parent

def main():
    root=HERE/'reports/trajectory_smoothing'
    raw=(HERE/'demonstrations/return_home_20261016_130748/return_path.json').read_bytes()
    data=json.loads(raw);source=hashlib.sha256(raw).hexdigest()
    parent=hashlib.sha256((root/'pruned_middle/candidate.json').read_bytes()).hexdigest()
    cfg=json.loads((HERE/'robot_params.json').read_text())
    home,ham=data['trajectory'][-1],data['trajectory'][0]
    with urlopen('http://127.0.0.1:5002/state',timeout=5) as response:state=json.load(response)
    robot=state['robot'];p=robot['pose_mm'];q=robot['joints']
    if (state['sequence']['active'] or robot['errors'] or not robot['connected']
            or robot['program_state']['state']!='stopped'
            or any(abs(p[k]-v)>1 for k,v in dict(X=226.52,Y=-200.47,Z=212.22,Rz=-.45).items())):
        raise RuntimeError('Robot no longer matches the cleared stationary return start.')
    routes={name:plan_straight_transfer(a['pose_mm'],b['pose_mm'],a['joints'],cfg,212)
            for name,a,b in [('to_hamilton',home,ham),('toward_home',ham,home)]}
    recovery=[{k:round(home['pose_mm'][k],2) for k in ('X','Y','Z','Rz')} for _ in range(2)]
    recovery[0]['Z']=round(p['Z'],2)
    recovery,_=prepare_points(p,q,recovery,cfg,reviewed=True,level_return=True)
    common=dict(source_sha256=source,parent_candidate_sha256=parent,
                execution_authorized=False,clearance_basis='Operator confirmation; not automatic collision detection')
    candidates={
        'straight_transfer_212':dict(**common,schema='cephla.straight-transfer-review.v1',height_mm=212,routes=routes),
        'return_to_start_212':dict(**common,schema='cephla.level-return-review.v1',
                                 start_sample=dict(pose_mm=p,joints=q,valid=True,elapsed_s=0),points=recovery)}
    for name,candidate in candidates.items():
        folder=root/name
        if (folder/'candidate.json').exists():raise RuntimeError('Preserve existing trial: '+name)
        folder.mkdir(parents=True,exist_ok=True)
        content=json.dumps(candidate,indent=2).encode('utf-8');ident=hashlib.sha256(content).hexdigest()
        (folder/'candidate.json').write_bytes(content)
        returning=name=='return_to_start_212'
        grant=dict(path_sha256=ident,source_sha256=source,attempt_available=True,
                   clearance_approved=True,workspace_box_exception=True,allow_explicit_repeats=False,
                   direction='toward_home' if returning else 'to_hamilton',speed=40,
                   authorization='Both routes clear; arm released; E-stop supervised',
                   status='approved_once')
        (folder/'replay_permission.json').write_text(json.dumps(grant,indent=2),encoding='utf-8')
        print(json.dumps(dict(folder=name,path_id=ident,points=recovery if returning else routes['to_hamilton']['points'])))

if __name__=='__main__':main()
