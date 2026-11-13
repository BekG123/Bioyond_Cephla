"""Recover the inspected empty DCG after independent site-4 jaw opening.

Ten millimeters straight up at 1 mm/s, jaws unchanged, then tool return/park.
Never restart the failed five-round batch. Default is read-only validation.
"""
import argparse
import asyncio
import json
from uuid import uuid4
from hamilton_dcg_transfer import C,HamiltonPrep,rest_ready
from inspect_hamilton_48_repeat import snapshot
from recover_empty_dcg_home import recover
from reseat_hamilton_48_suspended import PRIOR,verify_arrival

def retreat_plan(opened,current):
    if opened.get('status')!='opened_awaiting_clearance_inspection' or not opened.get('jaws_opened'):
        raise RuntimeError('Verified independent opening is required')
    if current['PrepGetPlateHeld']['value'] or current['PrepGetTipDefinitionHeld']['value'].get('label')!='DCG':
        raise RuntimeError('Expected empty DCG; no held-state reset allowed')
    before=current['PrepGetPositions'];verify_arrival(opened['after'],before,0)
    for p in before['positions']:
        if not 17.0<=p['position_z']<=17.8:raise RuntimeError('Unexpected recovery height')
    command=C.PrepMoveZAbsolute(channels=[C.ChannelZPositionParameters(default_values=False,
        channel=p['channel'],z_position=p['position_z']+10) for p in before['positions']],velocity=1)
    command.build_parameters().build()
    return dict(before=before,command=command)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute-empty-clear-confirmed',action='store_true')
    args=p.parse_args();h=HamiltonPrep();rest_ready(h)
    marker=h.folder/'active.json';prior=json.loads(marker.read_text())
    if prior.get('request_id')!=PRIOR or prior.get('status')!='failed_or_uncertain':raise RuntimeError('Wrong recovery hold')
    opened=json.loads((h.folder/PRIOR/'open_supported_result.json').read_text())
    current=asyncio.run(snapshot());plan=retreat_plan(opened,current)
    if not args.execute_empty_clear_confirmed:
        print('READ-ONLY CHECK PASSED: empty jaws at recorded opening; 10 mm slow vertical retreat then tool return/park');return
    lock=h.folder/'dcg48_execution.lock'
    with lock.open('x',encoding='utf-8') as f:f.write(PRIOR)
    ticket=dict(request_id='dcg48_park_'+uuid4().hex,action='empty_dcg_recovery',prior_request_id=PRIOR,
        operator_confirmation='Plate flat and supported; jaws visibly clear of plate and holder; previous retreat path clear')
    try:
        with (h.folder/PRIOR/'empty_retreat_attempt.json').open('x',encoding='utf-8') as f:json.dump(ticket,f)
        h.journal(ticket,'begin',ticket)
        asyncio.run(recover(h,ticket,True,initial_retreat=plan))
        after=asyncio.run(snapshot());state=rest_ready(h,initial=True)
        if not state.get('parked') or not after['PrepIsParked']['value'] or after['PrepGetTipDefinitionHeld']['value'].get('is_tool') or after['PrepGetPlateHeld']['value']:
            raise RuntimeError('Final park/tool feedback failed')
        result=dict(original=prior,recovery_request=ticket['request_id'],recovery_completed=True,
            physical_plate_left_at_site=4,round_trips_completed=0,batch_resumed=False,after=after)
        (h.folder/(PRIOR+'_resolved_after_supported_release.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
        h.journal(ticket,'outcome',result)
        if json.loads(marker.read_text()).get('request_id')!=PRIOR:raise RuntimeError('Ownership changed')
        marker.unlink();print('VERIFIED: EMPTY DCG RETURNED; HAMILTON PARKED; BATCH NOT RESUMED',flush=True)
    except BaseException as error:
        h.journal(ticket,'outcome',dict(status='failed_or_uncertain',error=str(error)));raise
    finally:lock.unlink()

if __name__=='__main__':main()
