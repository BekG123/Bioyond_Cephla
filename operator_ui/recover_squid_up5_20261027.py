"""Explicitly authorized vertical recovery only; no lateral continuation."""
import argparse,json,time
from proof_lift_plate import api,near,write,ROOT
from autonomy import check_path

FOLDER=ROOT/'operator_ui/reports/projected_alignment'
PLAN=FOLDER/'squid_caught_up5_20261027_plan.json'
OUTPUT=FOLDER/'squid_caught_up5_20261027_trial.json'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-confirmed',action='store_true');args=parser.parse_args()
    state=api('state');r=state['robot']
    if not r.get('connected') or state['sequence']['active']:raise RuntimeError('Connected idle owner required.')
    start={k:r['pose_mm'][k] for k in ('X','Y','Z','Rz')}
    near(start,dict(X=244.911,Y=352.635,Z=286.231,Rz=80.0),.05)
    if r['external_axes']['E1']>.15:raise RuntimeError('Empty claw feedback changed; inspect before startup.')
    cfg=api('robot_params');env={k:(state['envelope'][k]['min'],state['envelope'][k]['max']) for k in ('X','Y','Z')}
    target={**start,'Z':start['Z']+5.0}
    joints=check_path(start,target,r['joints'],cfg,env)
    if not state['envelope']['enabled'] or not 0<=r['joints']['J1']+5<=400:raise RuntimeError('Workspace/J1 check failed.')
    if not args.execute_confirmed:
        plan=dict(start=start,target=target,speed=5,cfg=cfg,envelope=env,joints=joints,
            authorization='Operator confirmed straight-up 5 mm frees the caught claw without pulling holder or plate; path clear.',
            before=state,hardware_commands_sent=False)
        with PLAN.open('x',encoding='utf-8') as stream:json.dump(plan,stream,indent=2)
        print(json.dumps(dict(plan=str(PLAN),target=target,ik_passed=True)));return
    plan=json.loads(PLAN.read_bytes());near(start,plan['start'],.05)
    if cfg!=plan['cfg'] or {k:list(v) for k,v in env.items()}!=plan['envelope']:raise RuntimeError('Policy changed.')
    record=dict(status='prepared',plan=plan,before=state,events=[],automatic_retry=False)
    with OUTPUT.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    try:
        for path,body in [('clear_errors',dict(confirm=True)),('enable',dict(confirm=True)),('program',dict(action='start'))]:
            response=api(path,body);record['events'].append(dict(at=time.time(),action=path,response=response));write(OUTPUT,record)
            if not response.get('ok') or response.get('errors_after'):raise RuntimeError('Recovery preparation refused: '+str(response))
            current=api('state');near(current['robot']['pose_mm'],start,.05)
            if current['robot'].get('errors'):raise RuntimeError('Fault remains after preparation.')
        r=api('state')['robot']
        if (not r['enabled'] or r['program_state']['state']!='running' or r['control_mode']['mode']!='auto'
                or r['external_axes']['E1']>.15):raise RuntimeError('Prepared state differs; stop.')
        command=dict(x=plan['target']['X'],y=plan['target']['Y'],z=plan['target']['Z'],rz=plan['target']['Rz'],speed=5,interpolation='linear')
        record.update(status='upward_move_requested',command=command);write(OUTPUT,record)
        response=api('move',command);record['move_response']=response
        if not response.get('ok') or response.get('recovered'):raise RuntimeError('Upward move uncertain; no retry.')
        state=api('state');near(state['robot']['pose_mm'],plan['target'],.1)
        if state['robot'].get('errors'):raise RuntimeError('Controller fault after move.')
        record.update(status='up5_completed_contact_inspection_pending',after=state)
    except Exception as exc:
        record.update(status='stopped_or_failed',error=str(exc))
        record['stop_response']=api('program',dict(action='stop'));raise
    finally:
        record['finished_at']=time.time();write(OUTPUT,record)
    print(json.dumps(dict(record=str(OUTPUT),status=record['status'],robot=state['robot'])))

if __name__=='__main__':main()
