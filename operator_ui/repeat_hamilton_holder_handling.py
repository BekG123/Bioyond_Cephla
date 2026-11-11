"""Repeat accepted HOME/Hamilton release/retrieval through the sole Flask owner."""
import argparse
import json
from pathlib import Path
import time
from uuid import uuid4

from proof_lift_plate import api
from hamilton_holder_dropoff import FOLDER, STATUSES

PHASES=('deliver','release','return','retrieve','finish_home')


def batch(source,cycles):
    folder=FOLDER/('batch_'+uuid4().hex);folder.mkdir(parents=True)
    record=dict(status='running',started_at=time.time(),requested_cycles=cycles,completed_cycles=0,
                source=str(Path(source).resolve()),cycles=[])
    dispatched=False
    def save():
        (folder/'run.json').write_text(json.dumps(record,indent=2))
    save()
    try:
        for number in range(1,cycles+1):
            cycle=dict(number=number,phases=[]);record['cycles'].append(cycle);save()
            for phase in PHASES:
                state=api('state');robot=state['robot']
                if (not robot.get('connected') or robot.get('errors') or not robot.get('enabled')
                    or robot.get('program_state',{}).get('state')!='running'
                    or robot.get('control_mode',{}).get('mode')!='auto' or api('seq')['active']):
                    raise RuntimeError('Healthy idle Auto console required; no recovery/retry.')
                plan=api('developer/api/hamilton-holder-dropoff/preview',dict(phase=phase,source=str(Path(source).resolve())))['plan']
                item=dict(phase=phase,plan=plan,status='dispatching',started_at=time.time())
                cycle['phases'].append(item);save()
                print(json.dumps(dict(cycle=number,phase=phase,status='starting')),flush=True)
                dispatched=True
                reply=api('developer/api/hamilton-holder-dropoff/start',dict(plan=plan,ready=True,setup_confirmed=True,path_clear=True))
                if reply.get('started')!='hamilton_holder_dropoff':raise RuntimeError('Unexpected dispatch response.')
                deadline=time.monotonic()+180
                while True:
                    seq=api('seq');state=api('state');robot=state['robot']
                    if seq.get('name')!='hamilton_holder_dropoff':raise RuntimeError('Sequence ownership changed.')
                    if (not robot.get('connected') or robot.get('errors') or not robot.get('enabled')
                        or robot.get('program_state',{}).get('state')!='running'):
                        raise RuntimeError('Controller unhealthy; batch stopped.')
                    if not seq['active']:
                        dispatched=False
                        result=seq.get('result') or {}
                        if result.get('ok') is not True:raise RuntimeError('Phase failed: '+str(result.get('error',result)))
                        receipt=Path(result['record']).resolve()
                        if receipt.parent!=FOLDER.resolve() or receipt.stem!=plan['id']:
                            raise RuntimeError('Unexpected completion receipt.')
                        data=json.loads(receipt.read_bytes())
                        if data['status']!=STATUSES[phase] or data['at']<item['started_at']:
                            raise RuntimeError('Unverified completion.')
                        item.update(status='completed',record=str(receipt),finished_at=time.time())
                        source=receipt;save();break
                    if time.monotonic()>deadline:raise TimeoutError('Phase timed out; no replay.')
                    time.sleep(.5)
            record['completed_cycles']=number;save()
            print(json.dumps(dict(cycle=number,status='controller_completed')),flush=True)
        record['status']='controller_completed_pending_operator_observation'
    except BaseException as error:
        record.update(status='stopped_or_uncertain',error=str(error))
        if dispatched:
            try:record['stop_request']=api('seq/stop',{})
            except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        record['finished_at']=time.time();save()
        print(json.dumps(dict(status=record['status'],completed_cycles=record['completed_cycles'],record=str(folder/'run.json'))),flush=True)
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True,help='Fresh finish_home receipt with plate released in HOME.')
    parser.add_argument('--cycles',type=int,default=5)
    parser.add_argument('--execute',action='store_true',help='Run supervised accepted cycles; confirms unchanged fixtures, clear routes and E-stop supervision.')
    args=parser.parse_args()
    if not 1<=args.cycles<=100:parser.error('--cycles must be 1..100')
    if not args.execute:
        print(json.dumps(dict(cycles=args.cycles,phases=PHASES,travel_speed=137,final_descent_speed=5,grip=25,open=28,motion_started=False)))
        return
    data=json.loads(args.source.read_bytes())
    if args.source.resolve().parent!=FOLDER.resolve() or data.get('status')!=STATUSES['finish_home']:
        parser.error('Source must be a completed finish_home receipt.')
    batch(args.source,args.cycles)


if __name__=='__main__':main()
