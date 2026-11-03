"""One authorized calibration, Squid drop-off and pickup; no retries."""
import argparse
import json
import sys
import time
import repeat_accepted_y104_20261103 as calibration
import regrip_48well_to_3p9 as grip
import proof_lift_48well_3p9_5mm as lift
import dropoff_approach_20261103 as approach
import release_empty_home_20261103 as release
import pickup_squid_home_20261103 as pickup
from capture_squid_approach_20261103 import FOLDER, sha
from proof_lift_plate import api, near, write
from plate48_workflow import reference
from prepare_squid_destination import validate

OUT = FOLDER / 'full_calibration_handling_20261103'
AUTH = 'Operator confirmed one full calibration and pickup, loaded Home, Squid drop-off, empty Home, Squid pickup and loaded Home. Plate returned to arm holder; unchanged accepted setup.'


def invoke(module, flags, *positional):
    prior = sys.argv[:]
    try:
        sys.argv = [module.__file__, *flags]
        module.main(*positional)
    finally:
        sys.argv = prior


def main(closed_claw=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if OUT.exists():
        raise RuntimeError('Already attempted; no replay')
    profile, digest, _ = reference(require_grip=False)
    if digest != calibration.SHA or profile['pickup_correction']['distance_mm'] != 10.4:
        raise RuntimeError('Accepted pickup changed')
    source = FOLDER / 'closed_claw_roundtrip_plan_20261103.json'
    if sha(source) != '4eb1eaef27adacfd0116b3376bc6765896aba0dbd0c05ac7429e4ff857352c81':
        raise RuntimeError('Squid route changed')
    plan = json.loads(source.read_bytes())
    if not api('state')['robot'].get('connected'):
        api('connect', {'ip': '192.168.201.220'})
    state = api('state')
    r = state['robot']
    if not r.get('ok') or r.get('errors') or not r.get('enabled') or r['program_state']['state'] != 'running' or r['control_mode']['mode'] != 'auto' or state['sequence']['active']:
        raise RuntimeError('Healthy idle Auto required; no restart')
    near(r['pose_mm'], plan['routes']['from_capture'][0], .05)
    if not state['envelope']['enabled'] or api('robot_params') != plan['cfg']:
        raise RuntimeError('Workspace/settings changed')
    if api('researcher/api/status')['hand_guiding']['state'] != 'off':
        raise RuntimeError('Hand guiding must be off')
    validate(plan['routes']['from_capture'], r['joints'], plan['cfg'], plan['envelope'])
    print(json.dumps(dict(validated=True, execute=args.execute, authorization=AUTH)), flush=True)
    if not args.execute:
        return
    OUT.mkdir()
    record = dict(status='running', at=time.time(), authorization=AUTH, initial_state=state,
                  pickup_profile_sha256=digest, squid_plan_sha256=sha(source), events=[], automatic_retries=False)
    output = OUT / 'run.json'

    def phase(name, **details):
        record['phase'] = name
        record['events'].append(dict(phase=name, at=time.time(), **details))
        write(output, record)
        print(json.dumps(dict(phase=name, **details)), flush=True)

    try:
        phase('calibration_started')
        parent = calibration.p.ROOT / 'operator_ui/reports/projected_alignment'
        before = set(parent.glob('accepted_y104_repeat_*'))
        result = api('seq/calibrate_48well', dict(confirm=True, cell_clear=True, empty_gripper=True, plate_unchanged=True))
        if not result.get('ok'):
            raise RuntimeError('Calibration start refused')
        invoke(calibration, ['--execute'])
        created = set(parent.glob('accepted_y104_repeat_*')) - before
        if len(created) != 1:
            raise RuntimeError('Fresh calibration receipt ambiguous')
        folder = created.pop()
        receipt = folder / 'attempt.json'
        calibration.verify_repeat(json.loads(receipt.read_bytes()), profile, digest, api('seq'))
        record['calibration_folder'] = str(folder)
        phase('alignment_descent_completed')
        invoke(grip, ['--operator-confirmed', '--inspected-positive-y104', '--accepted-geometry-repeat', str(receipt)])
        phase('grip_completed')
        invoke(lift, ['--operator-confirmed', '--positive-y104', '--accepted-geometry-repeat', str(receipt)])
        phase('proof_lift_completed')
        proposed = api('researcher/api/lacry/button/move_home', {})
        write(OUT / 'home_preview.json', proposed)
        home = proposed['plan']
        if home.get('preserve_gripper') is not True or home.get('dispatch') != 'ik_home_return' or home.get('prepare'):
            raise RuntimeError('Loaded Home preservation required')
        near(home['home'], plan['routes']['from_capture'][0], .01)
        response = api('researcher/api/lacry/confirm', dict(ready=True, plan_id=home['id']))
        write(OUT / 'home_dispatch.json', response)
        deadline = time.monotonic() + 240
        while True:
            seq = api('seq')
            state = api('state')
            r = state['robot']
            if seq['name'] != 'researcher_home' or not r.get('ok') or r.get('errors') or abs(r['external_axes']['E1'] - 3.9) > .15:
                raise RuntimeError('Loaded Home state uncertain')
            if not seq['active']:
                if not (seq.get('result') or {}).get('ok'):
                    raise RuntimeError('Home failed')
                break
            if time.monotonic() > deadline:
                raise RuntimeError('Home timed out')
            time.sleep(.5)
        near(r['pose_mm'], home['home'], .05)
        write(OUT / 'calibrated_home.json', dict(state=state, sequence=seq, calibration_folder=str(folder)))
        phase('calibrated_loaded_home_completed')
        if closed_claw:
            import execute_continuous_squid_return_20261103 as travel
            from copy import deepcopy
            from capture_squid_approach_20261103 import save
            closed_plan = deepcopy(plan)
            closed_plan['operator_intent'] = AUTH
            closed_plan['completion_status'] = 'calibrated_closed_roundtrip_completed_pending_operator_assessment'
            travel.PLAN = OUT / 'closed_roundtrip_plan.json'
            travel.OUTPUT = OUT / 'closed_roundtrip_trial.json'
            save(travel.PLAN, closed_plan)
            travel.SHA = sha(travel.PLAN)
            phase('closed_claw_roundtrip_started')
            travel.main(expected_speeds=(137,137,137,5,5,137,137,137), vertical_legs=(0,3,4,7))
            record['final_state'] = api('state')
            near(record['final_state']['robot']['pose_mm'], home['home'], .05)
            record['status'] = 'full_calibration_closed_roundtrip_home_completed_pending_operator_assessment'
            phase('closed_claw_loaded_home_completed')
            return
        delivery = OUT / 'dropoff'
        delivery.mkdir()
        invoke(approach, ['--execute'], delivery)
        phase('squid_delivery_completed')
        invoke(release, ['--execute'], delivery, AUTH)
        phase('dropoff_empty_home_completed')
        retrieval = OUT / 'pickup'
        retrieval.mkdir()
        invoke(pickup, ['--execute'], retrieval, AUTH)
        record['final_state'] = api('state')
        near(record['final_state']['robot']['pose_mm'], home['home'], .05)
        record['status'] = 'full_calibration_dropoff_pickup_home_completed_pending_operator_assessment'
        phase('loaded_home_completed')
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
        print(json.dumps(dict(status=record['status'], phase=record.get('phase'), report=str(output))), flush=True)


if __name__ == '__main__':
    main()
