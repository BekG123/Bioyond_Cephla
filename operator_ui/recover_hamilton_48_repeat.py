"""Reviewed empty-tool recovery for the failed site-4 repeat release only."""
import argparse
import asyncio
import json
from uuid import uuid4
from hamilton_dcg_transfer import HamiltonPrep,rest_ready
from inspect_hamilton_48_repeat import snapshot
from recover_empty_dcg_home import recover

PRIOR='dcg48_repeat_b4430697b16941128c1192bc2b481add'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-empty-clear-confirmed',action='store_true')
    args=parser.parse_args();h=HamiltonPrep();rest_ready(h)
    marker=h.folder/'active.json';prior=json.loads(marker.read_text())
    if prior.get('request_id')!=PRIOR or prior.get('status')!='failed_or_uncertain':
        raise RuntimeError('Only the reviewed failed repeat can be recovered')
    before=asyncio.run(snapshot())
    if before['PrepGetPlateHeld']['value'] or before['PrepGetTipDefinitionHeld']['value'].get('label')!='DCG':
        raise RuntimeError('Expected confirmed empty DCG; do not clear a held-plate state automatically')
    ticket=dict(request_id='dcg48_recovery_'+uuid4().hex,action='empty_dcg_return',prior_request_id=PRIOR,
        operator_confirmation='Plate moved to site 3; jaws empty/free; straight-up clear; door closed; hands clear; E-stop supervised')
    h.journal(ticket,'before',before)
    try:
        asyncio.run(recover(h,ticket,args.execute_empty_clear_confirmed))
        if not args.execute_empty_clear_confirmed:return
        state=rest_ready(h,initial=True);after=asyncio.run(snapshot())
        if not state.get('parked') or not after['PrepIsParked']['value'] or after['PrepGetTipDefinitionHeld']['value'].get('is_tool') or after['PrepGetPlateHeld']['value']:
            raise RuntimeError('Empty tool return/park not verified')
        result=dict(original=prior,recovery=ticket,after=after,recovery_completed=True,rounds_completed=0)
        (h.folder/(PRIOR+'_resolved_by_empty_recovery.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
        h.journal(ticket,'outcome',result)
        if json.loads(marker.read_text()).get('request_id')!=PRIOR:raise RuntimeError('Ownership changed')
        marker.unlink();print('VERIFIED EMPTY RECOVERY: tool returned; Hamilton parked; prior failed run retained',flush=True)
    except BaseException as error:
        h.journal(ticket,'outcome',dict(status='failed_or_uncertain',error=str(error)));raise

if __name__=='__main__':main()
