"""One explicitly authorized slow vertical Squid descent; no release/retry."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import time

from projected_pickup import ROOT
from prepare_squid_destination import validate
from proof_lift_plate import api, near, write

FOLDER = ROOT/'operator_ui/reports/squid_48well_approach'
SOURCE = FOLDER/'approach_20261103T180838653466Z.json'
APPROACH = FOLDER/'loaded_trial_7474e466acdd4b248cde354b2e9b0b54.json'
OUTPUT = FOLDER/'slow_descent_20261103_from_7474e466.json'
SHA = 'a2fb701e3224515e4c4437332b24f4be360aa1c62e074cc19eb39ff6bd4ae613'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if OUTPUT.exists():
        raise RuntimeError('Descent already attempted; no replay.')
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SHA:
        raise RuntimeError('Taught destination changed.')
    candidate = json.loads(SOURCE.read_bytes())
    arrival = json.loads(APPROACH.read_bytes())
    if (arrival['status'] != 'loaded_above_squid_awaiting_operator_teaching'
            or arrival['candidate_sha256'] != SHA):
        raise RuntimeError('Successful matching overhead approach required.')
    start, target = candidate['stop_before_descent'], candidate['target']
    if any(abs(start[k]-target[k]) > 1e-9 for k in ('X','Y','Rz')) or not 0 < start['Z']-target['Z'] <= 35:
        raise RuntimeError('Expected short vertical descent only.')
    cfg = api('robot_params')
    if cfg != candidate['cfg']:
        raise RuntimeError('Robot settings changed.')
    state = api('state')
    initial_e1 = state['robot'].get('external_axes', {}).get('E1')
    if initial_e1 is None or abs(initial_e1-3.9) > .15:
        raise RuntimeError('Loaded grip feedback unavailable or changed.')

    def check(state):
        r = state['robot']
        if (not r.get('connected') or not r.get('ok') or r.get('errors') or not r.get('enabled')
                or r.get('control_mode', {}).get('mode') != 'auto'
                or r.get('program_state', {}).get('state') != 'running' or state['sequence']['active']):
            raise RuntimeError('Controller not ready; no restart.')
        env = {k:[state['envelope'][k]['min'],state['envelope'][k]['max']] for k in ('X','Y','Z')}
        if not state['envelope']['enabled'] or env != candidate['envelope']:
            raise RuntimeError('Workspace changed.')
        if abs(r['external_axes']['E1']-initial_e1) > .1:
            raise RuntimeError('Grip feedback changed during descent.')
        pose = r['pose_mm']
        near(pose, {**start, 'Z':pose['Z']}, .15)
        if not target['Z']-.15 <= pose['Z'] <= start['Z']+.15:
            raise RuntimeError('Vertical descent envelope exceeded.')

    check(state)
    near(state['robot']['pose_mm'], start, .05)
    checked = validate([start,target], state['robot']['joints'], cfg, candidate['envelope'])
    print(json.dumps(dict(start=start,target=target,speed=5,execute=args.execute)),flush=True)
    if not args.execute:
        return
    record = dict(status='attempt_started',at=time.time(),candidate_sha256=SHA,
        approach=str(APPROACH),approach_sha256=hashlib.sha256(APPROACH.read_bytes()).hexdigest(),
        authorization='Operator: Yes, slowly descend now for me to see whether this will work.',
        start=start,target=target,speed=5,validation=checked,samples=[state],release_executed=False)
    write(OUTPUT,record)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(api,'move',dict(x=target['X'],y=target['Y'],z=target['Z'],
                rz=target['Rz'],speed=5,interpolation='linear'))
            try:
                while not future.done():
                    state = api('state'); record['samples'].append(state); check(state)
                    time.sleep(.2)
                response = future.result(); record['response'] = response
                if not response.get('ok') or response.get('recovered'):
                    raise RuntimeError('Descent completion uncertain.')
            except Exception:
                record['stop_response'] = api('program',dict(action='stop'))
                raise
        state = api('state'); check(state); near(state['robot']['pose_mm'],target,.1)
        record.update(status='at_dropoff_awaiting_support_and_release_confirmation',final_state=state)
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        if 'stop_response' not in record:
            record['stop_response'] = api('program',dict(action='stop'))
        raise
    finally:
        record['finished_at']=time.time(); write(OUTPUT,record)
        print(json.dumps(dict(report=str(OUTPUT),status=record['status'])),flush=True)


if __name__ == '__main__':
    main()
