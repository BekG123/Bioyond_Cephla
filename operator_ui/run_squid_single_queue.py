"""Preview or execute one accepted Squid direction; no restart or grip command."""
import argparse
import json
import sys
from copy import deepcopy
from datetime import datetime,timezone
from uuid import uuid4
from capture_squid_approach_20261103 import FOLDER,sha,save
from squid_handling_route import CURRENT_SOURCE,CURRENT_SHA,load_route
from proof_lift_plate import api
import execute_continuous_squid_return_20261103 as travel

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--direction',choices=('forward','reverse'),required=True)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    plan=deepcopy(load_route(CURRENT_SOURCE,CURRENT_SHA))
    route=plan['routes']['from_capture']
    forward=args.direction=='forward'
    plan.update(routes={'from_capture':route[:5] if forward else route[4:]},
        leg_speeds=[137,137,137,5] if forward else [5,137,137,137],
        completion_status='single_queue_'+args.direction+'_completed_pending_operator_assessment',
        operator_intent='Explicitly requested one-queue Squid travel, current clearance and payload established by operator; no release or automatic retry.')
    state=api('state')
    if not state['robot'].get('connected'):raise RuntimeError('Connect through existing Flask owner first')
    if api('researcher/api/status')['hand_guiding']['state']!='off':raise RuntimeError('End hand-guiding first')
    if api('researcher/api/lacry/state')['running']['active']:raise RuntimeError('Another workflow is active')
    # Preview first; missing 220109 cannot dispatch or create a trial directory.
    from squid_queue_client import preview
    preview(plan['routes']['from_capture'],plan['leg_speeds'])
    if not args.execute:
        print(json.dumps(dict(validated=True,direction=args.direction,speeds=plan['leg_speeds'],motion_sent=False)));return
    folder=FOLDER/('single_queue_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:8]);folder.mkdir()
    travel.PLAN=folder/'plan.json';save(travel.PLAN,plan);travel.SHA=sha(travel.PLAN);travel.OUTPUT=folder/'trial.json'
    old=sys.argv[:]
    try:
        sys.argv=[__file__,'--execute']
        travel.main(tuple(plan['leg_speeds']),(0,3),single_queue=True)
    finally:sys.argv=old

if __name__=='__main__':main()
