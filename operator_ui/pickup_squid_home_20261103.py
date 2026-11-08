"""One authorized pickup using the accepted route and gradual jaw sequence."""
import argparse
from copy import deepcopy
import json
import sys
import time
import execute_continuous_squid_return_20261103 as runner
from capture_squid_approach_20261103 import FOLDER, sha, save
from prepare_squid_destination import validate
from proof_lift_plate import api, near, write
from squid_handling_route import load_route, LEGACY_SOURCE, LEGACY_SHA


def main(output_dir=None, authorization=None, *, route_source=LEGACY_SOURCE, route_sha=LEGACY_SHA):
    output_dir = FOLDER if output_dir is None else output_dir
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    output = output_dir / 'pickup_home_trial_20261103.json'
    if output.exists():
        raise RuntimeError('Already attempted; no retry')
    source, source_hash = route_source, route_sha
    accepted = load_route(source, source_hash)
    plans = []
    for phase, points, speeds in (
        ('pickup_approach', accepted['routes']['from_capture'][:5], [137, 137, 137, 5]),
        ('pickup_loaded_return', accepted['routes']['from_capture'][4:], [5, 137, 137, 137]),
    ):
        plan = deepcopy(accepted)
        plan.update(routes={'from_capture': points}, leg_speeds=speeds,
                    completion_status=phase + '_completed_pending_operator_assessment',
                    operator_intent='Operator confirmed successful drop-off and requested pickup and Home using the tested route.')
        path = output_dir / (phase + '_plan_20261103.json')
        if path.exists():
            if json.loads(path.read_bytes()) != plan:
                raise RuntimeError('Trial plan changed')
        else:
            save(path, plan)
        plans.append((path, sha(path), output_dir / (phase + '_trial_20261103.json'), speeds))
    if not api('state')['robot'].get('connected'):
        api('connect', {'ip': '192.168.201.220'})

    def ready(position, opening):
        state = api('state')
        r = state['robot']
        if not r.get('connected') or not r.get('ok') or r.get('errors') or not r.get('enabled') or r['control_mode']['mode'] != 'auto' or r['program_state']['state'] != 'running' or state['sequence']['active']:
            raise RuntimeError('Controller not ready; no recovery')
        near(r['pose_mm'], position, .1)
        if abs(r['external_axes']['E1'] - opening) > .15 + 1e-9:
            raise RuntimeError('Unexpected claw position')
        env = {k: [state['envelope'][k]['min'], state['envelope'][k]['max']] for k in ('X', 'Y', 'Z')}
        if not state['envelope']['enabled'] or env != accepted['envelope'] or api('robot_params') != accepted['cfg'] or sha(source) != source_hash:
            raise RuntimeError('Reviewed settings changed')
        return state

    route = accepted['routes']['from_capture']
    initial = ready(route[0], 7)
    validate(route, initial['robot']['joints'], accepted['cfg'], accepted['envelope'])
    for path, digest, trial, speeds in plans:
        if trial.exists():
            raise RuntimeError('Phase already attempted; no retry')
    print(json.dumps(dict(validated=True, execute=args.execute, jaw_targets=[6, 5, 4.8, 4.6, 4.4, 4.2, 4, 3.9])), flush=True)
    if not args.execute:
        return
    record = dict(status='started', at=time.time(), source_state=initial,
                  operator_confirmation=authorization or 'yes, now attempt to pick it up and take it home',
                  source_sha256=source_hash, steps=[], phases=[])
    write(output, record)

    def travel(index):
        path, digest, trial, speeds = plans[index]
        runner.PLAN, runner.SHA, runner.OUTPUT = path, digest, trial
        runner.main(expected_speeds=tuple(speeds), vertical_legs=(0, 3))
        record['phases'].append(dict(receipt=str(trial), sha256=sha(trial)))
        write(output, record)

    try:
        travel(0)
        opening = 7
        for target in (6, 5, 4.8, 4.6, 4.4, 4.2, 4.0, 3.9):
            ready(route[4], opening)
            step = dict(target_e1=target, speed=5, status='requested', samples=[])
            record['steps'].append(step)
            write(output, record)
            response = api('gripper', dict(action='move', e1=target, speed=5))
            step['response'] = response
            write(output, record)
            if not response.get('ok') or response.get('recovered'):
                raise RuntimeError('Uncertain gripper response; no retry or lift')
            for _ in range(3):
                time.sleep(.25)
                step['samples'].append(ready(route[4], target))
            step['status'] = 'completed'
            opening = target
            write(output, record)
            print(json.dumps(dict(grip_target=target, actual=step['samples'][-1]['robot']['external_axes']['E1'])), flush=True)
        travel(1)
        record.update(status='pickup_and_home_completed_pending_operator_assessment', final_state=ready(route[-1], 3.9))
    except Exception as error:
        record.update(status='stopped_or_failed', error=str(error))
        try:
            record['stop_response'] = api('program', dict(action='stop'))
        except Exception as stop_error:
            record['stop_error'] = str(stop_error)
        raise
    finally:
        record['finished_at'] = time.time()
        write(output, record)
        print(json.dumps(dict(status=record['status'], receipt=str(output))), flush=True)


if __name__ == '__main__':
    main()
