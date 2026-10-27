"""Read-only IK review for the first open-claw 48-well descent trial."""
import json
from urllib.request import urlopen
from projected_pickup import ROOT,load,target,descent_plan
from sequences import get_robot_params,band_floor
from autonomy import TransferError

def main():
    with urlopen('http://127.0.0.1:5002/state',timeout=8) as response:s=json.load(response)
    r=s['robot']
    if s['sequence']['active'] or not r.get('connected') or not r.get('ok') or r.get('errors'):
        raise TransferError('Healthy idle robot required for trial preparation.')
    if not s['envelope']['enabled']:raise TransferError('Workspace must be enabled.')
    env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
    p,digest=load();t=target(trial=True)
    plan=descent_plan(r['pose_mm'],r['joints'],t,get_robot_params(),env,band_floor())
    report=dict(motion_started=False,profile_sha256=digest,start=r['pose_mm'],
                plan=plan,claw_open_target_mm=28,fast_speed=137,final_20mm_speed=5,
                automatic_grip=False,automatic_lift=False,
                note='Candidate gripping height requires supervised trial and visual acceptance.')
    path=ROOT/'operator_ui/reports/projected_alignment/descent_trial_prepared_20261026.json'
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(report=str(path),start=r['pose_mm'],endpoint=plan['endpoint'],
                          profile_sha256=digest,motion_started=False)))

if __name__=='__main__':main()
