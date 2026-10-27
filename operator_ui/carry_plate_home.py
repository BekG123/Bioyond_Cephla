"""Execute only the reviewed first loaded return, after operator pickup acceptance.

Uses the running Flask controller owner. Never starts/resets the program,
commands the claw, changes limits, retries, or uses empty-gripper Home consent.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import time

from autonomy import check_path, wrap
from proof_lift_plate import api, ready, near, write, PLAN, ROOT

AUTH=PLAN.with_name(PLAN.stem+'_carry_authorization.json')
PROOF=PLAN.with_name(PLAN.stem+'_proof_lift.json')
OUTPUT=PLAN.with_name(PLAN.stem+'_loaded_return.json')

def commands(plan):
    previous=plan['proof_lift']['target']
    result=[]
    for stage in plan['stages']:
        poses=stage['points'] if stage['kind']=='queue' else [{**previous,'Rz':stage['rz']}]
        for target in poses:
            rotation=stage['kind']=='rotate'
            if rotation:
                if min(previous['Z'],target['Z'])<299.95 or abs(wrap(target['Rz']-previous['Rz']))>30.05:
                    raise ValueError('Invalid wrist segment.')
                if any(abs(target[k]-previous[k])>1e-6 for k in ('X','Y','Z')):
                    raise ValueError('Wrist rotation must pin XYZ.')
            result.append(dict(target=target,rotation=rotation,
                speed=plan['candidate_wrist_speed'] if rotation else plan['candidate_translation_speed']))
            previous=target
    return result

if __name__=='__main__':
    if OUTPUT.exists():raise RuntimeError('This loaded return was already attempted. No automatic repeat.')
    auth=json.loads(AUTH.read_text())
    plan=json.loads(PLAN.read_text())
    proof=json.loads(PROOF.read_text())
    if not all(auth.get(k) is True for k in ('plate_secure','loaded_route_clear','hands_clear','estop_supervised')):
        raise RuntimeError('Operator pickup/clearance confirmation required.')
    if auth.get('plan_sha256')!=hashlib.sha256(PLAN.read_bytes()).hexdigest():
        raise RuntimeError('Reviewed plan changed.')
    if time.time()-auth['confirmed_at_unix']>600:raise RuntimeError('Confirmation expired.')
    if proof['status']!='lift_completed_awaiting_visual_inspection':raise RuntimeError('Successful proof lift required.')
    if hashlib.sha256((ROOT/'operator_ui/points.json').read_bytes()).hexdigest()!=plan['source_home_sha256']:
        raise RuntimeError('Saved Home changed.')
    state=api('state');ready(state);near(state['robot']['pose_mm'],proof['final_state']['robot']['pose_mm'],.05)
    if not state['envelope']['enabled']:raise RuntimeError('Workspace must remain enabled.')
    envelope={k:(state['envelope'][k]['min'],state['envelope'][k]['max']) for k in ('X','Y','Z')}
    if any(list(envelope[k])!=plan['envelope'][k] for k in envelope):raise RuntimeError('Reviewed workspace changed.')
    cfg=api('robot_params')
    if cfg!=plan['config']:raise RuntimeError('Kinematic configuration changed.')
    legs=commands(plan)
    previous=state['robot']['pose_mm'];q=state['robot']['joints']
    for leg in legs:
        q=check_path(previous,leg['target'],q,cfg,envelope);previous=leg['target']
    record=dict(status='attempt_started',authorization=auth,plan=plan,proof_lift=str(PROOF),
        initial_state=state,commands=legs,steps=[],samples=[],plate_release_commanded=False)
    write(OUTPUT,record)
    previous=state['robot']['pose_mm']
    try:
        for index,leg in enumerate(legs):
            state=api('state');ready(state);near(state['robot']['pose_mm'],previous,.1)
            target=leg['target']
            # Pure wrist MoveJ holds the measured XYZ, avoiding translation
            # caused by sub-millimetre encoder differences from the plan.
            if leg['rotation']:target={**state['robot']['pose_mm'],'Rz':target['Rz']}
            check_path(state['robot']['pose_mm'],target,state['robot']['joints'],cfg,envelope)
            command=dict(x=target['X'],y=target['Y'],z=target['Z'],rz=target['Rz'],
                         speed=leg['speed'],interpolation='joint' if leg['rotation'] else 'linear')
            step=dict(index=index,command=command,status='dispatched',started_at=datetime.now(timezone.utc).isoformat())
            record['steps'].append(step);write(OUTPUT,record)
            print(json.dumps(dict(step=index+1,total=len(legs),command=command)),flush=True)
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(api,'move',command)
                try:
                    while not future.done():
                        state=api('state');record['samples'].append(state);ready(state)
                        time.sleep(.2)
                    response=future.result();step['response']=response
                    if not response.get('ok') or response.get('recovered'):
                        raise RuntimeError('Motion completion unconfirmed; no retry.')
                except Exception:
                    record['stop_response']=api('program',{'action':'stop'})
                    raise
            state=api('state');ready(state);near(state['robot']['pose_mm'],target,.1)
            step.update(status='completed',actual=state['robot']);write(OUTPUT,record)
            previous=state['robot']['pose_mm']
        near(previous,plan['home'],.1)
        record.update(status='completed_at_home_awaiting_operator_inspection',final_state=state)
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        raise
    finally:
        record['finished_at']=datetime.now(timezone.utc).isoformat();write(OUTPUT,record)
    print(json.dumps(dict(status=record['status'],record=str(OUTPUT),pose=previous,e1=state['robot']['external_axes']['E1'])),flush=True)
