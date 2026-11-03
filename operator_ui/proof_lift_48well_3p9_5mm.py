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
GRIP_TOLERANCE_MM = .05


def ready(state):
    r=state['robot']
    if (not r.get('connected') or not r.get('ok') or r.get('errors') or not r.get('enabled')
            or r.get('control_mode',{}).get('mode')!='auto'
            or r.get('program_state',{}).get('state')!='running'
            or state['sequence']['active'] or not state['envelope']['enabled']):
        raise RuntimeError('Healthy idle already-running Auto and workspace required; no startup/reset.')
    if abs(r['external_axes']['E1']-3.9)>GRIP_TOLERANCE_MM+1e-9:
        raise RuntimeError('Claw changed from the inspected 3.9 mm setting.')


def main():
    global GRIP,RECEIPT,GRIP_TOLERANCE_MM
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operator-confirmed',action='store_true')
    parser.add_argument('--positive-y64',action='store_true')
    parser.add_argument('--positive-y84',action='store_true')
    parser.add_argument('--positive-y94',action='store_true')
    parser.add_argument('--positive-y114',action='store_true')
    parser.add_argument('--positive-y104',action='store_true')
    parser.add_argument('--positive-y124',action='store_true')
    parser.add_argument('--positive-y123',action='store_true')
    parser.add_argument('--positive-y120',action='store_true')
    parser.add_argument('--positive-y125',action='store_true')
    parser.add_argument('--positive-y127',action='store_true')
    parser.add_argument('--positive-y122',action='store_true')
    parser.add_argument('--squid-teaching-repeat',action='store_true')
    parser.add_argument('--new-squid-y114',action='store_true')
    parser.add_argument('--nov3-approach-y104',action='store_true')
    parser.add_argument('--nov3-retry-y104',action='store_true')
    parser.add_argument('--accepted-geometry-repeat',help='Fresh accepted-geometry repeat attempt.json')
    parser.add_argument('--accepted-repeat',type=int,choices=[1,2,3])
    parser.add_argument('--accepted-trial',choices=['squid_retry_20261027T1136','squid_nearby_20261027T1200','squid_reteach_e2_20261027','squid_clearance_20261027','squid_clearance_retry_20261027','squid_obstruction_removed_20261027','squid_full7_20261027']);args=parser.parse_args()
    if args.accepted_repeat and args.accepted_trial:raise RuntimeError('Select one trial receipt.')
    if sum(bool(x) for x in (args.positive_y104,args.positive_y64,args.positive_y84,args.positive_y94,args.positive_y114,args.positive_y124,args.positive_y123,args.positive_y120,args.positive_y125,args.positive_y127,args.positive_y122,args.accepted_repeat,args.accepted_trial))>1:raise RuntimeError('Select one pickup receipt')
    if not args.operator_confirmed:raise RuntimeError('Explicit confirmation required.')
    if args.accepted_repeat:
        GRIP=ROOT/f'operator_ui/reports/projected_alignment/repeat_{args.accepted_repeat}_grip_3p9_20261027.json'
        RECEIPT=ROOT/f'operator_ui/reports/projected_alignment/repeat_{args.accepted_repeat}_proof_lift_20261027.json'
    if args.accepted_trial:
        GRIP=ROOT/f'operator_ui/reports/projected_alignment/{args.accepted_trial}_grip.json'
        RECEIPT=ROOT/f'operator_ui/reports/projected_alignment/{args.accepted_trial}_lift.json'
    if args.positive_y64:
        GRIP=ROOT/'operator_ui/reports/projected_alignment/repeat_positive_y64_e58741f1aa1c4ac181711fafd324c8c2_grip.json'
        RECEIPT=GRIP.with_name(GRIP.stem+'_lift.json')
    if args.positive_y84:
        GRIP=ROOT/'operator_ui/reports/projected_alignment/positive_y84_b9bdbc5a1efa4f7186e75235a7514d8e/grip_attempt.json'
        RECEIPT=GRIP.with_name('proof_lift.json')
    if args.positive_y94:
        GRIP=ROOT/'operator_ui/reports/projected_alignment/positive_y94_95d18ef16cec44568da6e8b15ea5ba3b/grip_attempt.json'
        RECEIPT=GRIP.with_name('proof_lift.json')
        GRIP_TOLERANCE_MM=.15
    if args.positive_y114:
        GRIP=ROOT/'operator_ui/reports/projected_alignment/positive_y114_d9f8d4b4c3204e8190a89ad16a9f51db/grip_attempt.json'
        RECEIPT=GRIP.with_name('proof_lift.json')
        GRIP_TOLERANCE_MM=.15
    if args.new_squid_y114:
        if not args.positive_y114:
            raise RuntimeError('New Squid pairing requires +Y11.4')
        GRIP=ROOT/'operator_ui/reports/projected_alignment/positive_y114_3de7174fd18f4c999d11f4f11e592c24/grip_attempt.json'
        RECEIPT=GRIP.with_name('proof_lift.json')
    if args.positive_y124:
        GRIP=ROOT/'operator_ui/reports/projected_alignment/positive_y124_27612969ac91483cbc0059eadfad9677/grip_attempt.json'
        RECEIPT=GRIP.with_name('proof_lift.json')
        GRIP_TOLERANCE_MM=.15
    if args.positive_y123:
        GRIP=ROOT/'operator_ui/reports/projected_alignment/positive_y123_e35c76ed20a645ecbce9fddf73de8b6e/grip_attempt.json'
        RECEIPT=GRIP.with_name('proof_lift.json')
        GRIP_TOLERANCE_MM=.15
    if args.positive_y120:
        GRIP=ROOT/'operator_ui/reports/projected_alignment/positive_y120_63e04f1e35774dca806adf802a834c8d/grip_attempt.json'
        RECEIPT=GRIP.with_name('proof_lift.json')
        GRIP_TOLERANCE_MM=.15
    if args.positive_y125:
        GRIP=ROOT/'operator_ui/reports/projected_alignment/positive_y125_a25533839d004b898364954a2616bb52/grip_attempt.json'
        RECEIPT=GRIP.with_name('proof_lift.json')
        GRIP_TOLERANCE_MM=.15
    if args.positive_y127:
        GRIP=ROOT/'operator_ui/reports/projected_alignment/positive_y127_67d2e02fceea480ba7eb34e94792b330/grip_attempt.json'
        RECEIPT=GRIP.with_name('proof_lift.json')
        GRIP_TOLERANCE_MM=.15
    if args.positive_y122:
        GRIP=ROOT/'operator_ui/reports/projected_alignment/positive_y122_250c0133b30e4c82b97dbfbddee992b9/grip_attempt.json'
        RECEIPT=GRIP.with_name('proof_lift.json')
        GRIP_TOLERANCE_MM=.15
    if args.squid_teaching_repeat:
        if not args.positive_y122:
            raise RuntimeError('Teaching repeat requires the +Y12.2 receipt')
        GRIP=ROOT/'operator_ui/reports/projected_alignment/positive_y122_da891af038db475a84960a0896a8368b/grip_attempt.json'
        RECEIPT=GRIP.with_name('proof_lift.json')
    if args.positive_y104:
        GRIP=ROOT/'operator_ui/reports/projected_alignment/positive_y104_8f9bf274eba546ab8ec04f5dd29cf267/grip_attempt.json'
        RECEIPT=GRIP.with_name('proof_lift.json')
        GRIP_TOLERANCE_MM=.15
    if args.nov3_approach_y104:
        if not args.positive_y104:
            raise RuntimeError('Nov 3 approach requires +Y10.4')
        GRIP=ROOT/'operator_ui/reports/projected_alignment/positive_y104_b8f7c0f3458b44b19cb566a6f36ee3fd/grip_attempt.json'
        RECEIPT=GRIP.with_name('proof_lift.json')
    if args.nov3_retry_y104:
        if not args.positive_y104 or args.nov3_approach_y104:
            raise RuntimeError('Select only the Nov 3 retry +Y10.4')
        GRIP=ROOT/'operator_ui/reports/projected_alignment/positive_y104_0a6831631d984aa0bdd44540a0516785/grip_attempt.json'
        RECEIPT=GRIP.with_name('proof_lift.json')
    if args.accepted_geometry_repeat:
        from pathlib import Path
        if not args.positive_y104 or args.nov3_retry_y104 or args.nov3_approach_y104:
            raise RuntimeError('Repeat requires only +Y10.4 selection')
        repeat_path=Path(args.accepted_geometry_repeat).resolve()
        if (ROOT/'operator_ui/reports/projected_alignment') not in repeat_path.parents or repeat_path.name!='attempt.json':
            raise RuntimeError('Unexpected repeat receipt location')
        GRIP=repeat_path.with_name('grip_attempt.json');RECEIPT=repeat_path.with_name('proof_lift.json')
    if RECEIPT.exists():raise RuntimeError('Proof lift already attempted; no replay.')
    profile,digest=load();grip=json.loads(GRIP.read_bytes())
    if args.accepted_geometry_repeat:
        from repeat_accepted_y104_20261103 import verify_repeat
        verify_repeat(json.loads(repeat_path.read_bytes()),profile,digest,api('seq'))
        if grip.get('repeat_receipt_sha256')!=sha(repeat_path.read_bytes()):
            raise RuntimeError('Grip belongs to another repeat')
    if args.positive_y104 or args.positive_y64 or args.positive_y84 or args.positive_y94 or args.positive_y114 or args.positive_y124 or args.positive_y123 or args.positive_y120 or args.positive_y125 or args.positive_y127 or args.positive_y122:
        if profile.get('pickup_correction',{}).get('direction')!='positive_base_y' or not 0<=time.time()-grip['finished_at']<=600:
            raise RuntimeError('Fresh successful +Y grip required')
        if args.positive_y84 and profile['pickup_correction']['distance_mm']!=8.4:
            raise RuntimeError('Expected the inspected +Y 8.4 mm pickup')
        if args.positive_y94 and profile['pickup_correction']['distance_mm']!=9.4:
            raise RuntimeError('Expected the inspected +Y 9.4 mm pickup')
        if args.positive_y104 and profile['pickup_correction']['distance_mm']!=10.4:
            raise RuntimeError('Expected the inspected +Y 10.4 mm pickup')
        if args.positive_y114 and profile['pickup_correction']['distance_mm']!=11.4:
            raise RuntimeError('Expected the inspected +Y 11.4 mm pickup')
        if args.positive_y124 and profile['pickup_correction']['distance_mm']!=12.4:
            raise RuntimeError('Expected the inspected +Y 12.4 mm pickup')
        if args.positive_y123 and profile['pickup_correction']['distance_mm']!=12.3:
            raise RuntimeError('Expected the inspected +Y 12.3 mm pickup')
        if args.positive_y120 and profile['pickup_correction']['distance_mm']!=12.0:
            raise RuntimeError('Expected the inspected +Y 12.0 mm pickup')
        if args.positive_y125 and profile['pickup_correction']['distance_mm']!=12.5:
            raise RuntimeError('Expected the inspected +Y 12.5 mm pickup')
        if args.positive_y127 and profile['pickup_correction']['distance_mm']!=12.7:
            raise RuntimeError('Expected the inspected +Y 12.7 mm pickup')
        if args.positive_y122 and profile['pickup_correction']['distance_mm']!=12.2:
            raise RuntimeError('Expected the inspected +Y 12.2 mm pickup')
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
        claw_setting_unchanged_mm=3.9,grip_tolerance_mm=GRIP_TOLERANCE_MM,grasp_verified=False,automatic_home=False,samples=[state])
    if args.accepted_repeat:
        record.update(repeat_number=args.accepted_repeat,
            operator_confirmation='Three full repeats authorized; adjusted jaw placement inspected and accepted. Continue requested.',
            visual_retention_confirmation_pending=True)
    if args.accepted_trial:
        record.update(trial=args.accepted_trial,
            operator_confirmation='Retry requested full calibration and Squid trial using the previously successful grip/lift; setup and clearance confirmed.',
            visual_retention_confirmation_pending=True)
    if args.nov3_retry_y104 or args.accepted_geometry_repeat:
        record.update(operator_confirmation='Operator confirmed pickup ready and requested continuation without routine visual pauses.',
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
