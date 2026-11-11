"""One loaded return with continuous clearance lift; preserve current claws."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import time
from capture_squid_approach_20261103 import FOLDER, sha
from prepare_squid_destination import validate
from proof_lift_plate import api, near, write

PLAN=FOLDER/'loaded_return_continuous_lift_z266p81_20261103.json'
SHA='269694264565a4aef4d9b53a586d80925aa222df2aca7f3fa3d6f1aa84454fb7'
OUTPUT=FOLDER/'loaded_return_continuous_trial_20261103.json'
# Shared approach/release/pickup helpers use the new queue. Refuse before motion
# until 220109 is published; never silently fall back to separate host moves.
# single_queue=False remains available for an explicit legacy comparison.
USE_SINGLE_QUEUE=True


def main(expected_speeds=(5,137,137,137), vertical_legs=(0,), single_queue=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    if OUTPUT.exists():raise RuntimeError('Already attempted; no replay')
    if sha(PLAN)!=SHA:raise RuntimeError('Plan changed')
    plan=json.loads(PLAN.read_bytes());state=api('state');r=state['robot']
    if not r.get('connected'):raise RuntimeError('Connect status first')
    route=deepcopy(plan['routes']['from_capture'])
    near(r['pose_mm'],route[0],.05)
    # Preserve live XY/yaw for a strictly vertical departure within the reviewed start tolerance.
    route[0]={k:r['pose_mm'][k] for k in ('X','Y','Z','Rz')}
    route[1]=dict(route[0],Z=route[1]['Z'])
    baseline=r['external_axes']['E1']
    cfg=api('robot_params')
    if cfg!=plan['cfg']:raise RuntimeError('Settings changed')
    def check(s):
        robot=s['robot']
        if not robot.get('connected') or not robot.get('ok') or robot.get('errors') or not robot.get('enabled') or robot['control_mode']['mode']!='auto' or robot['program_state']['state']!='running' or s['sequence']['active']:
            raise RuntimeError('Controller not ready; no startup or recovery')
        env={k:[s['envelope'][k]['min'],s['envelope'][k]['max']] for k in ('X','Y','Z')}
        if not s['envelope']['enabled'] or env!=plan['envelope']:raise RuntimeError('Workspace changed')
        if abs(robot['external_axes']['E1']-baseline)>.1:raise RuntimeError('Grip feedback changed')
    check(state)
    checked=validate(route,r['joints'],cfg,plan['envelope'])
    assert plan['leg_speeds']==list(expected_speeds) and len(route)==len(expected_speeds)+1
    queued=USE_SINGLE_QUEUE if single_queue is None else single_queue
    if queued:
        from squid_queue_client import preview,execute as execute_queue
        body,queue_preview=preview(route,plan['leg_speeds'])
    print(json.dumps(dict(route=route,speeds=plan['leg_speeds'],preserved_e1=baseline,execute=args.execute)),flush=True)
    if not args.execute:return
    if queued:
        record=execute_queue(body,plan,route,baseline,state,OUTPUT,PLAN,SHA)
        print(json.dumps(dict(report=str(OUTPUT),status=record['status'],executor='lua_queue_segment_speeds')),flush=True)
        return
    record=dict(status='started',at=time.time(),plan=str(PLAN),plan_sha256=SHA,route=route,
        speeds=plan['leg_speeds'],source_state=state,validation=checked,steps=[],samples=[],
        authorization=plan.get('operator_intent','Operator requested execution of saved continuous-lift loaded return and confirmed controller ready. Preserve current claws.'),
        preserved_e1_mm=baseline,gripper_commands=[],startup_commands=[],release_executed=False)
    write(OUTPUT,record)
    try:
        for i,(point,speed) in enumerate(zip(route[1:],plan['leg_speeds'])):
            state=api('state');check(state);near(state['robot']['pose_mm'],route[i],.1)
            if sha(PLAN)!=SHA or api('robot_params')!=cfg:raise RuntimeError('Plan/settings changed')
            step=dict(target=point,speed=speed,status='requested');record['steps'].append(step);write(OUTPUT,record)
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(api,'move',dict(x=point['X'],y=point['Y'],z=point['Z'],rz=point['Rz'],speed=speed,interpolation='linear'))
                try:
                    while not future.done():
                        state=api('state');record['samples'].append(state);check(state)
                        if i in vertical_legs:
                            pose=state['robot']['pose_mm'];near(pose,dict(route[i],Z=pose['Z']),.15)
                            low,high=sorted((route[i]['Z'],point['Z']))
                            if not low-.15<=pose['Z']<=high+.15:raise RuntimeError('Vertical leg exceeded range')
                        time.sleep(.2)
                    result=future.result();step['response']=result
                    if not result.get('ok') or result.get('recovered'):raise RuntimeError('Uncertain movement completion')
                except Exception:
                    record['stop_response']=api('program',dict(action='stop'));raise
            state=api('state');check(state);near(state['robot']['pose_mm'],point,.1)
            step.update(status='arrived',after=state['robot']);write(OUTPUT,record)
            print(json.dumps(dict(leg=i+1,pose=state['robot']['pose_mm'])),flush=True)
        record.update(status=plan.get('completion_status','loaded_return_home_completed_pending_operator_assessment'),final_state=state)
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        if 'stop_response' not in record:record['stop_response']=api('program',dict(action='stop'))
        raise
    finally:
        record['finished_at']=time.time();write(OUTPUT,record)
        print(json.dumps(dict(report=str(OUTPUT),status=record['status'])),flush=True)


if __name__=='__main__':main()
