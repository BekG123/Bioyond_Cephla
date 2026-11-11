"""Authorized IDLE -> full-calibration repetitions through the existing Lacry UI API.

No controller startup/reset, geometry changes, retries, rotation or station travel.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4
from imitation_agent import close_pose

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT/'Pick and Hold/Calibration/plate_48_pickup_profile.json'
SHA = '1ddb2a2a3029eacb34317581d204cca62c68fc992420c49140e9b8efee0a09bc'
IDLE = dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88)
END = dict(X=312.0124178577057,Y=-65.47790542678248,Z=103.718,Rz=89.7652192188176)
LABELS = ['Calibrate the 48-well plate','Align with the 48-well plate',
          'Descend to the taught 48-well position','Grip the 48-well plate',
          'Lift the plate 5 mm','Lower the plate back into HOME',
          'Release the plate at HOME','Raise the empty arm 30 mm']


def api(path, body=None):
    req=Request('http://127.0.0.1:5002/'+path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type':'application/json','X-Cephla-View':'developer'})
    try:
        with urlopen(req,timeout=20) as response: value=json.load(response)
    except HTTPError as error:
        detail=error.read().decode('utf-8',errors='replace')
        raise RuntimeError(f'{path}: HTTP {error.code}: {detail}') from error
    if value.get('ok') is False: raise RuntimeError(str(value))
    return value


def near(actual, expected, tolerance=.05):
    if any(not math.isfinite(actual[k]) or abs(actual[k]-expected[k])>tolerance for k in ('X','Y','Z','Rz')):
        raise RuntimeError('Measured endpoint does not match expected pose.')


def at_idle_pose(pose):
    """Use the UI planner's existing parking readiness rule, including yaw wrap."""
    return close_pose(pose,IDLE)


def require_idle_pose(pose):
    if not at_idle_pose(pose):raise RuntimeError('Arm is outside the UI-accepted IDLE position.')


def start_location(pose):
    for name, expected in [('idle',IDLE),('holder_clearance',END)]:
        try:near(pose,expected)
        except (RuntimeError,KeyError,TypeError):continue
        return name
    raise RuntimeError('Start at IDLE or the accepted empty-arm HOME clearance position.')


def healthy(state):
    r=state['robot']
    if (not r.get('connected') or not r.get('ok') or r.get('errors')
            or not r.get('enabled') or r.get('control_mode',{}).get('mode')!='auto'
            or r.get('program_state',{}).get('state')!='running'
            or not state['envelope']['enabled']):
        raise RuntimeError('Controller not healthy running Auto; batch stopped without recovery.')
    if hashlib.sha256(PROFILE.read_bytes()).hexdigest()!=SHA:
        raise RuntimeError('Pickup profile changed during batch.')
    return r


def verify_finish(running, seq, state, phase, previous_receipt):
    if running.get('ok') is not True or seq.get('active') or not (seq.get('result') or {}).get('ok'):
        raise RuntimeError('Workflow did not verify completion: '+str(running))
    r=healthy(state)
    if abs(r['external_axes']['E1']-28)>.15:
        raise RuntimeError('Empty-jaw opening did not match 28 mm.')
    if phase=='idle':
        if seq['name']!='researcher_home': raise RuntimeError('Unexpected IDLE sequence.')
        require_idle_pose(r['pose_mm'])
        return None
    if running['done']!=LABELS or seq['name']!='pickup_holder_clearance':
        raise RuntimeError('Incomplete calibration stage list.')
    result=seq['result']; near(r['pose_mm'],END)
    if result.get('payload')!='empty' or not result.get('record') or result['record']==previous_receipt:
        raise RuntimeError('Missing fresh empty-clearance receipt.')
    receipt=json.loads(Path(result['record']).read_bytes())
    if receipt['status']!='completed' or receipt['action']!='Clearance' or receipt['speed']!=137:
        raise RuntimeError('Wrong finishing receipt.')
    return result['record']


def terminal(running):
    # ClassicPickup can stop being active before Lacry publishes its final result.
    # Wait for that publication; do not dispatch another move or retry.
    return not running['active'] and running.get('ok') is not None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--cycles',type=int,choices=(2,5,10),default=5)
    parser.add_argument('--reconcile-first-cycle',type=Path)
    args=parser.parse_args()
    if not args.execute:
        print(json.dumps(dict(cycles=args.cycles,sequence=['move_idle','full_calibration'],profile_sha256=SHA,no_retries=True)))
        return
    folder=ROOT/'operator_ui/reports/pickup_holder'/(str(args.cycles)+'_cycles_'+uuid4().hex)
    folder.mkdir(parents=True)
    record=dict(status='preflight',at=time.time(),planned_cycles=args.cycles,completed_cycles=0,
        authorization=f'Operator requested {args.cycles} full-calibration repetitions, verifying IDLE before each cycle.',
        profile_sha256=SHA,cycles=[],automatic_retries=False,operator_visual_assessment='not inferred from telemetry')
    path=folder/'run.json'
    def save():
        temp=path.with_suffix('.tmp');temp.write_text(json.dumps(record,indent=2),encoding='utf-8');temp.replace(path)
    save(); print(json.dumps(dict(batch_record=str(path))),flush=True)
    dispatched=False
    try:
        ui=api('researcher/api/lacry/state'); seq=api('seq')
        if ui['running']['active'] or ui.get('pending') or seq['active']:
            raise RuntimeError('Another operation or pending plan exists.')
        state=api('state')
        if not state['robot'].get('connected'):
            # Initial idle reconnect only; never reconnect/retry an executing cycle.
            api('connect',dict(ip='192.168.201.220'));state=api('state')
        r=healthy(state);record['start_location']=start_location(r['pose_mm'])
        if abs(r['external_axes']['E1']-28)>.15:raise RuntimeError('Expected released, open jaws at IDLE or holder clearance.')
        if api('researcher/api/status')['hand_guiding']['state']!='off':raise RuntimeError('Hand guiding active.')
        record['initial_state']=state;record['status']='running';save()
        previous_receipt=(seq.get('result') or {}).get('record')
        first=1
        if args.reconcile_first_cycle:
            old=json.loads(args.reconcile_first_cycle.read_bytes())
            if (old['completed_cycles']!=0 or len(old['cycles'])!=1
                    or old['cycles'][0]['phases'][0].get('status')!='completed'
                    or "'ok': None" not in old.get('error','') or old['profile_sha256']!=SHA):
                raise RuntimeError('Not the reviewed first-cycle status handoff failure.')
            receipt=verify_finish(ui['running'],seq,state,'calibration',None)
            data=json.loads(Path(receipt).read_bytes())
            if not old['cycles'][0]['phases'][1]['started_at'] < data['at'] < old['finished_at']+10:
                raise RuntimeError('Completion receipt is not from the interrupted reporting interval.')
            cycle=old['cycles'][0]
            cycle.update(status='controller_completed_reconciled',completion_receipt=receipt,
                         reconciliation='Fresh terminal UI, sequence receipt and final pose verify cycle 1; no replay.')
            cycle['phases'][1].update(status='completed_reconciled',running=ui['running'],sequence=seq,state=state)
            record.update(completed_cycles=1,cycles=[cycle],reconciled_from=str(args.reconcile_first_cycle),
                          original_stop_error=old['error'])
            first=2;save()
            print(json.dumps(dict(cycle=1,status='completion_reconciled_no_replay')),flush=True)
        for number in range(first,args.cycles+1):
            cycle=dict(number=number,started_at=time.time(),status='running',phases=[])
            record['cycles'].append(cycle);save()
            for phase,button in [('idle','move_idle'),('calibration','full_calibration')]:
                state=api('state');r=healthy(state)
                if abs(r['external_axes']['E1']-28)>.15:
                    raise RuntimeError('Expected empty jaws open to 28 mm before the next phase.')
                if phase=='idle' and start_location(r['pose_mm'])=='idle':
                    cycle['phases'].append(dict(phase='idle',status='already_at_idle_verified',
                                               state=state,at=time.time(),motion_started=False))
                    save();print(json.dumps(dict(cycle=number,phase='idle',status='already_at_idle_verified')),flush=True)
                    continue
                near(r['pose_mm'],END if phase=='idle' else IDLE)
                if phase=='calibration':
                    # The explicit repeat request authorizes a new session;
                    # keep the normal once-per-session planner rule intact.
                    renewal=api('researcher/api/lacry/plate-session/begin',
                        dict(reason=f'Operator-requested calibration repetition {number} of {args.cycles}.'))
                    if renewal.get('motion_started') is not False or renewal.get('session',{}).get('calibrated') is not False:
                        raise RuntimeError('New calibration session did not verify.')
                    cycle['calibration_session']=renewal;save()
                plan=api('researcher/api/lacry/button/'+button,{})['plan']
                if phase=='idle':
                    if plan['dispatch']!='ik_home_return' or not plan['preserve_gripper']:
                        raise RuntimeError('Unexpected IDLE planner or startup request.')
                    near(plan['home'],IDLE);near(plan['start'],r['pose_mm'])
                elif plan['dispatch']!='classic_pickup' or [s['label'] for s in plan['steps']]!=LABELS:
                    raise RuntimeError('Full calibration plan changed.')
                event=dict(phase=phase,plan=plan,started_at=time.time(),samples=[])
                cycle['phases'].append(event);save()
                print(json.dumps(dict(cycle=number,phase=phase,status='starting')),flush=True)
                dispatched=True # A timeout from confirm is uncertain; never repeat it.
                event['dispatch']=api('researcher/api/lacry/confirm',dict(ready=True,plan_id=plan['id']))
                deadline=time.monotonic()+(180 if phase=='idle' else 600)
                last_step=None
                handoff_deadline=None
                while True:
                    state=api('state');r=healthy(state)
                    ui=api('researcher/api/lacry/state');seq=api('seq');running=ui['running']
                    event['samples'].append(dict(at=time.time(),step=running['step'],sequence=seq['name'],
                        pose_mm=r['pose_mm'],e1_mm=r['external_axes']['E1']))
                    if running['step']!=last_step:
                        print(json.dumps(dict(cycle=number,phase=phase,step=running['step'])),flush=True)
                        last_step=running['step'];save()
                    if terminal(running):
                        receipt=verify_finish(running,seq,state,phase,previous_receipt)
                        if receipt:previous_receipt=receipt
                        event.update(status='completed',finished_at=time.time(),state=state,sequence=seq,running=running)
                        dispatched=False;save();break
                    if not running['active']:
                        if handoff_deadline is None:handoff_deadline=time.monotonic()+10
                        if time.monotonic()>handoff_deadline:
                            raise TimeoutError('Final workflow result was not published; no replay.')
                    else:handoff_deadline=None
                    if time.monotonic()>deadline:raise TimeoutError('No verified completion before deadline.')
                    time.sleep(2)
            cycle.update(status='controller_completed',finished_at=time.time())
            record['completed_cycles']=number;save()
            print(json.dumps(dict(cycle=number,status='completed',completed_cycles=number)),flush=True)
        record['status']='all_requested_cycles_controller_completed'
    except BaseException as error:
        record.update(status='stopped_or_uncertain',error=str(error))
        if dispatched:
            try:record['stop_response']=api('researcher/api/lacry/stop',{})
            except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        record['finished_at']=time.time();save()
        print(json.dumps(dict(status=record['status'],completed_cycles=record['completed_cycles'],record=str(path))),flush=True)


if __name__=='__main__':main()
