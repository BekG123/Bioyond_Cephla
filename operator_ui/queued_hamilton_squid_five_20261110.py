"""Five explicitly authorized closed-claw round trips, starting at Hamilton."""
import argparse
from copy import deepcopy
import json
import sys
import time
import hamilton_squid_full_repeat03_20261109 as h
import execute_continuous_squid_return_20261103 as travel
from squid_handling_route import CURRENT_SOURCE,CURRENT_SHA,load_route
from squid_single_queue import check_route
from proof_lift_plate import api,near,write
from capture_squid_approach_20261103 import sha

OUT=travel.FOLDER/'queued_hamilton_squid_five_20261110'
INITIAL='queue_five_initial_20261110'
AUTH=('Operator confirmed plate level and seated after the calibrated loaded Squid transfer, '
      'requested Squid -> Home -> Hamilton, then explicitly selected five Hamilton -> Home -> '
      'Squid -> Home -> Hamilton round trips keeping the plate gripped throughout. '
      'Standing clear routes, hands clear and E-stop supervision apply. No jaw commands or retries.')

def ready():
    s=api('state');r=s['robot']
    if (not r.get('connected') or not r.get('ok') or r.get('errors') or not r.get('enabled')
        or r['control_mode']['mode']!='auto' or r['program_state']['state']!='running'
        or s['sequence']['active'] or not s['envelope']['enabled']):
        raise RuntimeError('Idle healthy Auto required; no recovery')
    if abs(r['external_axes']['E1']-3.9)>.15:raise RuntimeError('Grip changed')
    if api('researcher/api/status')['hand_guiding']['state']!='off':raise RuntimeError('Hand-guiding active')
    if api('researcher/api/lacry/state')['running']['active']:raise RuntimeError('Other workflow active')
    return s

def squid(direction,folder,plan):
    p=deepcopy(plan);route=p['routes']['from_capture']
    p.update(routes={'from_capture':route[:5] if direction=='forward' else route[4:]},
        leg_speeds=[137,137,137,5] if direction=='forward' else [5,137,137,137],
        completion_status='closed_claw_'+direction+'_completed_pending_operator_assessment',operator_intent=AUTH)
    travel.PLAN=folder/('squid_'+direction+'_plan.json');write(travel.PLAN,p)
    travel.SHA=sha(travel.PLAN);travel.OUTPUT=folder/('squid_'+direction+'_trial.json')
    old=sys.argv[:]
    try:
        sys.argv=[__file__,'--execute']
        travel.main(tuple(p['leg_speeds']),(0,3),single_queue=True)
    finally:sys.argv=old

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    if OUT.exists():raise RuntimeError('Batch already attempted; preserve its evidence')
    s=api('state')
    if not s['robot'].get('connected'):
        if s['sequence']['active']:raise RuntimeError('Active disconnected sequence')
        if not api('connect',{'ip':'192.168.201.220'}).get('ok'):raise RuntimeError('Connect failed')
    s=ready();r=s['robot'];cfg=api('robot_params');hp=h.hamilton.reference();sp=load_route(CURRENT_SOURCE,CURRENT_SHA)
    env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
    near(r['pose_mm'],hp['routes']['reverse'][0],.05)
    prior=json.loads(h.hamilton.output_path(False,INITIAL).read_bytes())
    if prior['status']!='completed' or not prior['result']['ok'] or prior['plan']['candidate_sha256']!=h.hamilton.SHA:
        raise RuntimeError('Initial Hamilton arrival unverified')
    q=h.hamilton.check_route(r['pose_mm'],hp['routes']['reverse'][1:],r['joints'],cfg,env)
    h.hamilton.check_route(hp['routes']['forward'][0],hp['routes']['forward'][1:],q,cfg,env)
    path=sp['routes']['from_capture'];end=check_route(path[0],path[1:5],q,cfg,env)
    check_route(path[4],path[5:],end,cfg,env);h.hamilton_idle()
    print(json.dumps(dict(validated=True,cycles=5,keep_gripped=True,execute=args.execute)),flush=True)
    if not args.execute:return
    OUT.mkdir()
    record=dict(status='running',at=time.time(),authorization=AUTH,completed_cycles=0,events=[],initial_state=s,
        initial_hamilton_receipt=str(h.hamilton.output_path(False,INITIAL)),automatic_retries=False,gripper_commands=[])
    def phase(cycle,name):
        record['events'].append(dict(cycle=cycle,phase=name,at=time.time()));record.update(cycle=cycle,phase=name)
        write(OUT/'run.json',record);print(json.dumps(dict(cycle=cycle,phase=name)),flush=True)
    previous=INITIAL
    try:
        for cycle in range(1,6):
            ready();folder=OUT/('cycle_'+str(cycle));folder.mkdir()
            h.OUT=folder;h.TRIAL='queue_five_c'+str(cycle)+'_20261110'
            phase(cycle,'Hamilton_to_Home');write(folder/'home.json',h.travel_hamilton('reverse',previous))
            phase(cycle,'Home_to_Squid');squid('forward',folder,sp)
            phase(cycle,'Squid_to_Home');squid('reverse',folder,sp)
            phase(cycle,'Home_to_Hamilton');result=h.travel_hamilton('forward');write(folder/'hamilton.json',result)
            previous=h.TRIAL;record['completed_cycles']=cycle;record['final_robot']=result['robot']
            phase(cycle,'completed')
        record['status']='completed_pending_operator_assessment'
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        try:record['stop_response']=api('program',dict(action='stop'))
        except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        record['finished_at']=time.time();write(OUT/'run.json',record)
        print(json.dumps(dict(status=record['status'],completed_cycles=record['completed_cycles'],report=str(OUT/'run.json'))),flush=True)

if __name__=='__main__':main()
