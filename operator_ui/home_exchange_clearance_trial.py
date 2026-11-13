"""After inspected HOME seating: release to 7, lift 5 at 5, open to 28.

No holder rotation, startup, recovery or retry. Keeps the support observation
separate from controller feedback and binds every command to the seated pose.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import time

from autonomy import check_path
import home_exchange_holder_trial as seating
from proof_lift_plate import api, near, write
from projected_pickup import sha


def healthy(state, e1=None):
    r = state['robot']
    if (not r.get('connected') or not r.get('ok') or r.get('errors')
            or not r.get('enabled') or r.get('control_mode', {}).get('mode') != 'auto'
            or r.get('program_state', {}).get('state') != 'running'
            or state['sequence']['active'] or not state['envelope']['enabled']):
        raise RuntimeError('Healthy stationary-owner Auto required; no recovery.')
    actual = r.get('external_axes', {}).get('E1')
    if not isinstance(actual, (float,int)) or not math.isfinite(actual):
        raise RuntimeError('Fresh finite gripper feedback required.')
    if e1 is not None and abs(actual-e1) > .15:
        raise RuntimeError('Gripper feedback does not match this phase.')
    return r


def run(calibration_report, *, support_confirmed=False):
    if support_confirmed is not True:
        raise RuntimeError('Operator must inspect full plate support before release.')
    _, binding = seating.bind(calibration_report)
    path = seating.holder.RECEIPT
    raw = path.read_bytes()
    seat = json.loads(raw)
    if seat.get('status') != 'placement_completed_awaiting_inspection_before_release':
        raise RuntimeError('Successful checked seating required.')
    if seat['plan'].get('binding') != binding:
        raise RuntimeError('Seating and calibration evidence differ.')
    out = path.with_name('home_holder_release_clearance.json')
    if out.exists():
        raise RuntimeError('Clearance already attempted; no retry.')
    start = seat['final_state']['robot']['pose_mm']
    s = api('state'); healthy(s, 3.9); near(s['robot']['pose_mm'], start, .1)
    if api('researcher/api/status')['hand_guiding']['state'] != 'off':
        raise RuntimeError('Hand guiding must be off.')
    native = seating.verify_holder_stationary()
    target = dict(start, Z=start['Z']+5)
    cfg = api('robot_params')
    env = {k:(s['envelope'][k]['min'], s['envelope'][k]['max']) for k in ('X','Y','Z')}
    joints = check_path(start, target, s['robot']['joints'], cfg, env)
    record = dict(at=time.time(), status='started', binding=binding,
                  seating_receipt_sha256=sha(raw), start=start, target=target,
                  operator_observation='Plate flat and fully supported; jaws clear to open, hands clear and E-stop supervised.',
                  release_e1_mm=7, clearance_e1_mm=28, lift_mm=5, lift_speed=5,
                  ik_joints=joints, before=s, holder_before=native,
                  phases=[], rotation_sent=False, automatic_retry=False)
    write(out, record)

    def command(label, endpoint, body, final_e1, final_pose):
        phase = dict(label=label, at=time.time(), command=body, samples=[])
        record['phases'].append(phase); write(out, record)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(api, endpoint, body)
            while not future.done():
                snapshot = api('state'); phase['samples'].append(snapshot)
                try:
                    healthy(snapshot, 7 if endpoint == 'move' else None)
                    if endpoint == 'gripper':
                        near(snapshot['robot']['pose_mm'], final_pose, .1)
                except Exception:
                    record['stop_response'] = api('program', {'action':'stop'})
                    raise
                time.sleep(.2)
            response = future.result()
        phase['response'] = response
        if not response.get('ok') or response.get('recovered') or response.get('gripper_warning'):
            raise RuntimeError('Command completion uncertain; no retry.')
        after = api('state'); healthy(after, final_e1)
        near(after['robot']['pose_mm'], final_pose, .1)
        phase['after'] = after; write(out, record)
        print(json.dumps(dict(phase=label, pose=after['robot']['pose_mm'],
                              e1=after['robot']['external_axes']['E1'])), flush=True)
        return after

    try:
        command('release_supported_plate', 'gripper', dict(action='move',e1=7,speed=5), 7, start)
        command('lift_empty_jaws_5mm', 'move',
                dict(x=target['X'],y=target['Y'],z=target['Z'],rz=target['Rz'],speed=5,interpolation='linear'), 7, target)
        final = command('open_for_holder_clearance', 'gripper', dict(action='move',e1=28,speed=5), 28, target)
        record.update(status='home_release_lift_open_completed', final_state=final,
                      holder_after=seating.verify_holder_stationary(),
                      final_visual_observation_pending=True)
    except Exception as error:
        record.update(status='stopped_or_failed', error=str(error))
        if 'stop_response' not in record:
            try: record['stop_response'] = api('program', {'action':'stop'})
            except Exception as stop_error: record['stop_error'] = str(stop_error)
        raise
    finally:
        record['finished_at'] = time.time(); write(out, record)
    print(json.dumps(dict(status=record['status'], report=str(out))), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('calibration_report')
    parser.add_argument('--support-confirmed', action='store_true')
    args = parser.parse_args()
    run(args.calibration_report, support_confirmed=args.support_confirmed)
