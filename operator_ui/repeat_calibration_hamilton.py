"""Repeat fresh 48-well calibration and HOME -> Hamilton -> HOME. No retries.

Run without --execute for a nonmoving plan. --execute confirms empty jaws,
plate seated in HOME, both routes/holder rotation clear, hands clear and E-stop
supervision for the requested batch. Never starts/enables/resets the controller.
At IDLE, empty jaws are opened automatically. At HOME, release/open28 first.

--idle-only returns through the existing IDLE planner instead of running a
batch. --execute confirms the full return path/sweep is clear, hands are clear,
the arm is released, the E-stop is supervised, and any held plate is secure
and free to lift. This mode preserves the jaws; it never releases a plate or
starts/enables/resets the controller. Flask must already be running.
"""
import argparse
import json
import math
from pathlib import Path
import time
from uuid import uuid4

from repeat_holder_calibration_20261110 import api,healthy,near,terminal,verify_finish,IDLE,END,LABELS,ROOT,SHA,at_idle_pose,require_idle_pose
from short_side_hover_transfer import reference
from draggo import DragGoRPC
from run_record_io import write_run_record


class Batch:
    def __init__(self,cycles):
        self.folder=ROOT/'operator_ui/reports/plate_session'/('calibration_hamilton_'+uuid4().hex)
        self.folder.mkdir(parents=True,exist_ok=False)
        self.record=dict(status='preflight',at=time.time(),planned_cycles=cycles,completed_cycles=0,
            cycles=[],profile_sha256=SHA,automatic_retries=False,
            operator_visual_result='Not inferred from controller completion')
        self.dispatched=False;self.previous_receipt=None
        self.cycles=cycles
        _,_,self.grip=reference('04')
        self.clearance=dict(self.grip['descent_endpoint'],Z=self.grip['descent_endpoint']['Z']+30)
        self.save()

    def save(self):
        write_run_record(self.folder/'run.json',self.record)

    def say(self,**message):print(json.dumps(message),flush=True)

    def state(self,empty=False):
        s=api('state');r=healthy(s)
        e1=r['external_axes']['E1']
        if not math.isfinite(e1):raise RuntimeError('Invalid jaw-position feedback.')
        if empty and abs(e1-28)>.15:raise RuntimeError('Expected empty jaws open to28 mm.')
        return s

    def open_empty_at_idle(self):
        """One opening command at the parking pose; never infer an empty payload."""
        s=self.state();start=s['robot']['pose_mm'];require_idle_pose(start)
        n=DragGoRPC('192.168.201.220').info()
        if any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):
            raise RuntimeError('Stationary Auto required before empty-jaw opening.')
        e1=n['external_axes']['E1']
        if not math.isfinite(e1) or not -.15<=e1<=28.15:raise RuntimeError('Unexpected jaw position; no opening sent.')
        if abs(e1-28)<=.15:return
        event=dict(status='dispatching',at=time.time(),start=start,target_e1_mm=28,
            empty_gripper_basis='Operator --execute setup confirmation; not inferred from jaw reading')
        self.record['idle_jaw_preparation']=event;self.save()
        self.say(phase='prepare_idle',step='Open confirmed-empty jaws to28 mm')
        self.dispatched=True
        result=api('gripper',dict(action='move',e1=28,speed=5))
        event['result']=result;self.save()
        if result.get('ok') is not True or result.get('recovered'):
            raise RuntimeError('Empty-jaw opening failed or uncertain; no retry.')
        after=self.state(empty=True);near(after['robot']['pose_mm'],start,.05)
        end=DragGoRPC('192.168.201.220').info()
        if any(end.get(k,True) for k in ('moving','error','emergency','drag','manual')):
            raise RuntimeError('Controller not settled after opening.')
        if not math.isfinite(end['external_axes']['E1']) or abs(end['external_axes']['E1']-28)>.15:
            raise RuntimeError('Opening feedback did not reach28 mm.')
        event.update(status='completed',finished_at=time.time(),final=after)
        self.dispatched=False;self.save()

    def start(self):
        ui=api('researcher/api/lacry/state');seq=api('seq')
        if ui['running']['active'] or ui.get('pending') or seq['active']:
            raise RuntimeError('Another operation or pending plan exists.')
        s=api('state')
        if not s['robot'].get('connected'):
            api('connect',{'ip':'192.168.201.220'});s=api('state')
        n=DragGoRPC('192.168.201.220').info()
        if any(n.get(k,True) for k in ('moving','error','emergency','drag')):
            raise RuntimeError('Arm must be stationary, fault-free, with hand-guiding off.')
        r=s['robot']
        self.record['initial']=s;self.save()
        if not r.get('enabled') or r.get('errors') or r.get('program_state',{}).get('state')!='running':
            raise RuntimeError('Prepare the empty controller first; no automatic startup/reset.')
        e1=n['external_axes']['E1']
        if not math.isfinite(e1):raise RuntimeError('Invalid jaw-position feedback.')
        at_idle=at_idle_pose(r['pose_mm'])
        poses=[END,self.clearance,self.grip['descent_endpoint']]
        if not at_idle and not any(all(abs(r['pose_mm'][k]-p[k])<=.1 for k in IDLE) for p in poses):
            raise RuntimeError('Start at IDLE or an accepted released HOME seating/clearance pose.')
        if not at_idle and abs(e1-28)>.15:
            raise RuntimeError('At HOME, release the supported plate and open to28 mm before leaving the holder.')
        if r['control_mode']['mode']=='manual':api('mode',{'mode':'auto'})
        if at_idle:self.open_empty_at_idle()
        self.record['prepared']=self.state(empty=True);self.save()

    def ui_phase(self,cycle,phase,button):
        r=self.state(empty=True)['robot']
        if phase=='calibration':
            require_idle_pose(r['pose_mm'])
            renewal=api('researcher/api/lacry/plate-session/begin',
                {'reason':f'Operator-requested calibration/Hamilton cycle {cycle["number"]} of {self.cycles}'})
            if renewal.get('motion_started') is not False or renewal.get('session',{}).get('calibrated') is not False:
                raise RuntimeError('Fresh calibration session not established.')
        else:
            if at_idle_pose(r['pose_mm']):
                cycle['phases'].append(dict(phase='idle',status='already_at_idle_verified',
                    state=r,motion_started=False,at=time.time()))
                self.save();self.say(cycle=cycle['number'],phase=phase,status='already_at_idle_verified')
                return
        plan=api('researcher/api/lacry/button/'+button,{})['plan']
        if phase=='idle':
            if plan['dispatch']!='ik_home_return' or not plan['preserve_gripper']:raise RuntimeError('Unexpected IDLE preparation.')
            near(plan['start'],r['pose_mm']);near(plan['home'],IDLE)
        elif plan['dispatch']!='classic_pickup' or [x['label'] for x in plan['steps']]!=LABELS:
            raise RuntimeError('Full calibration stages changed.')
        event=dict(phase=phase,plan=plan,started_at=time.time(),samples=[])
        cycle['phases'].append(event);self.save()
        self.dispatched=True
        event['dispatch']=api('researcher/api/lacry/confirm',{'ready':True,'plan_id':plan['id']})
        deadline=time.monotonic()+(600 if phase=='calibration' else 180)
        last=None;handoff=None
        while True:
            s=self.state();ui=api('researcher/api/lacry/state');seq=api('seq');running=ui['running']
            event['samples'].append(dict(at=time.time(),step=running.get('step'),pose=s['robot']['pose_mm']))
            if running.get('step')!=last:
                last=running.get('step');self.say(cycle=cycle['number'],phase=phase,step=last);self.save()
            if terminal(running):
                receipt=verify_finish(running,seq,s,phase,self.previous_receipt)
                if receipt:self.previous_receipt=receipt
                event.update(status='completed',sequence=seq,state=s,running=running,finished_at=time.time())
                self.dispatched=False;self.save()
                if phase=='calibration':
                    path=self.folder/f'calibration_{cycle["number"]}.json'
                    path.write_text(json.dumps(dict(status='calibration_completed_at_HOME',final=s['robot'],phases=[event]),indent=2))
                    cycle['calibration_record']=str(path);self.save()
                return
            if not running['active']:
                if handoff is None:handoff=time.monotonic()+10
                if time.monotonic()>handoff:raise TimeoutError('Workflow completion publication missing; no replay.')
            else:handoff=None
            if time.monotonic()>deadline:raise TimeoutError('Workflow timed out; no replay.')
            time.sleep(1)

    def developer_phase(self,cycle,phase,path,body,name):
        event=dict(phase=phase,started_at=time.time(),samples=[])
        cycle['phases'].append(event);self.save();self.say(cycle=cycle['number'],phase=phase,status='starting')
        self.dispatched=True;reply=api(path,body);event['dispatch']=reply;self.save()
        if reply.get('started')!=name:raise RuntimeError('Unexpected sequence dispatch.')
        deadline=time.monotonic()+240;last=None
        while True:
            s=self.state();seq=api('seq')
            event['samples'].append(dict(at=time.time(),pose=s['robot']['pose_mm'],sequence=seq['name']))
            if seq['name']!=name:raise RuntimeError('Sequence ownership changed; no retry.')
            message=(seq.get('log') or [{}])[-1].get('msg')
            if message!=last:self.say(cycle=cycle['number'],phase=phase,step=message);last=message;self.save()
            if not seq['active']:
                result=seq.get('result') or {}
                if result.get('ok') is not True:raise RuntimeError('Sequence failed: '+str(result))
                receipt=Path(result['record']).resolve()
                allowed=ROOT/'operator_ui/reports/plate_session/hamilton_exchanges'
                if allowed not in receipt.parents:raise RuntimeError('Unexpected receipt location.')
                evidence=json.loads(receipt.read_bytes())
                if evidence.get('at',0)<event['started_at']:raise RuntimeError('Stale sequence receipt.')
                self.state(empty=True)
                if phase=='exchange':
                    if receipt.stem!=body['plan']['id'] or evidence['status']!='completed_pending_operator_observation':
                        raise RuntimeError('Incomplete exchange receipt.')
                    if result.get('payload')!='empty' or result.get('station')!='HOME':raise RuntimeError('Release not verified.')
                    near(s['robot']['pose_mm'],self.clearance,.1)
                else:
                    if evidence['status']!='completed':raise RuntimeError('Holder restore incomplete.')
                    require_idle_pose(s['robot']['pose_mm'])
                event.update(status='completed',sequence=seq,state=s,finished_at=time.time())
                self.dispatched=False;self.save();return
            if time.monotonic()>deadline:raise TimeoutError('Sequence timed out; no replay.')
            time.sleep(1)

    def run(self):
        self.say(batch_record=str(self.folder/'run.json'))
        try:
            self.start();self.record['status']='running'
            for number in range(1,self.cycles+1):
                cycle=dict(number=number,phases=[],status='running');self.record['cycles'].append(cycle);self.save()
                self.ui_phase(cycle,'idle','move_idle')
                self.developer_phase(cycle,'restore_original','developer/api/home-hamilton-exchange/restore-original',
                    dict(ready=True,empty_gripper=True,holder_clear=True),'home_hamilton_restore_original')
                self.ui_phase(cycle,'calibration','full_calibration')
                plan=api('developer/api/home-hamilton-exchange/preview',{'calibration_record':cycle['calibration_record']})['plan']
                if plan.get('holder_tolerances_deg')!={'arrival':.1,'monitor':.5}:raise RuntimeError('Load the updated holder tolerance before running.')
                cycle['exchange_plan']=plan;self.save()
                self.developer_phase(cycle,'exchange','developer/api/home-hamilton-exchange/start',
                    dict(plan=plan,ready=True,path_clear=True,setup_confirmed=True),'home_hamilton_exchange')
                cycle['status']='controller_completed';self.record['completed_cycles']=number;self.save()
                self.say(cycle=number,status='completed',completed_cycles=number,total=self.cycles)
            self.record['status']='all_requested_cycles_controller_completed'
        except BaseException as error:
            self.record.update(status='stopped_or_uncertain',error=str(error))
            if self.dispatched:
                try:self.record['stop_response']=api('researcher/api/lacry/stop',{})
                except Exception as stop_error:self.record['stop_error']=str(stop_error)
            raise
        finally:
            self.record['finished_at']=time.time();self.save()
            self.say(status=self.record['status'],completed_cycles=self.record['completed_cycles'],record=str(self.folder/'run.json'))


def return_idle():
    """CLI for the existing checked IDLE API, without a second motion planner."""
    from ik_home import ready_auto
    folder=ROOT/'operator_ui/reports/plate_session'/('idle_'+uuid4().hex)
    folder.mkdir(parents=True,exist_ok=False)
    path=folder/'run.json'
    record=dict(status='checking',at=time.time(),automatic_retries=False,
                authorization='--idle-only --execute: route clear, payload secure or empty, E-stop supervised',
                samples=[])
    dispatched=False
    def save():
        write_run_record(path,record)
    def say(**message):print(json.dumps(message),flush=True)
    def checked_state():
        s=api('state');r=s['robot']
        if (not r.get('connected') or not r.get('ok') or r.get('errors')
                or not ready_auto(r) or not s['envelope']['enabled']):
            raise RuntimeError('IDLE return requires healthy, already-running Auto and enabled workspace; no startup/reset sent.')
        value=r.get('external_axes',{}).get('E1')
        if type(value) not in (int,float) or not math.isfinite(value):
            raise RuntimeError('Fresh claw position unavailable.')
        return s
    save();say(record=str(path),phase='idle',status='checking')
    try:
        ui=api('researcher/api/lacry/state');seq=api('seq')
        if ui['running']['active'] or ui.get('pending') or seq['active']:
            raise RuntimeError('Another operation or pending plan exists; finish or cancel it first.')
        if not api('state')['robot'].get('connected'):
            api('connect',{'ip':'192.168.201.220'})
        s=checked_state();record['initial']=s;save()
        n=DragGoRPC('192.168.201.220').info()
        if any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):
            raise RuntimeError('IDLE return requires stationary Auto with hand-guiding off.')
        if at_idle_pose(s['robot']['pose_mm']):
            record.update(status='already_at_idle_verified',final=s)
            return
        plan=api('researcher/api/lacry/button/move_idle',{})['plan']
        record['plan']=plan;save()
        if plan.get('dispatch')!='ik_home_return' or plan.get('preserve_gripper') is not True:
            raise RuntimeError('Expected the existing IK IDLE plan preserving the claw; no motion confirmed.')
        near(plan['home'],IDLE);near(plan['start'],s['robot']['pose_mm'])
        if abs(plan['e1']-s['robot']['external_axes']['E1'])>.05:
            raise RuntimeError('Claw changed while planning; no motion confirmed.')
        say(phase='idle',status='starting',steps=plan['steps'])
        dispatched=True;record['status']='dispatching';save()
        record['dispatch']=api('researcher/api/lacry/confirm',{'ready':True,'plan_id':plan['id']});save()
        deadline=time.monotonic()+180;last=None
        while True:
            s=checked_state();seq=api('seq');running=api('researcher/api/lacry/state')['running']
            r=s['robot']
            if abs(r['external_axes']['E1']-plan['e1'])>.15:
                raise RuntimeError('Claw changed during IDLE return.')
            if seq.get('name')!='researcher_home':
                raise RuntimeError('Unexpected sequence during IDLE return.')
            record['samples'].append(dict(at=time.time(),pose=r['pose_mm'],e1=r['external_axes']['E1'],step=running.get('step')))
            progress=(seq.get('log') or [{}])[-1].get('msg',running.get('step'))
            if progress!=last:say(phase='idle',step=progress);last=progress
            save()
            if not seq['active'] and (seq.get('result') or {}).get('ok') is not True:
                raise RuntimeError('IDLE motion failed: '+str(seq.get('result')))
            if terminal(running):
                if running.get('ok') is not True or seq['active']:
                    raise RuntimeError('IDLE workflow did not verify completion: '+str(running))
                require_idle_pose(r['pose_mm'])
                record.update(status='completed',final=s,sequence=seq,running=running)
                dispatched=False
                return
            if time.monotonic()>deadline:raise TimeoutError('IDLE return timed out; no retry.')
            time.sleep(.5)
    except BaseException as error:
        record.update(status='stopped_or_uncertain',error=str(error))
        if dispatched:
            try:record['stop_response']=api('researcher/api/home/stop',{})
            except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        record['finished_at']=time.time();save()
        say(status=record['status'],record=str(path),pose=record.get('final',{}).get('robot',{}).get('pose_mm'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--cycles',type=int,choices=range(1,11),help='Calibration/Hamilton repetitions (default: 5).')
    mode.add_argument('--idle-only',action='store_true',help='Return to IDLE only; preserve jaws; skip calibration/Hamilton.')
    parser.add_argument('--execute',action='store_true',help='Confirm the setup described above and execute; otherwise show a nonmoving summary.')
    args=parser.parse_args()
    if args.cycles is None:args.cycles=5
    if args.idle_only:
        if not args.execute:
            print(json.dumps(dict(motion_started=False,sequence=['Return IDLE via existing IK planner'],
                target=IDLE,preserve_gripper=True,requires='Already-running Auto; route clear; secure payload or empty jaws; E-stop supervised',
                automatic_retries=False),indent=2))
            return
        return_idle()
        return
    if not args.execute:
        print(json.dumps(dict(cycles=args.cycles,motion_started=False,sequence=[
            'Empty return to IDLE','Restore released holder to1.77 degrees','Fresh full calibration',
            'Rotate to90.717; short-side pickup','Hamilton overhead route','Direct HOME return, release28, empty rise30'],
            transit_speed=137,monitor_tolerance_degrees=.5,automatic_retries=False),indent=2))
        return
    Batch(args.cycles).run()


if __name__=='__main__':main()
