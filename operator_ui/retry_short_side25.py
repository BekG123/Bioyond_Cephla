"""Prepare or execute supported-plate reopen/reseat, staged 25 mm grip, 5 mm lift."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import time
from proof_lift_plate import api,near
from draggo import DragGoRPC
from short_side_alignment_trial import FOLDER,reference_for_candidate
from autonomy import check_path

def main():
    args=argparse.ArgumentParser()
    args.add_argument('--plate-supported-jaws-free',action='store_true')
    options=args.parse_args()
    _,taught=reference_for_candidate('corrected02')
    parent=FOLDER/'proof_lift_corrected02_e1_26.json'
    lift=json.loads(parent.read_bytes())
    assert lift['status']=='lift_completed_awaiting_retention_inspection'
    assessment=FOLDER/'proof_lift_corrected02_e1_26_operator_assessment.json'
    if not assessment.exists():
        with assessment.open('x') as f:json.dump(dict(at=time.time(),status='operator_reported_slip',
            feedback='The lift did not work. It slipped.',physical_pickup_success=False,
            trial_sha256=hashlib.sha256(parent.read_bytes()).hexdigest()),f,indent=2)
    low={k:lift['start'][k] for k in ('X','Y','Z','Rz')}
    high={k:lift['target'][k] for k in ('X','Y','Z','Rz')}
    assert abs(high['Z']-low['Z']-5)<1e-8
    path=FOLDER/'retry_grip25_and_proof_lift.json'
    if path.exists():raise RuntimeError('25 mm trial already attempted; review before any retry')
    record=dict(status='prepared',at=time.time(),low=low,high=high,steps=[],samples=[],
        sequence=['open28','lower5mm','close27','close26','close25.8','close25.6','close25.4','close25.2','close25','lift5mm'],
        speed=5,grasp_verified=False,force_limits_changed=False,
        parent_sha256=hashlib.sha256(parent.read_bytes()).hexdigest())
    def save():path.write_text(json.dumps(record,indent=2))
    def checked(e1_range,expected_pose=None):
        s=api('state');r=s['robot'];n=DragGoRPC('192.168.201.220').info()
        record['samples'].append(dict(at=time.time(),state=s,native=n))
        if not r.get('ok') or not r.get('connected') or r.get('errors') or not r.get('enabled') or r['control_mode']['mode']!='auto' or r['program_state']['state']!='running' or not r.get('lua_app_initialized'):raise RuntimeError('Healthy running Auto required; no startup or reset allowed')
        if s['sequence']['active'] or any(n[k] for k in ('manual','drag','error','emergency')):raise RuntimeError('Conflicting activity or controller fault')
        if abs(n['external_axes']['E2']-taught['e2_degrees'])>.1:raise RuntimeError('Holder angle changed')
        if not e1_range[0]<=n['external_axes']['E1']<=e1_range[1]:raise RuntimeError('Jaw position outside current step')
        pose=r['pose_mm']
        if any(abs(pose[k]-low[k])>.15 for k in ('X','Y','Rz')) or not low['Z']-.15<=pose['Z']<=high['Z']+.15:raise RuntimeError('Arm left vertical trial corridor')
        if expected_pose is not None:near(pose,expected_pose,.1)
        return s,n
    def command(ep,body,e1_range,expected_pose=None):
        item=dict(at=time.time(),endpoint=ep,command=body);record['steps'].append(item);save()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(api,ep,body)
            while not future.done():
                try:checked(e1_range,expected_pose);save()
                except Exception:
                    record['stop_response']=api('program',{'action':'stop'});raise
                time.sleep(.1)
            item['response']=future.result();save()
        response=item['response']
        if not response.get('ok') or response.get('recovered') or response.get('gripper_warning'):raise RuntimeError('Uncertain command completion; no retry')
        return item
    def grip(target,previous,pose):
        checked((previous-.07,previous+.07),pose)
        item=command('gripper',dict(action='move',e1=target,speed=5),(min(previous,target)-.07,max(previous,target)+.07),pose)
        if target<previous and item['response'].get('gripper',{}).get('grip_detected'):raise RuntimeError('Contact/stall indication; inspect before continuing')
        item['stationary_reports']=[]
        for _ in range(3):
            checked((target-.07,target+.07),pose)
            report=api('gripper',{'action':'torque'});item['stationary_reports'].append(report);save()
            if not report.get('ok') or not report.get('telemetry_live') or report.get('recovered') or abs(report.get('e1_position',999)-target)>.07:raise RuntimeError('Fresh settled grip report not verified')
            time.sleep(.15)
    def vertical(target,e1):
        command('move',dict(x=target['X'],y=target['Y'],z=target['Z'],rz=target['Rz'],speed=5,interpolation='linear'),(e1-.07,e1+.07))
        s,n=checked((e1-.07,e1+.07),target)
        if n['moving']:raise RuntimeError('Arm has not stopped')
    s=api('state')
    if not s['robot'].get('connected') and not s['sequence']['active']:
        assert api('connect',{'ip':'192.168.201.220'})['ok']
    s,n=checked((25.93,26.07),high)
    assert not n['moving'] and api('researcher/api/status')['hand_guiding']['state']=='off'
    assert not api('researcher/api/lacry/state')['running']['active']
    assert s['envelope']['enabled']
    env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
    cfg=api('robot_params');q=check_path(high,low,s['robot']['joints'],cfg,env);check_path(low,high,q,cfg,env)
    assert 0<=s['robot']['joints']['J1']-5<=400
    if not options.plate_supported_jaws_free:
        print(json.dumps(dict(status='prepared_no_motion',low=low,high=high,targets=record['sequence'],assessment=str(assessment))));return
    record['authorization']='Operator requested 25 mm retry and confirmed plate fully supported, jaws free to open/lower, hands clear and E-stop supervised.'
    with path.open('x') as f:json.dump(record,f,indent=2)
    try:
        grip(28,26,high)
        vertical(low,28)
        previous=28
        for target in (27,26,25.8,25.6,25.4,25.2,25):
            grip(target,previous,low);previous=target
        for _ in range(5):checked((24.93,25.07),low);time.sleep(.2)
        vertical(high,25)
        for _ in range(5):s,n=checked((24.93,25.07),high);time.sleep(.2)
        record.update(status='lift_completed_awaiting_retention_inspection',final_state=s)
    except Exception as error:
        record.update(status='failed_or_uncertain',error=str(error))
        if 'stop_response' not in record:
            try:record['stop_response']=api('program',{'action':'stop'})
            except Exception as e:record['stop_error']=str(e)
        raise
    finally:record['finished_at']=time.time();save()
    print(json.dumps(dict(status=record['status'],pose=s['robot']['pose_mm'],e1=n['external_axes']['E1'],report=str(path))))

if __name__=='__main__':main()
