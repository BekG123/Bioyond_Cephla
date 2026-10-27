"""Reverse successful loaded Home route, stop at holder with jaws unchanged."""
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request,urlopen
from proof_lift_plate import api,near,write
from proof_lift_48well_3p9_5mm import ready
from projected_pickup import ROOT,sha
from autonomy import check_path
from researcher_home import queued_station_stages

FOLDER=ROOT/'operator_ui/reports/projected_alignment'
PLAN=FOLDER/'holder_return_48well_20261027_plan.json'
RECEIPT=FOLDER/'holder_return_48well_20261027_trial.json'
SOURCE=FOLDER/'proof_lift_3p9_5mm_20261027.json'


def placement_speed(start,target,pickup_z):
    if abs(start['Rz']-target['Rz'])>.02:
        return 30
    # The approach ENDS at the slow-zone boundary; it must not crawl all the
    # way from clearance height. Only moves starting inside that zone are slow.
    return 5 if start['Z']<=pickup_z+20.001 and target['Z']<start['Z'] else 137


def move_command(command):
    request=Request('http://127.0.0.1:5002/move',data=json.dumps(command).encode(),
        headers={'Content-Type':'application/json','X-Cephla-View':'developer'})
    # Continuous feedback monitoring remains in the caller. Match the service
    # motion deadline rather than timing out its HTTP client prematurely.
    with urlopen(request,timeout=130) as response:return json.load(response)


def prepare():
    state=api('state');ready(state)
    if api('researcher/api/status')['hand_guiding']['state']!='off':raise RuntimeError('Hand-guiding active.')
    home=dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88)
    near(state['robot']['pose_mm'],home,.1)
    source=json.loads(SOURCE.read_bytes());pickup=source['start'];lift=source['final_state']['robot']['pose_mm']
    cfg=api('robot_params');env={k:(state['envelope'][k]['min'],state['envelope'][k]['max']) for k in ('X','Y','Z')}
    forward=queued_station_stages(lift,home,source['final_state']['robot']['joints'],cfg,env)
    nodes=[dict(lift)]
    for stage in forward:
        if stage['kind']=='queue':nodes.extend(stage['points'])
        else:nodes.append(dict(nodes[-1],Rz=stage['rz']))
    points=list(reversed(nodes[:-1]))
    # Split the final vertical descent: final 20 mm plus last proof-lift distance at speed5.
    final=points.pop()
    points.extend([dict(final,Z=pickup['Z']+20),final,pickup])
    current=state['robot']['pose_mm'];joints=state['robot']['joints'];steps=[]
    for point in points:
        joints=check_path(current,point,joints,cfg,env)
        speed=placement_speed(current,point,pickup['Z'])
        steps.append(dict(target=point,speed=speed,ik_joints=joints));current=point
    plan=dict(at=time.time(),start=state['robot']['pose_mm'],steps=steps,
        source=SOURCE.relative_to(ROOT).as_posix(),source_sha256=sha(SOURCE.read_bytes()),
        settings_sha256=sha(json.dumps(cfg,sort_keys=True).encode()),envelope=env,
        grip_target_e1_mm=3.9,release_allowed=False,operator_inspection_required_before_release=True,
        authorization='Prepare robot return; inspect the first placement before release',motion_started=False)
    if PLAN.exists():raise RuntimeError('Plan exists; preserve it.')
    with PLAN.open('x',encoding='utf-8') as stream:json.dump(plan,stream,indent=2)
    print(json.dumps(dict(plan=str(PLAN),steps=steps,release_allowed=False)))


def execute():
    if RECEIPT.exists():raise RuntimeError('Trial already attempted; no automatic retry.')
    plan=json.loads(PLAN.read_bytes());state=api('state');ready(state)
    near(state['robot']['pose_mm'],plan['start'],.1)
    if api('researcher/api/status')['hand_guiding']['state']!='off':raise RuntimeError('Hand-guiding active.')
    if sha(SOURCE.read_bytes())!=plan['source_sha256']:raise RuntimeError('Evidence changed.')
    cfg=api('robot_params')
    if sha(json.dumps(cfg,sort_keys=True).encode())!=plan['settings_sha256']:raise RuntimeError('IK settings changed.')
    env={k:[state['envelope'][k]['min'],state['envelope'][k]['max']] for k in ('X','Y','Z')}
    if env!=plan['envelope']:raise RuntimeError('Workspace changed.')
    current=state['robot']['pose_mm'];joints=state['robot']['joints']
    for step in plan['steps']:
        joints=check_path(current,step['target'],joints,cfg,env);current=step['target']
    record=dict(at=time.time(),plan=plan,status='started',steps=[],release_command_sent=False)
    write(RECEIPT,record)
    try:
        for step in plan['steps']:
            ready(api('state'));target=step['target']
            item=dict(step=step,started_at=time.time(),samples=[]);record['steps'].append(item);write(RECEIPT,record)
            command=dict(x=target['X'],y=target['Y'],z=target['Z'],rz=target['Rz'],speed=step['speed'],interpolation='linear')
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(move_command,command)
                while not future.done():
                    state=api('state');item['samples'].append(state)
                    try:ready(state)
                    except Exception:
                        record['stop_response']=api('program',{'action':'stop'});raise
                    time.sleep(.2)
                item['response']=future.result()
            if not item['response'].get('ok') or item['response'].get('recovered'):raise RuntimeError('Uncertain move; no retry.')
            state=api('state');ready(state);near(state['robot']['pose_mm'],target,.1)
            item['after']=state;write(RECEIPT,record)
            print(json.dumps(dict(arrived=state['robot']['pose_mm'],e1=state['robot']['external_axes']['E1'])),flush=True)
        record.update(status='placement_completed_awaiting_inspection_before_release',final_state=state)
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        if 'stop_response' not in record:
            try:record['stop_response']=api('program',{'action':'stop'})
            except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:write(RECEIPT,record)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-confirmed',action='store_true')
    parser.add_argument('--accepted-repeat',type=int,choices=[1,2,3])
    args=parser.parse_args()
    if args.accepted_repeat:
        SOURCE=FOLDER/f'repeat_{args.accepted_repeat}_proof_lift_20261027.json'
        PLAN=FOLDER/f'repeat_{args.accepted_repeat}_holder_return_plan_20261027.json'
        RECEIPT=FOLDER/f'repeat_{args.accepted_repeat}_holder_return_trial_20261027.json'
    execute() if args.execute_confirmed else prepare()
