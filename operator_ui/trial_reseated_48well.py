"""One authorized adjusted open-claw trial. Never grip, lift, reset or retry."""
import argparse
from copy import deepcopy
import json
import math
import time
from projected_pickup import ROOT,PROFILE,load,sha,evidence
from correct_48well_centering import save
from proof_lift_plate import api,near,write
from autonomy import check_path,wrap
from pick_and_hold.Descend.lua_executor import make_plan
from sequences import band_floor

FOLDER=ROOT/'operator_ui/reports/projected_alignment'
PROPOSAL=FOLDER/'reseated_repeat1_adjustment_proposal_20261027.json'
PLAN=FOLDER/'reseated_repeat1_authorized_trial_20261027.json'
RECORD=FOLDER/'reseated_repeat1_open_claw_trial_20261027.json'


def healthy():
    state=api('state');r=state['robot']
    if (not r.get('connected') or not r.get('ok') or r.get('errors') or not r.get('enabled')
            or r.get('control_mode',{}).get('mode')!='auto'
            or r.get('program_state',{}).get('state')!='running'
            or state['sequence']['active'] or not state['envelope']['enabled']):
        raise RuntimeError('Healthy idle running Auto with workspace required; no recovery.')
    return state


def prepare():
    profile,digest=load();proposal=json.loads(PROPOSAL.read_bytes())
    if digest!=proposal['source_profile_sha256']:raise RuntimeError('Source pickup profile changed.')
    observed=json.loads(evidence(proposal['observation'],proposal['observation_sha256']).read_bytes())
    evidence(proposal['source_alignment_reference'],proposal['source_sha256'])
    state=healthy();seq=api('seq')
    if seq['name']!='projected_alignment' or seq['state']!='done' or not seq['result']['ok']:
        raise RuntimeError('Successful fresh projected alignment required.')
    actual=seq['result']['route']['target'];approved=observed['route']['target']
    if (math.hypot(actual['x']-approved['x'],actual['y']-approved['y'])>.5
            or abs(wrap(actual['rz']-approved['rz']))>.2):
        raise RuntimeError('Plate differs from the approved adjustment; no trial.')
    start=state['robot']['pose_mm'];near(start,dict(X=actual['x'],Y=actual['y'],Z=300,Rz=actual['rz']),.1)
    goal=proposal['proposed_endpoint'];hover=dict(goal,Z=300.)
    cfg=api('robot_params');env={k:(state['envelope'][k]['min'],state['envelope'][k]['max']) for k in ('X','Y','Z')}
    joints=check_path(start,hover,state['robot']['joints'],cfg,env)
    check_path(hover,goal,joints,cfg,env)
    target=dict(x=goal['X'],y=goal['Y'],rz=goal['Rz'],z_calibrated=goal['Z'])
    make_plan(hover,joints,target,cfg,env,band_floor())
    backup,backup_sha=save('profile_before_reseated_repeat1_trial_20261027.json',profile)
    approval,approval_sha=save('reseated_repeat1_trial_authorization_20261027.json',dict(
        at=time.time(),operator_feedback='Run adjusted open-claw trial; stop before grip',
        supervised_open_claw_trial_authorized=True,visual_alignment_accepted=False,
        alignment_pose_mm=hover,proposed_endpoint=goal,grip_authorized=False,
        proposal=PROPOSAL.relative_to(ROOT).as_posix(),proposal_sha256=sha(PROPOSAL.read_bytes()),
        fresh_alignment=seq['result']))
    candidate=deepcopy(profile)
    candidate.update(candidate_endpoint=goal,alignment_pose_mm=hover,
        descent_status='pending_supervised_open_claw_trial',acceptance=approval,acceptance_sha256=approval_sha,
        previous_profile=backup,previous_profile_sha256=backup_sha,
        physical_grip_validated_for_plate=False,full_pickup_verified=False,automatic_lift_enabled=False,
        alignment_source='Approved rigid plate-relative transform from fresh reseated-plate measurement',
        candidate_z_basis='Unchanged taught Z73.718; inspect open-claw placement before any grip.')
    for key in ('descent_acceptance','descent_acceptance_sha256','lateral_correction','lateral_correction_sha256'):
        candidate.pop(key,None)
    # Retain the accepted 3.9 reference. Its endpoint mismatch deliberately
    # blocks Grip until this new placement is inspected and linked to it.
    log=Path(seq['result']['log_file'])
    candidate.update(alignment_log=log.relative_to(ROOT).as_posix(),alignment_log_sha256=sha(log.read_bytes()))
    path,new_sha=save('reseated_repeat1_pending_profile_20261027.json',candidate)
    load(ROOT/path)
    plan=dict(at=time.time(),start=start,hover=hover,endpoint=goal,profile_path=path,profile_sha256=new_sha,
        previous_profile_sha256=digest,correction_speed=5,claw_open_mm=28,grip_authorized=False)
    with PLAN.open('x',encoding='utf-8') as stream:json.dump(plan,stream,indent=2)
    print(json.dumps(dict(plan=str(PLAN),start=start,hover=hover,endpoint=goal,motion_started=False)))


def execute():
    if RECORD.exists():raise RuntimeError('Trial consumed; no automatic retry.')
    plan=json.loads(PLAN.read_bytes());state=healthy();near(state['robot']['pose_mm'],plan['start'],.1)
    if load()[1]!=plan['previous_profile_sha256']:raise RuntimeError('Active profile changed.')
    source=evidence(plan['profile_path'],plan['profile_sha256']);load(source)
    if api('researcher/api/status')['hand_guiding']['state']!='off':raise RuntimeError('Hand-guiding active.')
    record=dict(at=time.time(),plan=plan,before=state,status='started',grip_executed=False,events=[])
    write(RECORD,record)
    try:
        hover=plan['hover'];cfg=api('robot_params')
        env={k:(state['envelope'][k]['min'],state['envelope'][k]['max']) for k in ('X','Y','Z')}
        check_path(state['robot']['pose_mm'],hover,state['robot']['joints'],cfg,env)
        record['correction_requested']=True;write(RECORD,record)
        response=api('move',dict(x=hover['X'],y=hover['Y'],z=300,rz=hover['Rz'],speed=5,interpolation='linear'))
        record['correction_response']=response;write(RECORD,record)
        if not response.get('ok') or response.get('recovered'):raise RuntimeError('Correction uncertain; no retry.')
        state=healthy();near(state['robot']['pose_mm'],hover,.1)
        temp=PROFILE.with_suffix('.tmp');temp.write_bytes(source.read_bytes());temp.replace(PROFILE)
        record['installed_profile_sha256']=load()[1];write(RECORD,record)
        result=api('seq/projected_descent_trial',dict(ready=True,empty_gripper=True,cell_clear=True,
            plate_unchanged=True,expected_profile_sha256=plan['profile_sha256']))
        record['descent_start']=result;write(RECORD,record)
        if not result.get('ok'):raise RuntimeError(str(result))
        deadline=time.monotonic()+180
        while True:
            seq=api('seq');state=api('state')
            record['events'].append(dict(at=time.time(),sequence_state=seq['state'],robot=state['robot']))
            if seq['name']!='researcher_descend':raise RuntimeError('Sequence owner changed.')
            if not seq['active']:break
            if time.monotonic()>deadline:raise RuntimeError('Descent timed out; stop and inspect.')
            time.sleep(.5)
        record['descent_result']=seq
        if not seq.get('result',{}).get('ok'):raise RuntimeError(str(seq.get('result')))
        state=healthy();near(state['robot']['pose_mm'],plan['endpoint'],.1)
        if not 27.98<=state['robot']['external_axes']['E1']<=28.05:raise RuntimeError('Open jaws not verified.')
        record.update(status='open_claw_descent_complete_awaiting_inspection',final_state=state)
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        try:record['stop_response']=api('seq/stop',{})
        except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:write(RECORD,record)
    print(json.dumps(dict(record=str(RECORD),status=record['status'],pose=state['robot']['pose_mm'],e1=state['robot']['external_axes']['E1'])))


if __name__=='__main__':
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-confirmed',action='store_true');args=parser.parse_args()
    execute() if args.execute_confirmed else prepare()
