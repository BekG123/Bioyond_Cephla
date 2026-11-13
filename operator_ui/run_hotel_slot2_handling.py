"""Slot2 handling using the taught endpoint and slot1 pattern.

--execute confirms unchanged rack, plate supported at slot2 for release_return
or seated in slot2 with empty HOME/jaws for retrieve, horizontal opening/retreat
and 5mm lift clear, hands clear and E-stop supervised. No startup/reset/retry.
release-retrieve starts held at slot2, releases, returns HOME, then retrieves.
"""
import argparse
import json
import time
from uuid import uuid4
from hotel_slot2_handling import geometry,OUTPUT
from run_cellvis24_scanner_hamilton import api,reconnect,dispatch
from run_record_io import write_run_record


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action',choices=['release_return','retrieve','release-retrieve'],default='release-retrieve')
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args(argv)
    g=geometry()
    actions=['release_return','retrieve'] if args.action=='release-retrieve' else [args.action]
    if not args.execute:
        print(json.dumps(dict(motion_started=False,actions=actions,geometry=g),indent=2));return
    OUTPUT.mkdir(parents=True,exist_ok=True)
    path=OUTPUT/('workflow_'+uuid4().hex+'.json')
    record=dict(at=time.time(),status='starting',actions=actions,steps=[],automatic_retries=False)
    def save():write_run_record(path,record)
    save()
    try:
        for action in actions:
            reconnect()
            plan=api('developer/api/hotel-slot2-handling/preview',dict(action=action))['plan']
            if plan['geometry']!=g:raise RuntimeError('Backend geometry changed.')
            result=dispatch('developer/api/hotel-slot2-handling/start',dict(plan=plan,
                plate_setup_confirmed=True,route_and_lift_clear=True,estop_supervised=True),'hotel_slot2_handling',240)
            record['steps'].append(dict(action=action,result=result));save()
        record['status']='completed_operator_observation_pending'
    except BaseException as exc:
        record.update(status='stopped_or_uncertain',error=str(exc));raise
    finally:
        record['finished_at']=time.time();save()
        print(json.dumps(dict(status=record['status'],record=str(path))),flush=True)
    return dict(record=record,record_path=str(path))


if __name__=='__main__':main()
