"""One operator-requested 10 mm vertical proof lift at speed 5; no grip/reset/retry."""
import argparse,json,time
from concurrent.futures import ThreadPoolExecutor
from proof_lift_plate import api,near,write
from projected_pickup import ROOT,load,sha
from autonomy import check_path

GRIP=ROOT/'operator_ui/demonstrations/reference_grip/6dccbc67cdd9499db239661788d41297.json'
RECEIPT=ROOT/'operator_ui/reports/projected_alignment/proof_lift_48well_10mm_20261027.json'

def ready(s):
    r=s['robot']
    if (not r.get('connected') or not r.get('ok') or r.get('errors') or not r.get('enabled')
            or r.get('control_mode',{}).get('mode')!='auto'
            or r.get('program_state',{}).get('state')!='running'
            or s['sequence']['active'] or not s['envelope']['enabled']):
        raise RuntimeError('Healthy idle Auto controller and enabled workspace required.')
    if not 3.65<=r['external_axes']['E1']<=3.75:
        raise RuntimeError('Claw setting changed; inspect before lifting.')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operator-confirmed',action='store_true');args=parser.parse_args()
    if not args.operator_confirmed:raise RuntimeError('Explicit operator request required.')
    if RECEIPT.exists():raise RuntimeError('This proof lift was already attempted; no replay.')
    profile,digest=load();grip=json.loads(GRIP.read_bytes())
    if not grip.get('ok') or grip['target_e1_mm']!=3.7:raise RuntimeError('Successful grip reference required.')
    if profile['descent_status']!='operator_accepted_open_claw_descent':raise RuntimeError('Accepted descent required.')
    state=api('state');ready(state);start=state['robot']['pose_mm']
    near(start,profile['candidate_endpoint'],.05);near(start,grip['pose_mm'],.05)
    if api('researcher/api/status')['hand_guiding']['state']!='off':raise RuntimeError('Hand-guiding must be off.')
    target={k:start[k] for k in ('X','Y','Z','Rz')};target['Z']+=10.
    env={k:(state['envelope'][k]['min'],state['envelope'][k]['max']) for k in ('X','Y','Z')}
    check_path(start,target,state['robot']['joints'],api('robot_params'),env)
    record=dict(at=time.time(),status='attempt_started',operator_request='Even jaw contact confirmed; try a 10 mm pickup to test grip strength.',
        grip_record=GRIP.relative_to(ROOT).as_posix(),grip_sha256=sha(GRIP.read_bytes()),
        profile_sha256=digest,start=start,target=target,speed=5,claw_target_unchanged_mm=3.7,
        grasp_verified=False,automatic_home=False,samples=[state])
    write(RECEIPT,record)
    command=dict(x=target['X'],y=target['Y'],z=target['Z'],rz=target['Rz'],speed=5,interpolation='linear')
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(api,'move',command)
            while not future.done():
                state=api('state');record['samples'].append(state)
                try:ready(state)
                except Exception:
                    record['stop_response']=api('program',{'action':'stop'});raise
                time.sleep(.2)
            response=future.result();record['response']=response
        if not response.get('ok') or response.get('recovered'):raise RuntimeError('Uncertain lift completion; no retry.')
        state=api('state');ready(state);near(state['robot']['pose_mm'],target,.1)
        record.update(status='lift_completed_awaiting_visual_inspection',final_state=state)
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        if 'stop_response' not in record:
            try:record['stop_response']=api('program',{'action':'stop'})
            except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        record['finished_at']=time.time();write(RECEIPT,record)
    print(json.dumps(dict(record=str(RECEIPT),status=record['status'],pose=state['robot']['pose_mm'],e1=state['robot']['external_axes']['E1'])))

if __name__=='__main__':main()
