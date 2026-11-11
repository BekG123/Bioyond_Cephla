"""Accepted short-side pickup -> new turning pose -> Hamilton; no Home detour."""
from gripper_closure import POLICY, closure_commands
from concurrent.futures import ThreadPoolExecutor
import argparse
import json
import time
from proof_lift_plate import api,near
from draggo import DragGoRPC
from autonomy import check_path
from short_side_full_trial import reference,FOLDER,validate_route,receipt
from short_side_alignment_trial import reference_for_candidate,candidate_points,validate_route as validate_pickup
from hamilton_short_side_trial import validate_route as validate_direct

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--revision',choices=('02','03','04'),required=True)
parser.add_argument('--attempt',choices=('retry01','retry02','retry03'),default='')
args=parser.parse_args();revision=args.revision;attempt=args.attempt
profile='pickup_hover'+revision+'_forward' if revision in ('03','04') else 'pickup_turning02_forward'
endpoint='developer/api/short-side-full-trial'+revision
plan,parent,grip=reference(revision);path=receipt('run',revision,attempt);grip_path=receipt('grip_lift',revision,attempt)
if path.exists() or grip_path.exists():raise RuntimeError('Trial already attempted; review saved evidence')
record=dict(status='started',started_at=time.time(),actions=[],samples=[],
    authorization='Operator confirmed all routes clear, plate flat in rotated holder, empty jaws, arm free and released, hands clear and E-stop supervised.',
    settings=grip,plate_retention_operator_verified=False,release_requested=False)
def save():path.write_text(json.dumps(record,indent=2))
def checked(e1_range,pose=None,allow_sequence=False,holder_required=True):
    s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
    record['samples'].append(dict(at=time.time(),state=s,native=n))
    if not r.get('ok') or not r.get('connected') or r.get('errors') or not r.get('enabled') or r['control_mode']['mode']!='auto' or r['program_state']['state']!='running' or not r.get('lua_app_initialized'):
        raise RuntimeError('Healthy running Auto required; no reset or restart')
    if (s['sequence']['active'] and not allow_sequence) or any(n[k] for k in ('manual','drag','error','emergency')):raise RuntimeError('Conflicting activity or fault')
    if holder_required and abs(n['external_axes']['E2']-grip['holder_e2_degrees'])>.1:raise RuntimeError('Holder changed before pickup')
    if not e1_range[0]<=n['external_axes']['E1']<=e1_range[1]:raise RuntimeError('Jaw position outside current step')
    if pose is not None:near(r['pose_mm'],pose,.1)
    return s,n
def call(ep,body):
    if ep==endpoint and attempt:body=dict(body,attempt=attempt)
    item=dict(at=time.time(),endpoint=ep,command=body);record['actions'].append(item);save()
    item['response']=api(ep,body);save();r=item['response']
    if not r.get('ok') or r.get('recovered') or r.get('gripper_warning'):raise RuntimeError(str(r))
    return r
def monitored_command(ep,body,e1_range,pose=None,vertical=None):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(call,ep,body)
        while not future.done():
            try:
                s,n=checked(e1_range,pose,holder_required=vertical is None)
                if vertical:
                    low,high=vertical;p=s['robot']['pose_mm']
                    if any(abs(p[k]-low[k])>.15 for k in ('X','Y','Rz')) or not low['Z']-.15<=p['Z']<=high['Z']+.15:raise RuntimeError('Proof lift left vertical corridor')
                save()
            except Exception:
                record['stop_response']=api('program',{'action':'stop'});raise
            time.sleep(.1)
        return future.result()
def wait(label,e1):
    deadline=time.monotonic()+150
    while time.monotonic()<deadline:
        s,n=checked((e1-.07,e1+.07),allow_sequence=True,holder_required=label!='hamilton');seq=api('seq');save()
        if not seq['active']:
            record[label]=seq;save()
            if seq['state']!='done' or not (seq.get('result') or {}).get('ok'):raise RuntimeError(str(seq.get('result')))
            if n['moving']:raise RuntimeError('Motion not settled')
            print(json.dumps(dict(stage=label,pose=s['robot']['pose_mm'])),flush=True);return
        time.sleep(.2)
    raise RuntimeError('Sequence timed out')

s=api('state')
if not s['robot'].get('connected') and not s['sequence']['active']:assert api('connect',{'ip':'192.168.201.220'})['ok']
initial_jaws=(-.15,.15)
if attempt or revision=='04':
    prep=json.loads(receipt('ready',revision,attempt).read_bytes())
    assert prep['status']=='completed' and prep['operator_confirmed_plate_reseated_empty_jaws']
    baseline=prep['jaw_position_preserved_mm'];initial_jaws=(baseline-.15,baseline+.15)
s,n=checked(initial_jaws,parent['home']);assert not n['moving']
assert api('researcher/api/status')['hand_guiding']['state']=='off'
assert not api('researcher/api/lacry/state')['running']['active']
assert s['envelope']['enabled']
cfg=api('robot_params');env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
pickup,_=reference_for_candidate('corrected02');points=candidate_points(pickup,'corrected02')
q=validate_pickup(s['robot']['pose_mm'],points,s['robot']['joints'],cfg,env,'corrected02')
low=grip['descent_endpoint'];high=grip['proof_lift_endpoint'];hq=check_path(low,high,q,cfg,env)
hq['J1']=q['J1']+5
record['home_between_pickup_and_hamilton']=False
validate_direct(high,plan['routes']['forward']['points'],hq,cfg,env,profile)
with path.open('x') as f:json.dump(record,f,indent=2)
try:
    monitored_command('gripper',dict(action='move',e1=28,speed=10),(-.15,28.07),parent['home'])
    checked((27.93,28.07),parent['home'])
    call(endpoint,dict(phase='approach',ready=True,setup_confirmed=True,path_clear=True));wait('approach',28)
    checked((27.93,28.07),low)
    gr=dict(closure_policy=POLICY,status='started',started_at=time.time(),settings=grip,steps=[],force_limits_changed=False)
    with grip_path.open('x') as f:json.dump(gr,f,indent=2)
    previous=28
    for command in closure_commands(28,grip['target_e1_mm']):
        target=command['target_e1_mm']
        checked((previous-.07,previous+.07),low)
        response=monitored_command('gripper',dict(action='move',e1=target,speed=command['speed']),(target-.07,previous+.07),low)
        if response.get('gripper',{}).get('grip_detected'):raise RuntimeError('Unexpected contact/stall indication; no further closure')
        step=dict(target=target,speed=command['speed'],response=response,reports=[]);gr['steps'].append(step)
        for _ in range(3):
            checked((target-.07,target+.07),low)
            report=call('gripper',{'action':'torque'});step['reports'].append(report)
            if not report.get('telemetry_live') or abs(report.get('e1_position',999)-target)>.07:raise RuntimeError('Settled grip report unconfirmed')
            time.sleep(.15)
        grip_path.write_text(json.dumps(gr,indent=2));previous=target
    monitored_command('move',dict(x=high['X'],y=high['Y'],z=high['Z'],rz=high['Rz'],speed=5,interpolation='linear'),(24.93,25.07),vertical=(low,high))
    for _ in range(5):s,n=checked((24.93,25.07),high,holder_required=False);time.sleep(.2)
    assert not n['moving'];gr.update(status='completed',finished_at=time.time(),final_state=s,operator_retention_observation='pending',
        holder_monitor='Required through grasp; telemetry only during proof lift and loaded travel. Jaw/vertical/arm/fault checks retained.')
    grip_path.write_text(json.dumps(gr,indent=2))
    print(json.dumps(dict(stage='grip25_and_lift5_completed',pose=s['robot']['pose_mm'])),flush=True)
    checked((24.93,25.07),high,holder_required=False)
    call(endpoint,dict(phase='hamilton',ready=True,setup_confirmed=True,path_clear=True));wait('hamilton',25)
    s,n=checked((24.93,25.07),plan['routes']['forward']['points'][-1],holder_required=False)
    record.update(status='completed_awaiting_operator_inspection',final_state=s)
except Exception as e:
    record.update(status='failed_or_uncertain',error=str(e))
    if grip_path.exists():
        gr=json.loads(grip_path.read_bytes())
        if gr['status']=='started':gr.update(status='failed_or_uncertain',error=str(e));grip_path.write_text(json.dumps(gr,indent=2))
    try:
        if api('seq')['active']:record['stop_response']=api('researcher/api/lacry/stop',{})
        else:record['stop_response']=api('program',{'action':'stop'})
    except Exception as stop_error:record['stop_error']=str(stop_error)
    raise
finally:record['finished_at']=time.time();save()
print(json.dumps(dict(status=record['status'],pose=s['robot']['pose_mm'],report=str(path))))
