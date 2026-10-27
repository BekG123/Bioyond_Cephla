"""Dispatch the explicitly reviewed Home return or nearby Squid trial once.

Invoke through monitor_e2_trial.py. No startup, reset, release, or retries.
"""
import argparse
import json
import time
from proof_lift_plate import api
from projected_pickup import ROOT

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['home','squid'])
    parser.add_argument('--receipt',choices=['initial','reteach_start','reteach_loaded','reteach_squid','clearance_start','clearance_loaded','clearance_squid','clearance_retry_start','clearance_retry_prepared_home','clearance_retry_loaded','obstruction_removed_start','obstruction_removed_loaded','obstruction_removed_squid','full7_start','full7_loaded'],default='initial')
    parser.add_argument('--plan-id')
    args=parser.parse_args()
    if args.receipt!='initial' and args.phase=='home' and not args.plan_id:
        raise RuntimeError('Exact reviewed Home plan ID required.')
    output=ROOT/f'operator_ui/reports/projected_alignment/e2_reference_{args.phase}_20261027{("_"+args.receipt) if args.receipt!="initial" else ""}.json'
    record={'at':time.time(),'phase':args.phase,'authorization':'Continue same successful full calibration, then the previously authorized nearby Squid endpoint; stop before release.'}
    with output.open('x',encoding='utf-8') as stream:
        json.dump(record,stream)
    try:
        if args.phase=='home':
            result=api('researcher/api/lacry/confirm',{'ready':True,'plan_id':args.plan_id or '2026-10-27T12:14:51.373853+00:00:1793103291373'})
            expected='researcher_home'
        else:
            from squid_48well_endpoint_trial import SHA
            result=api('developer/api/squid-48well-trial/start',{'ready':True,'candidate_sha256':SHA})
            expected='squid_48well_endpoint_trial'
        record['dispatch']=result
        if not result.get('ok'):raise RuntimeError(str(result))
        deadline=time.monotonic()+120
        while True:
            state=api('state');seq=api('seq')
            if seq['name']!=expected:raise RuntimeError('Sequence owner changed')
            if not seq['active']:break
            if time.monotonic()>deadline:
                api('seq/stop',{});api('program',{'action':'stop'})
                raise RuntimeError('Completion timed out; stopped, no retry')
            time.sleep(.25)
        record.update(sequence=seq,final_state=state)
        if not (seq.get('result') or {}).get('ok'):raise RuntimeError(str(seq.get('result')))
        record['status']='motion_complete_inspection_pending'
    except Exception as exc:
        record.update(status='stopped_or_failed',error=str(exc));raise
    finally:
        output.write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps({'record':str(output),'status':record['status'],'robot':state['robot']}),flush=True)

if __name__=='__main__':main()
