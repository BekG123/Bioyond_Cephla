"""One 5 mm lift at speed5 after the operator-inspected 3.9 mm regrip."""
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from proof_lift_plate import api,near,write
from projected_pickup import ROOT,load,sha
from autonomy import check_path

GRIP=ROOT/'operator_ui/reports/projected_alignment/regrip_3p9_reseated_20261027.json'
RECEIPT=ROOT/'operator_ui/reports/projected_alignment/proof_lift_3p9_5mm_20261027.json'


def ready(state):
    r=state['robot']
    if (not r.get('connected') or not r.get('ok') or r.get('errors') or not r.get('enabled')
            or r.get('control_mode',{}).get('mode')!='auto'
            or r.get('program_state',{}).get('state')!='running'
            or state['sequence']['active'] or not state['envelope']['enabled']):
        raise RuntimeError('Healthy idle already-running Auto and workspace required; no startup/reset.')
    if not 3.85<=r['external_axes']['E1']<=3.95:
        raise RuntimeError('Claw changed from the inspected 3.9 mm setting.')


def main():
    global GRIP,RECEIPT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operator-confirmed',action='store_true')
    parser.add_argument('--accepted-repeat',type=int,choices=[1,2,3])
    parser.add_argument('--accepted-trial',choices=['squid_retry_20261027T1136','squid_nearby_20261027T1200','squid_reteach_e2_20261027','squid_clearance_20261027','squid_clearance_retry_20261027','squid_obstruction_removed_20261027','squid_full7_20261027']);args=parser.parse_args()
    if args.accepted_repeat and args.accepted_trial:raise RuntimeError('Select one trial receipt.')
    if not args.operator_confirmed:raise RuntimeError('Explicit confirmation required.')
    if args.accepted_repeat:
        GRIP=ROOT/f'operator_ui/reports/projected_alignment/repeat_{args.accepted_repeat}_grip_3p9_20261027.json'
        RECEIPT=ROOT/f'operator_ui/reports/projected_alignment/repeat_{args.accepted_repeat}_proof_lift_20261027.json'
    if args.accepted_trial:
        GRIP=ROOT/f'operator_ui/reports/projected_alignment/{args.accepted_trial}_grip.json'
        RECEIPT=ROOT/f'operator_ui/reports/projected_alignment/{args.accepted_trial}_lift.json'
    if RECEIPT.exists():raise RuntimeError('Proof lift already attempted; no replay.')
    profile,digest=load();grip=json.loads(GRIP.read_bytes())
    if args.accepted_trial:
        from projected_pickup import accepted_grip
        if not accepted_grip(profile) or grip.get('trial')!=args.accepted_trial:
            raise RuntimeError('Accepted profile and matching fresh trial grip required.')
        if time.time()-grip['finished_at']>600:raise RuntimeError('Grip receipt expired.')
    if (grip['status']!='closed_awaiting_operator_inspection' or grip['target_e1_mm']!=3.9
            or grip['profile_sha256']!=digest):raise RuntimeError('Inspected regrip reference changed.')
    if profile['descent_status']!='operator_accepted_open_claw_descent':raise RuntimeError('Accepted descent required.')
    state=api('state');ready(state);start=state['robot']['pose_mm']
    near(start,grip['after']['robot']['pose_mm'],.05)
    if api('researcher/api/status')['hand_guiding']['state']!='off':raise RuntimeError('Hand-guiding must be off.')
    target={k:start[k] for k in ('X','Y','Z','Rz')};target['Z']+=5.
    env={k:(state['envelope'][k]['min'],state['envelope'][k]['max']) for k in ('X','Y','Z')}
    check_path(start,target,state['robot']['joints'],api('robot_params'),env)
    command=dict(x=target['X'],y=target['Y'],z=target['Z'],rz=target['Rz'],speed=5,interpolation='linear')
    record=dict(at=time.time(),status='attempt_started',
        operator_confirmation='Both jaws contacting evenly, plate flat; requested 5 mm slow proof lift before Home. E-stop supervised.',
        grip_record=GRIP.relative_to(ROOT).as_posix(),grip_sha256=sha(GRIP.read_bytes()),
        profile_sha256=digest,start=start,target=target,command=command,
        claw_setting_unchanged_mm=3.9,grasp_verified=False,automatic_home=False,samples=[state])
    if args.accepted_repeat:
        record.update(repeat_number=args.accepted_repeat,
            operator_confirmation='Three full repeats authorized; adjusted jaw placement inspected and accepted. Continue requested.',
            visual_retention_confirmation_pending=True)
    if args.accepted_trial:
        record.update(trial=args.accepted_trial,
            operator_confirmation='Retry requested full calibration and Squid trial using the previously successful grip/lift; setup and clearance confirmed.',
            visual_retention_confirmation_pending=True)
    write(RECEIPT,record)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(api,'move',command)
            while not future.done():
                state=api('state');record['samples'].append(state)
                try:ready(state)
                except Exception:
                    record['stop_response']=api('program',{'action':'stop'});raise
                time.sleep(.2)
            response=future.result();record['response']=response
        if not response.get('ok') or response.get('recovered'):raise RuntimeError('Lift completion uncertain; no retry.')
        state=api('state');ready(state);near(state['robot']['pose_mm'],target,.1)
        record.update(status='lift_completed_awaiting_visual_inspection',final_state=state)
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        if 'stop_response' not in record:
            try:record['stop_response']=api('program',{'action':'stop'})
            except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        record['finished_at']=time.time();write(RECEIPT,record)
    print(json.dumps(dict(record=str(RECEIPT),status=record['status'],pose=state['robot']['pose_mm'],e1=state['robot']['external_axes']['E1'])))


if __name__=='__main__':main()
