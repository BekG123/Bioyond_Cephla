"""Repeat accepted pickup geometry without replacing its human acceptance."""
import argparse
import json
import time
from uuid import uuid4
import projected_pickup as p
from plate48_workflow import reference, match_placement
from prepare_squid_destination import validate
from scope_step_trial import near
from test_squid_destination_empty import api

SHA='446d252761215951c2e6ddbc46275998e129f21a9ed1b7333b99b7947954edf2'


def verify_repeat(receipt, profile, digest, sequence):
    if (digest!=SHA or receipt.get('status')!='accepted_geometry_repeat_descent_complete'
            or receipt.get('profile_sha256')!=digest
            or receipt.get('endpoint')!=profile['candidate_endpoint']
            or receipt.get('prior_descent_acceptance')!=profile['descent_acceptance']
            or receipt.get('prior_descent_acceptance_sha256')!=profile['descent_acceptance_sha256']
            or not 0<=time.time()-receipt.get('finished_at',0)<=600
            or sequence.get('active') or sequence.get('name')!='researcher_descend'
            or sequence.get('result')!=receipt.get('descent_result')
            or not receipt.get('descent_result',{}).get('ok')):
        raise RuntimeError('Fresh matching accepted-geometry repeat required')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    profile,digest,raw=reference(require_grip=False)
    if digest!=SHA or profile['pickup_correction']['distance_mm']!=10.4:
        raise RuntimeError('Accepted profile changed')
    if not args.execute:
        print(json.dumps(dict(profile_sha256=digest,endpoint=profile['candidate_endpoint'])));return
    folder=p.ROOT/'operator_ui/reports/projected_alignment'/('accepted_y104_repeat_'+uuid4().hex)
    folder.mkdir()
    record=dict(status='started',at=time.time(),profile_sha256=digest,
        endpoint=profile['candidate_endpoint'],prior_descent_acceptance=profile['descent_acceptance'],
        prior_descent_acceptance_sha256=profile['descent_acceptance_sha256'],
        authorization='Operator requested full calibration repeat, confirmed empty claws, plate in holder and clear route; no routine visual pause.',
        new_visual_acceptance_claimed=False,events=[])
    def save():
        (folder/'attempt.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    def healthy():
        s=api('state');r=s['robot']
        if not r.get('connected') or r.get('errors') or not r.get('enabled') or r['program_state']['state']!='running' or r['control_mode']['mode']!='auto' or not s['envelope']['enabled']:
            raise RuntimeError('Controller not ready; no restart')
        if p.sha(p.PROFILE.read_bytes())!=digest:raise RuntimeError('Profile changed')
        return s
    def wait(name):
        deadline=time.monotonic()+240
        while True:
            seq=api('seq');healthy()
            if seq['name']!=name:raise RuntimeError('Sequence owner changed')
            if not seq['active']:
                record['events'].append(dict(sequence=seq));save()
                if not (seq.get('result') or {}).get('ok'):raise RuntimeError(str(seq.get('result')))
                return seq['result']
            if time.monotonic()>deadline:raise RuntimeError('Sequence timed out')
            time.sleep(.5)
    save()
    try:
        cal=wait('plate48_calibrate')
        near(healthy()['robot']['pose_mm'],cal['context']['pose'],.05)
        api('seq/projected_alignment',dict(confirm=True,cell_clear=True,empty_gripper=True,
            expected_start=cal['context']['pose'],expected_target=cal['target']))
        aligned=wait('projected_alignment');match_placement(aligned['route']['target'],raw)
        state=healthy();hover=profile['alignment_pose_mm'];goal=profile['candidate_endpoint']
        env={k:[state['envelope'][k]['min'],state['envelope'][k]['max']] for k in ('X','Y','Z')}
        record['validation']=validate([state['robot']['pose_mm'],hover,goal],state['robot']['joints'],api('robot_params'),env);save()
        result=api('move',dict(x=hover['X'],y=hover['Y'],z=hover['Z'],rz=hover['Rz'],speed=5,interpolation='linear'))
        if result.get('recovered'):raise RuntimeError('Uncertain hover arrival')
        near(healthy()['robot']['pose_mm'],hover,.05)
        opened=api('gripper',dict(action='move',e1=28,speed=5))
        if opened.get('recovered') or opened.get('gripper_warning'):raise RuntimeError('Uncertain opening')
        if not 27.98<=healthy()['robot']['external_axes']['E1']<=28.05:raise RuntimeError('Claws not open')
        api('seq/projected_descent_trial',dict(ready=True,empty_gripper=True,cell_clear=True,plate_unchanged=True,expected_profile_sha256=digest))
        result=wait('researcher_descend')
        state=healthy();near(state['robot']['pose_mm'],goal,.05)
        if not 27.98<=state['robot']['external_axes']['E1']<=28.05:raise RuntimeError('Claws changed')
        record.update(status='accepted_geometry_repeat_descent_complete',descent_result=result,final_state=state)
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        try:record['stop']=api('program',dict(action='stop'))
        except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        record['finished_at']=time.time();save()
        print(json.dumps(dict(receipt=str(folder/'attempt.json'),status=record['status'])),flush=True)


if __name__=='__main__':main()
