"""One-shot empty DCG recovery after the reviewed high-clearance check stop."""
import argparse
import asyncio
import json
from uuid import uuid4
from hamilton_dcg_transfer import HamiltonPrep,rest_ready
from inspect_hamilton_48_repeat import snapshot
from recover_empty_dcg_home import recover

PRIOR='dcg48_repeat_d08221dc9a8d40a1bcb874cd3929555d'

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute-empty-clear-confirmed',action='store_true')
    args=p.parse_args();h=HamiltonPrep();rest_ready(h)
    marker=h.folder/'active.json';prior=json.loads(marker.read_text())
    if prior.get('request_id')!=PRIOR or prior.get('status')!='failed_or_uncertain':raise RuntimeError('Wrong stopped run')
    s=asyncio.run(snapshot())
    if s['PrepGetTipDefinitionHeld']['value'].get('label')!='DCG':raise RuntimeError('Expected DCG')
    expected={1:(54.04150772,112.9622345,165.0000763),2:(54.04150772,79.5377426,165.0003052)}
    rows=s['PrepGetPositions']['positions']
    if len(rows)!=2 or {v['channel'] for v in rows}!={1,2}:raise RuntimeError('Unexpected channels')
    for row in rows:
        if any(not abs(row[k]-v)<=.1 for k,v in zip(('position_x','position_y','position_z'),expected[row['channel']])):
            raise RuntimeError('Stopped clearance position changed')
    if not args.execute_empty_clear_confirmed:print('READ-ONLY EMPTY CLEARANCE RECOVERY CHECK PASSED');return
    ticket=dict(request_id='dcg48_high_recovery_'+uuid4().hex,prior_request_id=PRIOR,
        operator_confirmation='Plate flat at site4; gripper empty and clear; then user moved plate to site3 and requested retry')
    lock=h.folder/'dcg48_execution.lock'
    with lock.open('x',encoding='utf-8') as f:f.write(ticket['request_id'])
    try:
        with (h.folder/PRIOR/'empty_recovery_attempt.json').open('x',encoding='utf-8') as f:json.dump(ticket,f)
        h.journal(ticket,'before',s)
        asyncio.run(recover(h,ticket,True))
        after=asyncio.run(snapshot());state=rest_ready(h,initial=True)
        if not state.get('parked') or not after['PrepIsParked']['value'] or after['PrepGetPlateHeld']['value'] or after['PrepGetTipDefinitionHeld']['value'].get('is_tool'):
            raise RuntimeError('Park/empty verification failed')
        result=dict(original=prior,recovery=ticket,after=after,recovery_completed=True,round_trips_completed=0)
        (h.folder/(PRIOR+'_resolved_by_empty_recovery.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
        if json.loads(marker.read_text()).get('request_id')!=PRIOR:raise RuntimeError('Ownership changed')
        marker.unlink();print('VERIFIED EMPTY DCG RETURNED AND HAMILTON PARKED',flush=True)
    except BaseException as error:h.journal(ticket,'failed_or_uncertain',str(error));raise
    finally:lock.unlink()

if __name__=='__main__':main()
