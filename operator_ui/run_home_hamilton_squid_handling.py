"""Select full calibration and/or HOME station handling; no instrument runs.

--execute confirms a plate supported in HOME, released jaws for calibration,
clear routes and supervised E-stop. Selected station trips also require an
empty destination holder and open Hamilton access. The Squid position
is bound to the operator-confirmed current successful loading setup, without
changing the saved microscope-stage reference or moving its stage.
"""
import argparse
import json
import math
from pathlib import Path
import time
from uuid import uuid4

from proof_lift_plate import api
from repeat_holder_calibration_20261110 import healthy
from squid_adapter import native_command, SquidAdapter
from run_record_io import write_run_record

ROOT=Path(__file__).resolve().parents[1]


def parse_args(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycles', type=int,default=1,help='Station-handling repetitions; calibration runs once (default: 1).')
    parser.add_argument('--full-calibration',action='store_true',help='Fresh calibration, ending with plate released in HOME. Visits IDLE first.')
    parser.add_argument('--home-to-hamilton-roundtrip',action='store_true',help='Deliver, release, return empty, retrieve and reseat in HOME.')
    parser.add_argument('--home-to-squid-roundtrip',action='store_true',help='Deliver, release, return empty, retrieve and reseat in HOME.')
    parser.add_argument('--calibration-record',type=Path,help='Fresh calibration receipt when skipping calibration.')
    parser.add_argument('--source',type=Path,help='Fresh completed HOME release receipt for station handling.')
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args(argv)
    if args.cycles < 1:parser.error('--cycles must be at least 1.')
    if not any((args.full_calibration,args.home_to_hamilton_roundtrip,args.home_to_squid_roundtrip)):
        if args.calibration_record: # Preserve the original combined command.
            args.home_to_hamilton_roundtrip=args.home_to_squid_roundtrip=True
        else:parser.error('Select at least one workflow flag.')
    if args.full_calibration and (args.calibration_record or args.source):
        parser.error('Fresh calibration creates its own receipt; omit --source and --calibration-record.')
    if args.source and args.calibration_record:
        parser.error('Supply only one starting receipt: --source or --calibration-record.')
    if args.cycles > 1 and not (args.home_to_hamilton_roundtrip or args.home_to_squid_roundtrip):
        parser.error('--cycles repeats station handling. Select a Hamilton or Squid round trip; calibration runs once.')
    return args


def selection(args):
    return [label for enabled,label in (
        (args.full_calibration,'Full calibration (IDLE first; finish released at HOME)'),
        (args.home_to_hamilton_roundtrip,'HOME -> Hamilton drop-off -> empty HOME -> retrieval -> HOME release'),
        (args.home_to_squid_roundtrip,'HOME -> Squid drop-off -> empty HOME -> retrieval -> HOME release')) if enabled]


def find_source(args):
    """Select evidence only; the server still verifies age, pose, axes and reuse."""
    explicit=args.calibration_record or args.source
    if explicit:return explicit.resolve()
    from home_hamilton_exchange import calibration_evidence
    from hamilton_holder_dropoff import FOLDER as hf,STATUSES
    from home_squid_transfer import FOLDER as sf
    candidates=[]
    for p in (ROOT/'operator_ui/reports/plate_session').glob('calibration_hamilton_*/calibration_*.json'):
        try:
            data,_=calibration_evidence(p)
            candidates.append((data['phases'][-1]['finished_at'],p.resolve()))
        except (ValueError,KeyError,OSError,RuntimeError):continue
    folders=[(hf,STATUSES['finish_home'])]
    if not args.home_to_hamilton_roundtrip:folders.append((sf,'plate_released_at_HOME_clearance'))
    for folder,status in folders:
        for p in folder.glob('*.json'):
            try:
                d=json.loads(p.read_bytes());at=d.get('finished_at',0)
                if d.get('status')==status and 0<=time.time()-at<=1800:candidates.append((at,p.resolve()))
            except (ValueError,OSError):continue
    if not candidates:raise RuntimeError('No fresh HOME receipt. Run --full-calibration or supply a fresh --calibration-record/--source.')
    # Never fall back to older evidence when the newest receipt fails validation.
    return max(candidates,key=lambda item:item[0])[1]


def hamilton_delivery(source):
    data=json.loads(Path(source).read_bytes())
    if data.get('status')=='calibration_completed_at_HOME':
        return ('developer/api/home-hamilton-exchange',dict(calibration_record=str(source),delivery_only=True),'home_hamilton_exchange')
    return ('developer/api/hamilton-holder-dropoff',dict(source=str(source),phase='deliver'),'hamilton_holder_dropoff')


def calibrate():
    from repeat_calibration_hamilton import Batch
    b=Batch(1);cycle=dict(number=1,phases=[]);b.record['cycles'].append(cycle)
    try:
        b.start();b.ui_phase(cycle,'idle','move_idle')
        b.developer_phase(cycle,'restore_original','developer/api/home-hamilton-exchange/restore-original',
            dict(ready=True,empty_gripper=True,holder_clear=True),'home_hamilton_restore_original')
        b.ui_phase(cycle,'calibration','full_calibration')
        b.record.update(status='calibration_completed_at_HOME',completed_cycles=1)
        return cycle['calibration_record']
    except BaseException as error:
        b.record.update(status='stopped_or_uncertain',error=str(error))
        if b.dispatched:
            try:b.record['stop_response']=api('researcher/api/lacry/stop',{})
            except Exception as e:b.record['stop_error']=str(e)
        raise
    finally:b.record['finished_at']=time.time();b.save()


def run_selected(args,phase,state,hamilton_ready,squid_ready,record,save,say):
    """Calibrate once; advance receipts only after each requested phase succeeds."""
    source=calibrate() if args.full_calibration else str(find_source(args))
    calibration_source=source
    record['starting_receipt']=source;save()
    both=args.home_to_hamilton_roundtrip and args.home_to_squid_roundtrip
    if both and args.cycles > 1:
        if json.loads(Path(calibration_source).read_bytes()).get('status')!='calibration_completed_at_HOME':
            raise RuntimeError('Combined repeats require --full-calibration or a fresh --calibration-record; no handling started.')
    handling=args.home_to_hamilton_roundtrip or args.home_to_squid_roundtrip
    for number in range(1,args.cycles+1) if handling else ():
        # Squid returns to long-side HOME. Use the session calibration binding
        # for its existing checked rotation/short-side connection, not Squid's
        # receipt in the short-side-only delivery executor. No fresh calibration.
        previous_release=source
        if both and number > 1:source=calibration_source
        cycle=dict(number=number,status='starting',at=time.time(),starting_receipt=source,
                   previous_release_receipt=previous_release,first_phase_index=len(record['phases']))
        record['cycles'].append(cycle);record['current_cycle']=number;save()
        say(cycle=number,total=args.cycles,status='starting')
        try:
            state()
            if args.home_to_hamilton_roundtrip:
                hamilton_ready()
                source=phase('Hamilton delivery',*hamilton_delivery(source))
                for step in ('release','return','retrieve','finish_home'):
                    if step=='retrieve':hamilton_ready()
                    source=phase('Hamilton '+step,'developer/api/hamilton-holder-dropoff',dict(source=source,phase=step),'hamilton_holder_dropoff')
            if args.home_to_squid_roundtrip:
                squid_ready()
                source=phase('Squid delivery','developer/api/home-squid-transfer',dict(source=source),'home_squid_transfer')
                for step in ('release_squid','empty_return','retrieve'):
                    squid_ready()
                    source=phase('Squid '+step,'developer/api/home-squid-handling',dict(source=source,phase=step),'home_squid_handling')
                source=phase('Final HOME release','developer/api/home-squid-return',dict(source=source,phase='release_home'),'home_squid_return')
            final=state()
            cycle.update(status='controller_completed',final_receipt=source,final=final,finished_at=time.time(),
                         end_phase_index=len(record['phases']))
            record['completed_cycles']=number;record['final_receipt']=source;save()
            say(cycle=number,total=args.cycles,status='completed',completed_cycles=number)
        except BaseException as error:
            cycle.update(status='stopped_or_uncertain',error=str(error),finished_at=time.time())
            save();raise
    return source


def main(argv=None):
    args=parse_args(argv)
    if not args.execute:
        print(json.dumps(dict(steps=selection(args),motion_started=False,
            calibration_runs=1 if args.full_calibration else 0,
            handling_cycles=args.cycles if args.home_to_hamilton_roundtrip or args.home_to_squid_roundtrip else 0,
            grip='Approach speed10; final1mm speed5; long-side3.9mm, short-side25mm',
            receipt='Fresh evidence and current pose required; no retries.'),indent=2))
        return
    folder=ROOT/'operator_ui/reports/plate_session'/('continuous_grip_handling_'+uuid4().hex)
    folder.mkdir(parents=True,exist_ok=False);path=folder/'run.json'
    record=dict(status='checking',at=time.time(),selected_workflows=selection(args),phases=[],cycles=[],
        planned_cycles=args.cycles if args.home_to_hamilton_roundtrip or args.home_to_squid_roundtrip else 0,
        completed_cycles=0,current_cycle=None,
        authorization='Operator requested calibration, Hamilton drop-off/retrieval, then Squid drop-off/retrieval and HOME. Hamilton access open/site4 empty confirmed; Squid unchanged from accepted direct round trip.',
        automatic_retries=False,operator_retention_result='pending')
    dispatched=False
    def save():
        write_run_record(path,record)
    def say(**value):print(json.dumps(value),flush=True)
    def state():
        s=api('state');healthy(s);return s
    def squid_ready():
        s=SquidAdapter(background=False).connect()
        if s.get('stage_simulated') is not False or s['status'] not in ('idle','historical','completed'):
            raise RuntimeError('Squid must remain idle, physical stage at confirmed loading setup.')
        p=native_command('get_position')
        for k,v in record['squid_loading_position'].items():
            actual=p.get(k)
            if type(actual) not in (int,float) or not math.isfinite(actual) or abs(actual-v)>.02:
                raise RuntimeError('Squid moved from current operator-confirmed loading setup.')
    def hamilton_ready():
        h=api('researcher/api/lacry/hamilton/status')
        if not h.get('connected') or h.get('global_state')!='Idle' or h.get('parked') is not True or h.get('pending_errors') or h.get('operation'):
            raise RuntimeError('Hamilton not idle/parked/error-free; no approach.')
    def phase(label,base,body,name):
        nonlocal dispatched
        state()
        if api('seq')['active'] or api('researcher/api/lacry/state')['running']['active']:
            raise RuntimeError('Another operation is active.')
        p=api(base+'/preview',body)['plan']
        event=dict(label=label,cycle=record['current_cycle'],at=time.time(),plan=p,status='dispatching',samples=[])
        record['phases'].append(event);save();say(phase=label,status='starting')
        dispatched=True
        response=api(base+'/start',dict(plan=p,ready=True,setup_confirmed=True,path_clear=True))
        event['dispatch']=response;save()
        if response.get('started')!=name:raise RuntimeError('Unexpected dispatcher.')
        deadline=time.monotonic()+240;last=None
        while True:
            s=state();q=api('seq')
            if q.get('name')!=name:raise RuntimeError('Sequence ownership changed.')
            line=(q.get('log') or [{}])[-1].get('msg')
            event['samples'].append(dict(at=time.time(),pose=s['robot']['pose_mm'],axes=s['robot']['external_axes']))
            if line!=last:say(phase=label,step=line);last=line
            save()
            if not q['active']:
                result=q.get('result') or {}
                if result.get('ok') is not True:raise RuntimeError('Sequence failed: '+str(result.get('error',result)))
                receipt=Path(result['record']).resolve()
                if ROOT/'operator_ui/reports/plate_session' not in receipt.parents or receipt.stem!=p['id']:
                    raise RuntimeError('Completion receipt mismatch.')
                evidence=json.loads(receipt.read_bytes())
                if evidence.get('at',0)<event['at']:raise RuntimeError('Stale completion receipt.')
                event.update(status='completed',result=result,final=s,finished_at=time.time());dispatched=False;save()
                say(phase=label,status='completed',pose=s['robot']['pose_mm'])
                return str(receipt)
            if time.monotonic()>deadline:raise TimeoutError('Handling timed out; no retry.')
            time.sleep(.5)
    try:
        save();say(record=str(path))
        if not api('state')['robot'].get('connected'):api('connect',{'ip':'192.168.201.220'})
        state()
        if args.home_to_hamilton_roundtrip:hamilton_ready()
        if args.home_to_squid_roundtrip:
            record['squid_loading_position']=native_command('get_position');squid_ready();save()
        source=run_selected(args,phase,state,hamilton_ready,squid_ready,record,save,say)
        record.update(status='controller_completed_pending_operator_assessment',final_receipt=source,final=state())
    except BaseException as error:
        record.update(status='stopped_or_uncertain',error=str(error))
        if dispatched:
            try:record['stop_response']=api('researcher/api/lacry/stop',{})
            except Exception as se:record['stop_error']=str(se)
        raise
    finally:
        record['finished_at']=time.time();save();say(status=record['status'],completed_cycles=record['completed_cycles'],record=str(path))


if __name__=='__main__':main()
