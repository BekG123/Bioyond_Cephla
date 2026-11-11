"""Supervised Hamilton and Squid handling rounds; retain fresh phase evidence."""
import argparse
import json
import sys
import time
import hamilton_squid_full_repeat03_20261109 as h
import queued_hamilton_squid_five_20261110 as checks
import dropoff_approach_20261103 as approach
import release_empty_home_20261103 as release
import pickup_squid_home_20261103 as pickup
from squid_handling_route import CURRENT_SOURCE,CURRENT_SHA
from proof_lift_plate import api,near,write

ROOT=approach.FOLDER/'station_handling_five_20261110'
AUTH=('Operator requested five Hamilton release -> empty Home -> Hamilton pickup -> loaded Home '
      '-> Squid release -> empty Home -> Squid pickup -> loaded Home cycles. '
      'Current Hamilton plate support and jaw opening to 7 mm explicitly confirmed. '
      'Standing route clearance, unchanged holders, hands clear and E-stop supervision apply. '
      'Use current routes, 7 mm release and two-speed (approach10, final1mm at5) 3.9 mm pickup, no retries or instrument operations.')

def invoke(module,folder):
    old=sys.argv[:]
    try:
        sys.argv=[module.__file__,'--execute']
        if module is approach:module.main(folder,route_source=CURRENT_SOURCE,route_sha=CURRENT_SHA)
        else:module.main(folder,AUTH,route_source=CURRENT_SOURCE,route_sha=CURRENT_SHA)
    finally:sys.argv=old

def handling(operation,trial,forward,folder):
    h.hamilton_idle()
    body=dict(ready=True,supported_and_clear=True,candidate_sha256=h.hamilton.SHA,
        trial_id=trial,forward_trial_id=forward,operation=operation)
    preview=api('developer/api/hamilton-release/preview',body)
    write(folder/(operation+'_preview.json'),preview)
    if not preview.get('ok'):raise RuntimeError('Hamilton handling preview refused')
    result=api('developer/api/hamilton-release/start',body)
    write(folder/(operation+'_dispatch.json'),result)
    if not result.get('ok'):raise RuntimeError('Hamilton handling start refused')
    deadline=time.monotonic()+180
    while True:
        q=api('seq');r=api('state')['robot']
        if q['name']!='hamilton_release_empty_home' or not r.get('connected') or not r.get('ok') or r.get('errors'):
            raise RuntimeError('Hamilton handling feedback uncertain')
        if not q['active']:
            result=q.get('result') or {}
            if not result.get('ok') or result.get('operation')!=operation:raise RuntimeError('Hamilton handling failed: '+str(result))
            near(r['pose_mm'],h.hamilton.reference()['routes']['forward'][0],.1)
            if abs(r['external_axes']['E1']-(7 if operation=='release' else 3.9))>.15:raise RuntimeError('Hamilton final jaw mismatch')
            write(folder/(operation+'_completion.json'),dict(sequence=q,robot=r));return
        if time.monotonic()>deadline:raise RuntimeError('Hamilton handling timed out')
        time.sleep(.3)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start',type=int,default=1);parser.add_argument('--count',type=int,default=1)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--first-cycle-accepted',action='store_true');args=parser.parse_args()
    if not 1<=args.start<=5 or not 1<=args.count<=6-args.start:raise RuntimeError('Only the five requested cycles')
    out=ROOT/f'cycles_{args.start}_{args.start+args.count-1}'
    if out.exists():raise RuntimeError('Already attempted; preserve evidence')
    s=api('state')
    if not s['robot'].get('connected'):
        if s['sequence']['active']:raise RuntimeError('Active sequence')
        if not api('connect',{'ip':'192.168.201.220'}).get('ok'):raise RuntimeError('Connect failed')
    s=checks.ready();h.hamilton_idle();hp=h.hamilton.reference()
    near(s['robot']['pose_mm'],hp['routes']['reverse'][0] if args.start==1 else hp['routes']['forward'][0],.05)
    if args.start>1:
        prior=json.loads((ROOT/'cycles_1_1/run.json').read_bytes())
        if prior['status']!='completed_pending_operator_assessment':raise RuntimeError('First cycle must complete before remaining four')
    print(json.dumps(dict(validated=True,start=args.start,count=args.count,execute=args.execute)),flush=True)
    if not args.execute:return
    if args.start>1:
        if not args.first_cycle_accepted:raise RuntimeError('First physical handling result must be accepted before continuing')
        acceptance=ROOT/'cycles_1_1/operator_acceptance.json'
        if not acceptance.exists():
            with acceptance.open('x',encoding='utf-8') as f:
                json.dump(dict(at=time.time(),operator_statement='Yes—clean releases and secure pickups; continue four more',
                    scope='Cycle 1: Hamilton and Squid release/pickup with level secure returns',
                    run_sha256=approach.sha(ROOT/'cycles_1_1/run.json'),telemetry_modified=False),f,indent=2)
    out.mkdir(parents=True)
    record=dict(status='running',at=time.time(),authorization=AUTH,start_cycle=args.start,completed_cycles=[],events=[],initial_state=s,automatic_retries=False)
    def phase(cycle,name):
        record.update(cycle=cycle,phase=name);record['events'].append(dict(cycle=cycle,phase=name,at=time.time()))
        write(out/'run.json',record);print(json.dumps(dict(cycle=cycle,phase=name)),flush=True)
    try:
        for cycle in range(args.start,args.start+args.count):
            folder=out/f'cycle_{cycle}';folder.mkdir();h.OUT=folder
            if cycle==1:forward='queue_five_c5_20261110'
            else:
                h.TRIAL=f'handling5_c{cycle}_delivery_20261110'
                phase(cycle,'Home_to_Hamilton');h.travel_hamilton('forward');forward=h.TRIAL
            phase(cycle,'Hamilton_release_and_empty_Home')
            handling('release',f'handling5_c{cycle}_release_20261110',forward,folder)
            h.TRIAL=f'handling5_c{cycle}_pickup_approach_20261110'
            phase(cycle,'Home_to_Hamilton_empty');h.travel_hamilton('forward')
            phase(cycle,'Hamilton_pickup_and_loaded_Home')
            handling('pickup',f'handling5_c{cycle}_pickup_20261110',h.TRIAL,folder)
            delivery=folder/'squid_dropoff';delivery.mkdir()
            phase(cycle,'Home_to_Squid');invoke(approach,delivery)
            phase(cycle,'Squid_release_and_empty_Home');invoke(release,delivery)
            retrieval=folder/'squid_pickup';retrieval.mkdir()
            phase(cycle,'Squid_pickup_and_loaded_Home');invoke(pickup,retrieval)
            final=checks.ready();near(final['robot']['pose_mm'],hp['routes']['forward'][0],.05)
            record['completed_cycles'].append(cycle);record['final_state']=final
            phase(cycle,'completed')
        record['status']='completed_pending_operator_assessment'
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        try:record['stop_response']=api('program',dict(action='stop'))
        except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        record['finished_at']=time.time();write(out/'run.json',record)
        print(json.dumps(dict(status=record['status'],completed_cycles=record['completed_cycles'],report=str(out/'run.json'))),flush=True)

if __name__=='__main__':main()
