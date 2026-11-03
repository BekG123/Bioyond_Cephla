"""One operator-requested 5 mm lowering; no release, startup or retry."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import time
from projected_pickup import ROOT
from prepare_squid_destination import validate
from proof_lift_plate import api, near, write

FOLDER=ROOT/'operator_ui/reports/squid_48well_approach'
PRIOR=FOLDER/'slow_descent_20261103_from_65a0371c.json'
CANDIDATE=FOLDER/'destination_reteach_20261103T185217893840Z.json'
OUTPUT=FOLDER/'extra5_descent_20261103_from_65a0371c.json'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if OUTPUT.exists():raise RuntimeError('Already attempted; no replay')
    prior=json.loads(PRIOR.read_bytes());candidate=json.loads(CANDIDATE.read_bytes())
    if prior['candidate_sha256']!=hashlib.sha256(CANDIDATE.read_bytes()).hexdigest() or prior['status']!='at_dropoff_awaiting_support_and_release_confirmation':
        raise RuntimeError('Successful prior descent evidence required')
    state=api('state');r=state['robot']
    start={k:r['pose_mm'][k] for k in ('X','Y','Z','Rz')}
    near(start,prior['final_state']['robot']['pose_mm'],.05)
    target=dict(start,Z=start['Z']-5)
    initial_e1=r['external_axes']['E1']
    if abs(initial_e1-3.9)>.15:raise RuntimeError('Grip changed')
    cfg=api('robot_params')
    if cfg!=candidate['cfg']:raise RuntimeError('Settings changed')
    def check(s):
        robot=s['robot']
        if not robot.get('connected') or not robot.get('ok') or robot.get('errors') or not robot.get('enabled') or robot['control_mode']['mode']!='auto' or robot['program_state']['state']!='running' or s['sequence']['active']:
            raise RuntimeError('Controller not ready; no restart')
        env={k:[s['envelope'][k]['min'],s['envelope'][k]['max']] for k in ('X','Y','Z')}
        if not s['envelope']['enabled'] or env!=candidate['envelope']:raise RuntimeError('Workspace changed')
        pose=robot['pose_mm'];near(pose,dict(start,Z=pose['Z']),.15)
        if not target['Z']-.15<=pose['Z']<=start['Z']+.15:raise RuntimeError('Vertical range exceeded')
        if abs(robot['external_axes']['E1']-initial_e1)>.1:raise RuntimeError('Grip feedback changed')
    check(state)
    validation=validate([start,target],r['joints'],cfg,candidate['envelope'])
    print(json.dumps(dict(start=start,target=target,speed=5,execute=args.execute)),flush=True)
    if not args.execute:return
    record=dict(status='started',at=time.time(),prior=str(PRIOR),prior_sha256=hashlib.sha256(PRIOR.read_bytes()).hexdigest(),
        authorization='Operator requested an additional 0.5 cm lowering to inspect seating; no release.',
        start=start,target=target,speed=5,validation=validation,samples=[state],release_executed=False)
    write(OUTPUT,record)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(api,'move',dict(x=target['X'],y=target['Y'],z=target['Z'],rz=target['Rz'],speed=5,interpolation='linear'))
            try:
                while not future.done():
                    s=api('state');record['samples'].append(s);check(s);time.sleep(.2)
                response=future.result();record['response']=response
                if not response.get('ok') or response.get('recovered'):raise RuntimeError('Uncertain movement completion')
            except Exception:
                record['stop_response']=api('program',dict(action='stop'));raise
        final=api('state');check(final);near(final['robot']['pose_mm'],target,.1)
        record.update(status='lowered_5mm_awaiting_operator_seating_assessment',final_state=final)
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        if 'stop_response' not in record:record['stop_response']=api('program',dict(action='stop'))
        raise
    finally:
        record['finished_at']=time.time();write(OUTPUT,record)
        print(json.dumps(dict(report=str(OUTPUT),status=record['status'])),flush=True)


if __name__=='__main__':main()
