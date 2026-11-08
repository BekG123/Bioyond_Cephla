"""Fresh accepted Home-to-Squid transfer, retaining the currently held plate."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import sys
import execute_continuous_squid_return_20261103 as runner
from capture_squid_approach_20261103 import FOLDER, sha, save
from finish_squid_handling_20261107 import SOURCE, SHA, stage_ready
from prepare_squid_destination import validate
from proof_lift_plate import api, near

PARENT=FOLDER/'finish_handling_20261108T044707604699Z/run.json'
AUTH=('Operator confirmed plate remained level and secure during completed pickup and Home return, '
      'then requested the path to Squid again. Existing unchanged clearance and supervision apply. '
      'Forward only, claws unchanged; no release, return, imaging, reset or retry.')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if sha(SOURCE)!=SHA:raise RuntimeError('Accepted route changed')
    parent=json.loads(PARENT.read_bytes())
    if parent['status']!='handling_completed_pending_operator_assessment':
        raise RuntimeError('Previous completed handling receipt required')
    state=api('state');r=state['robot']
    if (not r.get('connected') or not r.get('ok') or r.get('errors') or not r.get('enabled')
        or r['program_state']['state']!='running' or r['control_mode']['mode']!='auto'
        or state['sequence']['active'] or api('seq')['active']):
        raise RuntimeError('Healthy idle running Auto required')
    if api('researcher/api/status')['hand_guiding']['state']!='off':
        raise RuntimeError('Hand-guiding must be off')
    near(r['pose_mm'],parent['final_state']['robot']['pose_mm'],.05)
    if abs(r['external_axes']['E1']-parent['final_state']['robot']['external_axes']['E1'])>.1:
        raise RuntimeError('Grip changed since accepted loaded Home')
    plan=deepcopy(json.loads(SOURCE.read_bytes()))
    route=plan['routes']['from_capture'][:5]
    near(r['pose_mm'],route[0],.05)
    env={k:[state['envelope'][k]['min'],state['envelope'][k]['max']] for k in ('X','Y','Z')}
    if not state['envelope']['enabled'] or env!=plan['envelope'] or api('robot_params')!=plan['cfg']:
        raise RuntimeError('Reviewed settings changed')
    checked=validate(route,r['joints'],plan['cfg'],env)
    squid=stage_ready()
    print(json.dumps(dict(validated=True,execute=args.execute,target=route[-1],preserved_e1=r['external_axes']['E1'])),flush=True)
    if not args.execute:return
    out=FOLDER/('forward_repeat_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir()
    plan.update(routes={'from_capture':route},leg_speeds=[137,137,137,5],
        completion_status='closed_claw_forward_completed_pending_operator_assessment',
        operator_intent=AUTH,parent_receipt=str(PARENT),parent_sha256=sha(PARENT),
        source_sha256=SHA,squid_loading=squid,validation=checked)
    runner.PLAN=out/'plan.json';runner.OUTPUT=out/'trial.json'
    save(runner.PLAN,plan);runner.SHA=sha(runner.PLAN)
    original=sys.argv[:]
    try:
        sys.argv=[runner.__file__]
        runner.main(expected_speeds=(137,137,137,5),vertical_legs=(0,3))
        stage_ready()
        sys.argv=[runner.__file__,'--execute']
        runner.main(expected_speeds=(137,137,137,5),vertical_legs=(0,3))
    finally:sys.argv=original

if __name__=='__main__':main()
