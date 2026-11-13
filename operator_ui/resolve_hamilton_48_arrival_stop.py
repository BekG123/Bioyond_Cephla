"""Resolve the reviewed parked camera-arrival stop after manual plate reseating.

Read-only hardware checks; optional archive writes. Never sends a motion command.
"""
import argparse
import asyncio
import json
from pathlib import Path
from hamilton_dcg_transfer import HamiltonPrep,rest_ready
from inspect_hamilton_48_repeat import snapshot
from hamilton_48_dcg_pipeline import fresh_source_check
from hamilton_48_dcg_repeat import accepted_reference,leg_plan,measured_pickup_plan

PRIOR='dcg48_repeat_1c7b6422467246f3a4adb8393b923e28'
def validate_stopped(prior,current):
    if prior.get('request_id')!=PRIOR or prior.get('status')!='failed_or_uncertain' or prior.get('stage')!='camera_arrival':
        raise RuntimeError('Only the reviewed parked camera stop can be resolved')
    if not current['PrepIsParked']['value'] or current['PrepGetPlateHeld']['value'] or current['PrepGetTipDefinitionHeld']['value'].get('is_tool'):
        raise RuntimeError('Instrument must be parked with empty channels')
    cp=prior['checkpoint']
    if cp['plate_held'] or cp['tool']['value'].get('is_tool'):raise RuntimeError('Prior release did not complete')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--archive-confirmed-reseating',action='store_true')
    parser.add_argument('--temporal-camera',action='store_true')
    args=parser.parse_args();h=HamiltonPrep();s=rest_ready(h,initial=True)
    marker=h.folder/'active.json';prior=json.loads(marker.read_text());current=asyncio.run(snapshot())
    validate_stopped(prior,current)
    if not s.get('parked'):raise RuntimeError('REST park disagrees')
    base=accepted_reference(Path(__file__).resolve().parent/'reports/hamilton_api/plate_offset_20261108T112943Z/staged_transfer_plan.json')
    if args.temporal_camera:base['temporal_camera_frames']=5
    measured=fresh_source_check(h,leg_plan(base,3),measurement_only=True)
    plan=measured_pickup_plan(base,3,measured)
    print(json.dumps(dict(current_site3=plan['source_top_mm'],site4_empty=True,parked=True,motion_sent=False)),flush=True)
    if not args.archive_confirmed_reseating:return
    lock=h.folder/'dcg48_execution.lock'
    with lock.open('x',encoding='utf-8') as f:f.write(PRIOR)
    try:
        if json.loads(marker.read_text())!=prior:raise RuntimeError('Owner changed')
        result=dict(original=prior,resolution='User reseated plate at site3; parked/empty and site3 occupied/site4 empty verified',
            measurement=measured,current=current,round_trips_completed=0,motion_sent=False)
        with (h.folder/(PRIOR+'_resolved_after_manual_reseating.json')).open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
        marker.unlink();print('ARCHIVED PARKED CAMERA STOP; FAILED RUN RETAINED',flush=True)
    finally:lock.unlink()

if __name__=='__main__':main()
