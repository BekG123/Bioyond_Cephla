"""One 5 mm proof lift through existing Flask owner; no reset, grip or retry."""
from concurrent.futures import ThreadPoolExecutor
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

from autonomy import check_path, wrap

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'operator_ui/reports/pickup_home/20261017T105903Z_plan.json'
def api(path,body=None):
    request=Request('http://127.0.0.1:5002/'+path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type':'application/json','X-Cephla-View':'developer'})
    with urlopen(request,timeout=45) as response:return json.load(response)
def write(path,value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def near(actual,expected,tolerance):
    for k in ('X','Y','Z','Rz'):
        d=actual[k]-expected[k]
        if k=='Rz':d=wrap(d)
        if abs(d)>tolerance:raise RuntimeError('Pose mismatch: '+k)
def ready(state):
    r=state['robot']
    if not r.get('ok') or not r.get('connected') or r.get('errors') or not r.get('enabled') or r['control_mode']['mode']!='auto' or r['program_state']['state']!='running' or not r.get('lua_app_initialized'):
        raise RuntimeError('Healthy, already-running Auto controller required; no preparation allowed.')
    if state['sequence']['active']:raise RuntimeError('Another action is active.')
    if not 3.75<=r['external_axes']['E1']<=3.85:raise RuntimeError('Claw position changed; inspect before lifting.')

if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=PLAN)
    parser.add_argument('--operator-confirmed', action='store_true')
    args = parser.parse_args()
    if not args.operator_confirmed:
        raise RuntimeError('Explicit proof-lift clearance confirmation required.')
    PLAN = args.plan.resolve()
    plan=json.loads(PLAN.read_text())
    receipt=PLAN.with_name(PLAN.stem+'_proof_lift.json')
    if receipt.exists():raise RuntimeError('Proof lift already attempted; do not replay this script.')
    record=dict(plan=str(PLAN),plan_sha256=hashlib.sha256(PLAN.read_bytes()).hexdigest(),
        started_at=datetime.now(timezone.utc).isoformat(),
        authorization=plan.get('operator_confirmation',
            'Operator confirmed upward path clear, hands clear and E-stop supervised; one 5 mm lift only.'),
        grasp_verified=False,home_return_started=False,samples=[])
    if api('researcher/api/status')['hand_guiding']['state'] != 'off':
        raise RuntimeError('Hand-guiding must be off.')
    for _ in range(3):
        state=api('state');ready(state);near(state['robot']['pose_mm'],plan['start'],.05)
        record['samples'].append(state);time.sleep(.15)
    envelope={k:(state['envelope'][k]['min'],state['envelope'][k]['max']) for k in ('X','Y','Z')}
    if not state['envelope']['enabled']:raise RuntimeError('Workspace must be enabled.')
    target=plan['proof_lift']['target']
    if abs(target['Z']-plan['start']['Z']-5)>1e-6 or any(target[k]!=plan['start'][k] for k in ('X','Y','Rz')):
        raise RuntimeError('Only the reviewed vertical 5 mm lift is allowed.')
    check_path(plan['start'],target,state['robot']['joints'],api('robot_params'),envelope)
    command=dict(x=target['X'],y=target['Y'],z=target['Z'],rz=target['Rz'],speed=5,interpolation='linear')
    record.update(command=command,status='attempt_started');write(receipt,record)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(api,'move',command)
            while not future.done():
                state=api('state');record['samples'].append(state)
                try:ready(state)
                except Exception:
                    record['stop_response']=api('program',{'action':'stop'})
                    raise
                time.sleep(.2)
            response=future.result();record['response']=response
        if not response.get('ok') or response.get('recovered'):raise RuntimeError('Lift completion uncertain; no retry.')
        state=api('state');ready(state);near(state['robot']['pose_mm'],target,.1)
        record.update(final_state=state,status='lift_completed_awaiting_visual_inspection')
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        if 'stop_response' not in record:
            try:
                record['stop_response']=api('program',{'action':'stop'})
            except Exception as stop_error:
                record['stop_error']=str(stop_error)
        raise
    finally:
        record['finished_at']=datetime.now(timezone.utc).isoformat();write(receipt,record)
    print(json.dumps(dict(record=str(receipt),status=record['status'],pose=state['robot']['pose_mm'],e1=state['robot']['external_axes']['E1'])))
