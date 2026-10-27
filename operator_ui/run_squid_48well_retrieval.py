"""Dispatch the authorized one-shot retrieval through the existing Flask owner."""
import argparse,json,time
from proof_lift_plate import api,ROOT,write
from squid_48well_higher_route import SHA

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stop-before-release',action='store_true')
    args=parser.parse_args()
    out=ROOT/'operator_ui/reports/projected_alignment/squid_48well_full7_cycle_20261027_dispatch.json'
    record=dict(at=time.time(),authorization='User requested full retry with higher Squid corridor and 7 mm release/approach: drop off, empty Home, retrieve and loaded Home.')
    if args.stop_before_release:
        record.update(authorization='Continue full calibration and transfer to Squid for drop-off; stop before release for support inspection.',stop_before_release=True)
    with out.open('x',encoding='utf-8') as stream:json.dump(record,stream)
    try:
        body=dict(ready=True,candidate_sha256=SHA)
        if args.stop_before_release:body['stop_before_release']=True
        record['response']=api('developer/api/squid-48well-retrieval/start',body)
        if not record['response'].get('ok'):raise RuntimeError(str(record['response']))
        deadline=time.monotonic()+180
        while True:
            seq=api('seq')
            if seq['name']!='squid_48well_retrieval':raise RuntimeError('Sequence owner changed.')
            if not seq['active']:break
            if time.monotonic()>deadline:
                api('seq/stop',{});api('program',dict(action='stop'))
                raise RuntimeError('Retrieval timed out; stopped, no retry.')
            time.sleep(.25)
        record.update(sequence=seq,final_state=api('state'))
        if not (seq.get('result') or {}).get('ok'):raise RuntimeError(str(seq.get('result')))
        record['status']='seated_endpoint_awaiting_support_inspection' if args.stop_before_release else 'completed_awaiting_retention_confirmation'
    except Exception as exc:
        record.update(status='stopped_or_failed',error=str(exc));raise
    finally:
        write(out,record)
    print(json.dumps(dict(record=str(out),status=record['status'],robot=record['final_state']['robot'])))

if __name__=='__main__':main()
