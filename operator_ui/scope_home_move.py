"""Drive the reviewed four-point scope->Home route through the running Flask owner.

Same geometry as scope_compact_trial.execute (whose one-shot trial record is
already written); individual MoveL at the console's 50 mm/s linear cap. Never
starts/resets the program, commands the claw, changes limits, or retries.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import time

from autonomy import check_path
from proof_lift_plate import api, near, write, ROOT

E1_REF = None  # set from the scope route's recorded e1_start


def ready(state):
    """Scope-route readiness: the HoldingService band, not the plate-carry band."""
    r = state['robot']
    if (not r.get('ok') or not r.get('connected') or r.get('errors') or not r.get('enabled')
            or r['control_mode']['mode'] != 'auto' or r['program_state']['state'] != 'running'
            or not r.get('lua_app_initialized')):
        raise RuntimeError('Healthy, already-running Auto controller required; no preparation allowed.')
    if state['sequence']['active']:
        raise RuntimeError('Another action is active.')
    e1 = r['external_axes']['E1']
    if type(e1) not in (float, int) or abs(e1 - E1_REF) > .1:
        raise RuntimeError('Gripper feedback changed; inspect before continuing.')

PLAN = ROOT/'operator_ui/reports/squid/compact4_20261017T131133Z_ace8e9/candidate.json'
SPEED = 50

if __name__ == '__main__':
    plan = json.loads(PLAN.read_text())
    route = list(reversed([plan['start']] + plan['points']))
    home = json.loads((ROOT/'operator_ui/points.json').read_text(encoding='utf-8-sig'))
    h = home['points'][home['roles']['home']]
    near(route[-1], dict(X=h['x'], Y=h['y'], Z=h['z_grip'], Rz=h['rz']), .001)

    trial = json.loads(PLAN.with_name('compact4_roundtrip_speed137_trial.json').read_text())
    globals()['E1_REF'] = trial['plan']['e1_start']

    receipt = PLAN.with_name(f'scope_home_move_{time.time_ns()}.json')
    record = dict(plan=str(PLAN), plan_sha256=hashlib.sha256(PLAN.read_bytes()).hexdigest(),
                  started_at=datetime.now(timezone.utc).isoformat(), route=route, speed=SPEED,
                  authorization='User requested the arm be moved from the scope to the saved Home '
                                'on the reviewed four-point route, supervised at the E-stop.',
                  legs=[], samples=[])

    state = api('state'); ready(state)
    near(state['robot']['pose_mm'], route[0], .05)
    if not state['envelope']['enabled']:
        raise RuntimeError('Workspace must be enabled.')
    envelope = {k: (state['envelope'][k]['min'], state['envelope'][k]['max']) for k in ('X', 'Y', 'Z')}
    cfg = api('robot_params')

    current, q = route[0], state['robot']['joints']
    for point in route[1:]:
        q = check_path(current, point, q, cfg, envelope)
        current = point
    record.update(status='attempt_started', final_joints=q, e1_ref=E1_REF); write(receipt, record)
    print('route validated; final J2 %.2f J3 %.2f J4 %.2f' % (q['J2'], q['J3'], q['J4']))

    try:
        for i, target in enumerate(route[1:], 1):
            state = api('state'); ready(state)
            command = dict(x=target['X'], y=target['Y'], z=target['Z'], rz=target['Rz'],
                           speed=SPEED, interpolation='linear')
            leg = dict(n=i, target=target, command=command, started_at=time.time())
            record['legs'].append(leg); write(receipt, record)
            print(f"leg {i}/4 -> X{target['X']} Y{target['Y']} Z{target['Z']} Rz{target['Rz']}")
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(api, 'move', command)
                while not future.done():
                    snap = api('state'); record['samples'].append(snap)
                    try:
                        ready(snap)
                    except Exception:
                        record['stop_response'] = api('program', {'action': 'stop'})
                        raise
                    time.sleep(.2)
                result = future.result()
            leg.update(result=result, finished_at=time.time())
            if not result.get('ok'):
                raise RuntimeError(f"leg {i} refused/failed: {result.get('error')}")
            near(api('state')['robot']['pose_mm'], target, .2)
            print(f"  arrived ({leg['finished_at']-leg['started_at']:.1f} s)")
        final = api('state')
        record.update(status='completed', final_robot=final['robot'])
        print('AT HOME:', final['robot']['pose_mm'], final['robot']['joints'])
    except Exception as error:
        record.update(status='stopped_or_failed', error=str(error))
        raise
    finally:
        record['finished_at'] = datetime.now(timezone.utc).isoformat()
        write(receipt, record)
        print('record:', receipt)
