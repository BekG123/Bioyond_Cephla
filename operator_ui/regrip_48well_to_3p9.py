"""One supervised regrip: reuse staged commands, stop at previously settled 3.9.

No arm travel, startup, force-limit changes, retry, or commands below 3.9 mm.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import time
import projected_pickup as p
from proof_lift_plate import api, near, write
from pick_and_hold.Grip.fast_position_plan import plan_closure

RECORD=p.ROOT/'operator_ui/reports/projected_alignment/regrip_3p9_reseated_20261027.json'


def checked(pose):
    state=api('state');r=state['robot']
    if (not r.get('connected') or not r.get('ok') or r.get('errors') or not r.get('enabled')
            or r['control_mode']['mode']!='auto' or r['program_state']['state']!='running'
            or state['sequence']['active']):
        raise RuntimeError('Healthy idle already-running Auto required; no recovery.')
    near(r['pose_mm'],pose,.1)
    return state


def researcher_grip(record,pose):
    status=api('researcher/api/status')['grip']
    if not status.get('can_start') or status.get('target_e1_mm')!=3.9:
        raise RuntimeError('Researcher Grip must be ready with the accepted 3.9 target.')
    record.update(method='existing_researcher_reference_grip',descent_id=status['descent_id'])
    write(RECORD,record)
    response=api('seq/grip',dict(ready=True,descent_id=status['descent_id']))
    record['start_response']=response;write(RECORD,record)
    if not response.get('ok'):raise RuntimeError(str(response))
    deadline=time.monotonic()+150
    while True:
        seq=api('seq')
        if seq['name']!='position_grip':raise RuntimeError('Grip sequence owner changed.')
        if not seq['active']:break
        if time.monotonic()>deadline:
            api('seq/stop',{});raise RuntimeError('Grip timed out; no retry.')
        time.sleep(.5)
    result=seq.get('result') or {};record['sequence']=seq
    if not result.get('ok') or result.get('target_e1_mm')!=3.9:
        record.update(status='stopped_or_failed',error=result.get('error','Unexpected Grip result'))
        write(RECORD,record);raise RuntimeError(record['error'])
    state=checked(pose)
    if abs(state['robot']['external_axes']['E1']-3.9)>.05:raise RuntimeError('Grip endpoint mismatch.')
    source=__import__('pathlib').Path(result['record']).resolve()
    if p.ROOT not in source.parents:raise RuntimeError('Unexpected Grip record location.')
    original=json.loads(source.read_bytes())
    record.update(status='closed_awaiting_operator_inspection',after=state,
        steps=original['steps'],source_grip_record=str(source),source_grip_sha256=p.sha(source.read_bytes()),
        finished_at=time.time())
    write(RECORD,record)
    print(json.dumps(dict(record=str(RECORD),status=record['status'],e1=state['robot']['external_axes']['E1'])))


def main():
    global RECORD
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operator-confirmed',action='store_true')
    parser.add_argument('--use-researcher-grip',action='store_true')
    parser.add_argument('--accepted-repeat',type=int,choices=[1,2,3])
    parser.add_argument('--accepted-trial',choices=['squid_retry_20261027T1136','squid_nearby_20261027T1200','squid_reteach_e2_20261027','squid_clearance_20261027','squid_clearance_retry_20261027','squid_obstruction_removed_20261027','squid_full7_20261027']);args=parser.parse_args()
    if args.accepted_repeat and args.accepted_trial:raise RuntimeError('Select one trial receipt.')
    if not args.operator_confirmed:raise RuntimeError('Supervised operator confirmation required.')
    if args.accepted_repeat:
        RECORD=p.ROOT/f'operator_ui/reports/projected_alignment/repeat_{args.accepted_repeat}_grip_3p9_20261027.json'
    if args.accepted_trial:
        RECORD=p.ROOT/f'operator_ui/reports/projected_alignment/{args.accepted_trial}_grip.json'
    if RECORD.exists():raise RuntimeError('Trial already attempted; no replay.')
    profile,digest=p.load()
    if profile['descent_status']!='operator_accepted_open_claw_descent':raise RuntimeError('Accept descent first.')
    pose=dict(X=311.782,Y=-76.212,Z=73.712,Rz=89.662)
    if args.accepted_repeat:
        if not p.accepted_grip(profile):raise RuntimeError('Accepted 48-well grip binding required.')
        batch=json.loads((p.ROOT/'operator_ui/reports/projected_alignment/three_repeat_batch_20261027.json').read_bytes())
        if batch['requested_repetitions']!=3:raise RuntimeError('Three-repeat authorization changed.')
        pose=profile['candidate_endpoint']
    if args.accepted_trial:
        if not p.accepted_grip(profile):raise RuntimeError('Accepted 48-well grip binding required.')
        selection_name=('squid_full7_20261027_reference.json' if args.accepted_trial=='squid_full7_20261027'
                        else 'squid_retry_reference_20261027T1136.json')
        selection=json.loads((p.ROOT/'operator_ui/reports/projected_alignment'/selection_name).read_bytes())
        if not selection['applied'] or selection['source_sha256']!=digest:
            raise RuntimeError('Selected accepted trial reference changed.')
        pose=profile['candidate_endpoint']
    near(pose,profile['candidate_endpoint'],.1)
    state=checked(pose)
    if not 27.98<=state['robot']['external_axes']['E1']<=28.05:raise RuntimeError('Expected fully open jaws.')
    if api('researcher/api/status')['hand_guiding']['state']!='off':raise RuntimeError('Hand-guiding must be off.')
    prior_path=p.ROOT/'operator_ui/demonstrations/reference_grip/2228f22a6a0a46ccb75f8bab9095d183.json'
    prior=json.loads(prior_path.read_bytes())
    accepted=[x for x in prior['steps'] if x['command']['target_e1_mm']==3.9 and abs(x.get('settled_e1_mm',0)-3.9)<=.02]
    if len(accepted)!=1:raise RuntimeError('Previous settled 3.9 mm evidence missing.')
    steps=[s for s in plan_closure(28)['commands'] if s['target_e1_mm']>=3.9]
    if steps[-1]['target_e1_mm']!=3.9:raise RuntimeError('Unexpected staged plan.')
    record=dict(at=time.time(),operator_confirmation='Plate replaced flat and centered, hands clear, E-stop supervised; staged regrip before lift.',
        reason='Stop at last successfully settled 3.9 mm; do not repeat the failed 3.8 mm step.',
        previous_grip=str(prior_path),previous_grip_sha256=p.sha(prior_path.read_bytes()),
        profile_sha256=digest,pose=pose,before=state,target_e1_mm=3.9,speed=5,
        planned_commands=steps,steps=[],samples=[],grasp_verified=False,lift_started=False,
        status='prepared',force_limits_changed=False)
    if args.accepted_repeat:
        record.update(repeat_number=args.accepted_repeat,
            operator_confirmation='Three full repeats authorized; adjusted open-claw placement visually accepted, continue.',
            reason='Reuse the accepted 48-well 3.9 mm grip at the inspected adjusted placement.')
    if args.accepted_trial:
        record.update(trial=args.accepted_trial,
            operator_confirmation='Retry of requested full calibration and Squid trial; prior setup/clearance confirmation retained.',
            reason='Reuse exact successful repeat-1 endpoint within unchanged camera-placement gates.',
            current_trial_visual_retention_confirmation_pending=True)
        if args.accepted_trial=='squid_full7_20261027':
            record.update(operator_confirmation='yes, continue with gripping',
                reason='Reuse accepted 3.9 mm grip at the newly inspected camera-adjusted endpoint; stop before lift.')
    write(RECORD,record);sent=False
    if args.use_researcher_grip:
        if not (args.accepted_repeat or args.accepted_trial):raise RuntimeError('Accepted Researcher trial required.')
        researcher_grip(record,pose)
        return
    try:
        previous=28.
        for step in steps:
            s=checked(pose)
            if abs(s['robot']['external_axes']['E1']-previous)>.05:raise RuntimeError('Opening changed between commands.')
            item=dict(command=step,at=time.time());record['steps'].append(item);record['status']='closing';write(RECORD,record)
            sent=True
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(api,'gripper',dict(action='move',e1=step['target_e1_mm'],speed=5))
                while not future.done():
                    try:s=checked(pose)
                    except Exception:
                        record['stop_response']=api('program',dict(action='stop'));raise
                    record['samples'].append(s);time.sleep(.15)
                response=future.result()
            item['response']=response;write(RECORD,record)
            if not response.get('ok') or response.get('recovered') or response.get('gripper_warning'):
                raise RuntimeError('Uncertain closing step; no retry.')
            deadline=time.monotonic()+2;stable=0
            while stable<3:
                s=checked(pose);actual=s['robot']['external_axes']['E1'];record['samples'].append(s)
                if time.monotonic()>deadline:raise RuntimeError('Closing step did not settle; no further closure.')
                stable=stable+1 if abs(actual-step['target_e1_mm'])<=.02 else 0
                if stable<3:time.sleep(.1)
            report=api('gripper',dict(action='torque'));item.update(settled_e1_mm=actual,stationary_report=report)
            write(RECORD,record)
            if (not report.get('ok') or not report.get('telemetry_live') or report.get('recovered')
                    or abs(report['e1_position']-step['target_e1_mm'])>.05
                    or not math.isfinite(report['e1_torque'])):
                raise RuntimeError('Fresh feedback not verified.')
            checked(pose);previous=actual
            print(json.dumps(dict(step=len(record['steps']),e1=actual)),flush=True)
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            s=checked(pose)
            if abs(s['robot']['external_axes']['E1']-3.9)>.05:raise RuntimeError('Claw changed after closing.')
            record['samples'].append(s);time.sleep(.1)
        record.update(status='closed_awaiting_operator_inspection',after=s)
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        if sent and 'stop_response' not in record:
            record['stop_response']=api('program',dict(action='stop'))
        raise
    finally:
        record['finished_at']=time.time();write(RECORD,record)
    print(json.dumps(dict(record=str(RECORD),status=record['status'],e1=s['robot']['external_axes']['E1'],pose=s['robot']['pose_mm'])))


if __name__=='__main__':main()
