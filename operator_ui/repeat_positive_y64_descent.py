"""Repeat accepted +Y pickup calibration/alignment/descent; no grip or startup."""
import json
import time
from uuid import uuid4
from test_squid_destination_empty import api
from scope_step_trial import near
from prepare_squid_destination import validate
from plate48_workflow import reference, match_placement
from projected_pickup import ROOT, PROFILE, sha

def main():
    profile,digest,raw=reference(require_grip=False)
    if profile.get('pickup_correction',{}).get('direction')!='positive_base_y':
        raise RuntimeError('Expected accepted +Y pickup')
    cfg=api('robot_params'); goal=profile['candidate_endpoint']; hover=profile['alignment_pose_mm']
    output=ROOT/'operator_ui/reports/projected_alignment'/('repeat_positive_y64_'+uuid4().hex+'.json')
    record=dict(status='running',profile_sha256=digest,endpoint=goal,events=[],grip_executed=False)
    def save():output.write_text(json.dumps(record,indent=2),encoding='utf-8')
    def healthy():
        s=api('state');r=s['robot']
        if not r.get('connected') or r.get('errors') or not r.get('enabled') or r['control_mode']['mode']!='auto' or r['program_state']['state']!='running':
            raise RuntimeError('Controller not ready; no recovery')
        if sha(PROFILE.read_bytes())!=digest or api('robot_params')!=cfg or not s['envelope']['enabled']:
            raise RuntimeError('Reviewed settings changed')
        return s
    def wait(name):
        deadline=time.monotonic()+240
        while True:
            healthy();seq=api('seq')
            if seq['name']!=name:raise RuntimeError('Sequence changed')
            if not seq['active']:
                record['events'].append(seq);save()
                if not (seq.get('result') or {}).get('ok'):raise RuntimeError(str(seq.get('result')))
                return seq['result']
            if time.monotonic()>deadline:raise RuntimeError('Sequence timed out')
            time.sleep(.5)
    save()
    try:
        calibration=wait('plate48_calibrate')
        api('seq/projected_alignment',dict(confirm=True,cell_clear=True,empty_gripper=True,
            expected_start=calibration['context']['pose'],expected_target=calibration['target']))
        aligned=wait('projected_alignment');match_placement(aligned['route']['target'],raw)
        state=healthy();r=state['robot'];env={k:[state['envelope'][k]['min'],state['envelope'][k]['max']] for k in ('X','Y','Z')}
        record['checked']=validate([r['pose_mm'],hover,goal],r['joints'],cfg,env);save()
        response=api('move',dict(x=hover['X'],y=hover['Y'],z=hover['Z'],rz=hover['Rz'],speed=5,interpolation='linear'))
        if response.get('recovered'):raise RuntimeError('Uncertain movement')
        near(healthy()['robot']['pose_mm'],hover,.05)
        api('seq/projected_descent_trial',dict(ready=True,empty_gripper=True,cell_clear=True,plate_unchanged=True,expected_profile_sha256=digest))
        print('Alignment complete; open-claw descent running.',flush=True)
        wait('researcher_descend');final=healthy()['robot'];near(final['pose_mm'],goal,.05)
        if not 27.98<=final['external_axes']['E1']<=28.05:raise RuntimeError('Claws not open')
        record.update(status='open_claw_repeat_complete',final_robot=final)
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        try:record['stop']=api('program',dict(action='stop'))
        except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        save();print(json.dumps(dict(status=record['status'],record=str(output))),flush=True)

if __name__=='__main__':main()
