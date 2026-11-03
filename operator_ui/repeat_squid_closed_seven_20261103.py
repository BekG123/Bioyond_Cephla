"""Seven sequential authorized closed-claw cycles; stop on first failure."""
import argparse
import json
import time
import roundtrip_squid_closed_20261103 as cycle
from proof_lift_plate import api, near, write
from capture_squid_approach_20261103 import FOLDER, sha

BATCH=FOLDER/'closed_claw_seven_20261103'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    prior=json.loads(cycle.OUTPUT.read_bytes())
    if prior['status']!='closed_claw_roundtrip_completed_pending_operator_assessment' or prior['release_executed']:
        raise RuntimeError('Successful prior round trip required')
    plan=json.loads(cycle.PLAN.read_bytes());plan_hash=sha(cycle.PLAN)
    if prior['plan_sha256']!=plan_hash:raise RuntimeError('Accepted plan changed')
    state=api('state');r=state['robot']
    def ready(s,baseline):
        robot=s['robot']
        if not robot.get('connected') or not robot.get('ok') or robot.get('errors') or not robot.get('enabled') or robot['control_mode']['mode']!='auto' or robot['program_state']['state']!='running' or s['sequence']['active']:
            raise RuntimeError('Healthy idle Auto/Running required; no recovery')
        near(robot['pose_mm'],plan['routes']['from_capture'][0],.1)
        if abs(robot['external_axes']['E1']-baseline)>.1:raise RuntimeError('Grip changed from batch baseline')
        if sha(cycle.PLAN)!=plan_hash:raise RuntimeError('Plan changed during batch')
    if not r.get('connected'):raise RuntimeError('Connect status first')
    baseline=r['external_axes']['E1'];ready(state,baseline)
    if BATCH.exists():raise RuntimeError('Batch already attempted; no replay')
    if not args.execute:
        print(json.dumps(dict(cycles=7,plan_sha256=plan_hash,speeds=plan['leg_speeds'],preserved_e1=baseline)));return
    BATCH.mkdir()
    record=dict(status='running',at=time.time(),requested_cycles=7,completed_cycles=0,
        plan=str(cycle.PLAN),plan_sha256=plan_hash,prior_trial=str(cycle.OUTPUT),prior_trial_sha256=sha(cycle.OUTPUT),
        prior_operator_assessment='This worked successfully; run seven times for repeatability.',
        authorization='Seven closed-claw Home/Squid/Home cycles, stop on first failure; no automatic retry.',
        baseline_e1_mm=baseline,cycles=[],gripper_commands=[],release_executed=False)
    output=BATCH/'batch.json';write(output,record)
    try:
        for number in range(1,8):
            ready(api('state'),baseline)
            receipt=BATCH/f'cycle_{number:02d}.json';cycle.OUTPUT=receipt
            record['current_cycle']=number;write(output,record)
            print(json.dumps(dict(cycle=number,status='starting')),flush=True)
            cycle.main()
            result=json.loads(receipt.read_bytes())
            if result['status']!='closed_claw_roundtrip_completed_pending_operator_assessment' or len(result['steps'])!=8 or result['release_executed']:
                raise RuntimeError('Cycle completion unverified')
            ready(api('state'),baseline)
            record['cycles'].append(dict(cycle=number,receipt=str(receipt),sha256=sha(receipt),
                elapsed_s=result['finished_at']-result['at'],final_pose=result['final_state']['robot']['pose_mm']))
            record['completed_cycles']=number;write(output,record)
            print(json.dumps(dict(cycle=number,status='completed',completed_cycles=number)),flush=True)
        record.update(status='seven_cycles_completed_pending_operator_assessment',final_state=api('state'))
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        try:record['stop_response']=api('program',dict(action='stop'))
        except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        record['finished_at']=time.time();write(output,record)
        print(json.dumps(dict(batch=str(output),status=record['status'],completed_cycles=record['completed_cycles'])),flush=True)


if __name__=='__main__':main()
