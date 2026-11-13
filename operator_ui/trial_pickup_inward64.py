"""Supervised 6.4 mm pickup correction; stops open at descent, never grips."""
import argparse
from copy import deepcopy
import json
import math
import time
from uuid import uuid4

import projected_pickup as pickup
from plate48_workflow import match_placement
from prepare_squid_destination import validate
from test_squid_destination_empty import api
from scope_step_trial import near

PARENT_SHA = '163d9aed7350f1e003fe3d8cc9b189500465027d6b518f723af2a2251c99ce2b'


def shifted_endpoint(endpoint, cfg):
    goal = deepcopy(endpoint)
    dx, dy = cfg['base_x_mm']-goal['X'], cfg['base_y_mm']-goal['Y']
    radius = math.hypot(dx, dy)
    if not math.isfinite(radius) or radius <= 6.4:
        raise ValueError('Invalid base-directed shift')
    goal.update(X=goal['X']+6.4*dx/radius, Y=goal['Y']+6.4*dy/radius)
    return goal


def positive_y_endpoint(endpoint, distance=6.4):
    goal = deepcopy(endpoint)
    if not all(math.isfinite(goal[k]) for k in ('X','Y','Z','Rz')):
        raise ValueError('Nonfinite pickup endpoint')
    if distance not in (6.4,8.4,9.4,10.4,11.4,12.0,12.2,12.3,12.4,12.5,12.7):raise ValueError('Unreviewed +Y correction')
    goal['Y'] += distance
    return goal


def main(direction='rejected_inward', total_shift=6.4, parent_sha=PARENT_SHA):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--open-before-descent', action='store_true',
                        help='Open empty claws at the corrected hover, after calibration/alignment.')
    args = parser.parse_args()
    if args.execute and direction != 'positive_base_y':
        raise RuntimeError('Inward trial rejected by operator. Baseline restored; do not replay this direction.')
    profile, digest = pickup.load()
    if digest != parent_sha:
        raise RuntimeError('Pickup parent changed; no cumulative shift')
    cfg = api('robot_params')
    source=profile['pickup_correction']['source_endpoint'] if total_shift in (8.4,9.4,10.4,11.4,12.0,12.2,12.3,12.4,12.5,12.7) else profile['candidate_endpoint']
    goal = positive_y_endpoint(source,total_shift) if direction=='positive_base_y' else shifted_endpoint(profile['candidate_endpoint'], cfg)
    print(json.dumps(dict(endpoint=goal, shift_mm=total_shift, direction=direction,
                          grip=False, execute=args.execute)), flush=True)
    if not args.execute:
        return
    folder = pickup.ROOT/'operator_ui/reports/projected_alignment'/(f'positive_y{round(total_shift*10)}_'+uuid4().hex)
    folder.mkdir()
    original = pickup.PROFILE.read_bytes()
    (folder/'previous_profile.json').write_bytes(original)
    record = dict(at=time.time(), parent_sha256=digest, endpoint=goal,
                  authorization=f'Operator requested +Y {total_shift} mm total from original pickup, empty claws, return Home then revised calibration. Stop open before grip.',
                  status='preparing', events=[], grip_executed=False,
                  squid_destination_changed=False, visual_acceptance_pending=True)
    def save():
        (folder/'attempt.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    def healthy():
        state = api('state'); r = state['robot']
        if (not r.get('connected') or r.get('errors') or not r.get('enabled')
                or r['control_mode']['mode']!='auto' or r['program_state']['state']!='running'
                or not state['envelope']['enabled']):
            raise RuntimeError('Controller not ready; no restart or retry')
        if api('robot_params') != cfg:
            raise RuntimeError('Robot settings changed')
        return state
    def wait_sequence(name):
        deadline = time.monotonic()+240
        while True:
            seq = api('seq'); healthy()
            if seq['name'] != name:
                raise RuntimeError('Sequence owner changed')
            if not seq['active']:
                record['events'].append(dict(sequence=seq)); save()
                if not (seq.get('result') or {}).get('ok'):
                    raise RuntimeError(str(seq.get('result')))
                return seq['result']
            if time.monotonic() > deadline:
                raise RuntimeError('Sequence timed out; no retry')
            time.sleep(.5)
    save()
    try:
        calibration = wait_sequence('plate48_calibrate')
        state = healthy(); near(state['robot']['pose_mm'],calibration['context']['pose'],.05)
        if pickup.sha(pickup.PROFILE.read_bytes()) != digest:
            raise RuntimeError('Pickup changed during calibration')
        result = api('seq/projected_alignment', dict(confirm=True, cell_clear=True, empty_gripper=True,
                     expected_start=calibration['context']['pose'], expected_target=calibration['target']))
        record['events'].append(dict(alignment_dispatch=result)); save()
        aligned = wait_sequence('projected_alignment')
        accepted = json.loads(pickup.evidence(profile['acceptance'],profile['acceptance_sha256']).read_bytes())
        match_placement(aligned['route']['target'], accepted['fresh_alignment']['route']['target'])
        state = healthy(); r = state['robot']; hover = dict(goal,Z=300.)
        env = {k:[state['envelope'][k]['min'],state['envelope'][k]['max']] for k in ('X','Y','Z')}
        checked = validate([r['pose_mm'],hover,goal],r['joints'],cfg,env)
        record['checked'] = checked; save()
        authorization = dict(at=time.time(), supervised_open_claw_trial_authorized=True,
            visual_alignment_accepted=False, alignment_pose_mm=hover, proposed_endpoint=goal,
            fresh_alignment=aligned, parent_profile_sha256=digest,
            direction=direction, distance_mm=total_shift, grip_authorized=False)
        auth_path = folder/'authorization.json'
        auth_path.write_text(json.dumps(authorization,indent=2),encoding='utf-8')
        candidate = deepcopy(profile)
        for key in ('accepted_grip_reference','accepted_grip_reference_sha256',
                    'descent_acceptance','descent_acceptance_sha256'):
            candidate.pop(key,None)
        candidate.update(alignment_pose_mm=hover,candidate_endpoint=goal,
            acceptance=auth_path.relative_to(pickup.ROOT).as_posix(),
            acceptance_sha256=pickup.sha(auth_path.read_bytes()),
            descent_status='supervised_open_claw_trial_pending',
            physical_grip_validated_for_plate=False,current_placement_grip_tested=False,
            automatic_lift_enabled=False,full_pickup_verified=False,
            pickup_correction=dict(direction=direction,distance_mm=total_shift,
                parent_profile_sha256=digest,source_endpoint=source),
            total_outward_correction_mm=profile['total_outward_correction_mm'])
        candidate_path = folder/'candidate_profile.json'
        candidate_path.write_text(json.dumps(candidate,indent=2),encoding='utf-8')
        pickup.load(candidate_path)
        healthy()
        if pickup.PROFILE.read_bytes()!=original:
            raise RuntimeError('Profile changed before activation')
        temporary = pickup.PROFILE.with_suffix('.positive_y64.tmp')
        temporary.write_bytes(candidate_path.read_bytes()); temporary.replace(pickup.PROFILE)
        record['candidate_sha256'] = pickup.sha(candidate_path.read_bytes()); save()
        response = api('move',dict(x=hover['X'],y=hover['Y'],z=hover['Z'],rz=hover['Rz'],speed=5,interpolation='linear'))
        record['events'].append(dict(correction_response=response)); save()
        if response.get('recovered'):
            raise RuntimeError('Uncertain correction; no further movement')
        near(healthy()['robot']['pose_mm'],hover,.05)
        if args.open_before_descent:
            print('At corrected hover: opening empty claws to 28 mm before descent.',flush=True)
            opened = api('gripper',dict(action='move',e1=28,speed=5))
            record['events'].append(dict(open_before_descent=opened)); save()
            if not opened.get('ok') or opened.get('recovered'):
                raise RuntimeError('Claw opening did not complete cleanly; no descent')
            state = healthy()
            near(state['robot']['pose_mm'],hover,.05)
            if not 27.98 <= state['robot']['external_axes']['E1'] <= 28.05:
                raise RuntimeError('Open claws not verified; no descent')
        print('Corrected alignment reached; starting open-claw descent.',flush=True)
        dispatch = api('seq/projected_descent_trial',dict(ready=True,empty_gripper=True,
            cell_clear=True,plate_unchanged=True,expected_profile_sha256=record['candidate_sha256']))
        record['events'].append(dict(descent_dispatch=dispatch)); save()
        wait_sequence('researcher_descend')
        final=healthy()['robot']; near(final['pose_mm'],goal,.05)
        if not 27.98 <= final['external_axes']['E1'] <= 28.05:
            raise RuntimeError('Open claws not confirmed')
        record.update(status='open_claw_descent_complete_awaiting_visual_acceptance',final_robot=final)
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        try: record['stop']=api('program',dict(action='stop'))
        except Exception as stop_error: record['stop_error']=str(stop_error)
        raise
    finally:
        save(); print(json.dumps(dict(report=str(folder/'attempt.json'),status=record['status'])),flush=True)


if __name__=='__main__':
    main()
