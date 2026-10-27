"""One supervised empty-gripper trial through Lacry; no controller preparation."""
import argparse
import json
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from hamilton_true_home import ROOT, configured, validate_route
from scope_step_trial import near


def api(path,body=None):
    request=Request('http://127.0.0.1:5002'+path,
                    data=None if body is None else json.dumps(body).encode(),
                    headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=15) as response:
        return json.load(response)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--plan-id',required=True)
    parser.add_argument('--empty-gripper-confirmed',action='store_true')
    args=parser.parse_args()
    if not args.empty_gripper_confirmed:
        raise RuntimeError('Require explicit empty-gripper/clearance/E-stop confirmation.')
    state=api('/state');r=state['robot']
    if (state['sequence']['active'] or not r['ok'] or r['errors'] or not r['enabled']
        or r['control_mode']['mode']!='auto' or r['program_state']['state']!='running'):
        raise RuntimeError('Require already healthy running Auto; no reset or restart.')
    e1=r['external_axes']['E1']
    if abs(e1)>.1:
        raise RuntimeError('Expected confirmed empty closed jaws after preparation.')
    pending=api('/researcher/api/lacry/state')['pending']
    if not pending or pending['id']!=args.plan_id:
        raise RuntimeError('Reviewed Home plan changed.')
    review=configured()
    path=ROOT/'reports/hamilton'/('zero_roundtrip_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
    record=dict(status='authorized',started_at=time.time(),before=state,route=review,
        authorization='Operator: Removed plate, gripper empty, path clear, E-stop confirmed. Earlier confirmed arm released and both directions clear.',
        speed=137,empty_gripper=True,phases=[],operator_acceptance=None,
        motion_requested=False,initial_review_id=args.plan_id)
    with path.open('x',encoding='utf-8') as stream:
        json.dump(record,stream,indent=2)
    def save():
        path.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
    print('Recording '+str(path),flush=True)
    try:
        for action,direction in [('move_home','reverse'),('move_hamilton','forward')]:
            # /lacry/state exposes an abbreviated pending summary. Button
            # proposals return the full executable plan without moving.
            plan=api('/researcher/api/lacry/button/'+action,{})['plan']
            if plan.get('prepare') or plan.get('dispatch') or plan['actions']!=[action] or len(plan['steps'])!=1:
                raise RuntimeError('Unexpected dispatch or preparation; no motion.')
            step=plan['steps'][0]
            if step['profile']!={'hamilton_home':True} or step['points']!=review[direction][1:]:
                raise RuntimeError('Route differs from reviewed trial.')
            validate_route(plan['start'],step['points'],review)
            phase=dict(action=action,plan=plan,started_at=time.time(),samples=[])
            record['phases'].append(phase);save()
            record['motion_requested']=True;save()
            response=api('/researcher/api/lacry/confirm',dict(ready=True,plan_id=plan['id']))
            phase['response']=response;save()
            if not response.get('ok'):
                raise RuntimeError(str(response))
            print(action+' started',flush=True)
            deadline=time.monotonic()+120
            while True:
                state=api('/state');seq=api('/seq')
                phase['samples'].append(dict(at=time.time(),state=state,sequence=seq));save()
                robot=state['robot']
                if not robot['ok'] or robot['errors']:
                    raise RuntimeError('Controller fault or unavailable feedback.')
                if abs(robot['external_axes']['E1']-e1)>.1:
                    raise RuntimeError('Unexpected gripper movement.')
                if seq['name']!='lacry_plan':
                    raise RuntimeError('Unexpected sequence owner.')
                if not seq['active']:
                    if seq['state']!='done' or not (seq.get('result') or {}).get('ok'):
                        raise RuntimeError('Trial step failed: '+str(seq.get('result')))
                    near(robot['pose_mm'],review[direction][-1],.2)
                    phase.update(status='completed',finished_at=time.time(),final_robot=robot);save()
                    print(action+' completed '+json.dumps(robot['pose_mm']),flush=True)
                    break
                if time.monotonic()>deadline:
                    raise RuntimeError('Trial timed out; no retry.')
                time.sleep(.4)
        record.update(status='completed',finished_at=time.time(),final=api('/state'));save()
        print(json.dumps(dict(ok=True,record=str(path),final=record['final']['robot']['pose_mm'],
                              joints=record['final']['robot']['joints'],
                              durations_s=[p['finished_at']-p['started_at'] for p in record['phases']]),
                         indent=2),flush=True)
    except Exception as error:
        record.update(status='failed_or_uncertain' if record['motion_requested'] else 'blocked_before_motion',
                      error=str(error),finished_at=time.time())
        try:
            if api('/seq').get('active'):
                record['stop_response']=api('/researcher/api/lacry/stop',{})
        finally:
            save()
        raise


if __name__=='__main__':
    main()
