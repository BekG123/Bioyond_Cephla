"""Fresh authorized accepted pickup and overhead-only Squid transfer."""
import argparse
import json
import sys
from datetime import datetime, timezone
import full_calibration_handling_20261103 as workflow
import test_squid_destination_empty as transfer
from proof_lift_plate import api, near, write
from prepare_squid_destination import validate

AUTH = ('Operator confirmed: empty gripper, plate flat in calibration holder, arm released, '
        'pickup/Home/Squid route and hands clear, E-stop supervised; calibrate, pick up, '
        'and stop above Squid with plate retained. No release or holder descent.')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    source=workflow.FOLDER/'destination_final_z266p81_20261103.json'
    digest='ac004fd846bf2333a29f29374b7091b7c042cb6cf31d53ca09c45432412a84b8'
    if workflow.sha(source)!=digest:raise RuntimeError('Pinned Squid destination changed')
    candidate=json.loads(source.read_bytes())
    state=api('state');r=state['robot']
    near(r['pose_mm'],candidate['routes']['forward'][0],.05)
    if not r.get('ok') or r.get('errors') or state['sequence']['active']:
        raise RuntimeError('Healthy idle Home required')
    if abs(r['external_axes']['E1'])>.2:raise RuntimeError('Expected confirmed empty closed gripper')
    if api('robot_params')!=candidate['cfg']:raise RuntimeError('Robot parameters changed')
    env={k:[state['envelope'][k]['min'],state['envelope'][k]['max']] for k in ('X','Y','Z')}
    if not state['envelope']['enabled'] or env!=candidate['envelope']:raise RuntimeError('Workspace changed')
    validate(candidate['routes']['forward'][:-1],r['joints'],candidate['cfg'],env)
    out=workflow.FOLDER/('calibration_overhead_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    workflow.OUT=out;workflow.AUTH=AUTH
    print(json.dumps(dict(authorization=AUTH,overhead=candidate['routes']['forward'][-2],output=str(out),execute=args.execute)),flush=True)
    workflow.invoke(workflow,['--execute'] if args.execute else [],False,True)
    if not args.execute:return
    result=json.loads((out/'run.json').read_bytes())
    if result['status']!='full_calibration_loaded_home_completed_pending_operator_assessment':
        raise RuntimeError('Pickup and loaded Home not completed')
    transfer.SOURCE=source;transfer.SHA=digest
    flags=['--loaded-forward-only','--approach-only','--transit-speed','137']
    workflow.invoke(transfer,flags)
    before=set(workflow.FOLDER.glob('loaded_trial_*.json'))
    workflow.invoke(transfer,[*flags,'--execute'])
    created=set(workflow.FOLDER.glob('loaded_trial_*.json'))-before
    if len(created)!=1:raise RuntimeError('Fresh transfer receipt ambiguous')
    receipt=created.pop();trial=json.loads(receipt.read_bytes())
    if trial['status']!='loaded_above_squid_awaiting_operator_teaching':raise RuntimeError('Overhead arrival unverified')
    write(out/'overhead_completion.json',dict(status='completed_pending_operator_retention_assessment',
        authorization=AUTH,transfer_receipt=str(receipt),transfer_sha256=workflow.sha(receipt),
        final_state=api('state'),new_visual_observation_claimed=False))
    print(json.dumps(dict(status='stopped_above_squid_claws_unchanged',report=str(out))),flush=True)

if __name__=='__main__':main()
