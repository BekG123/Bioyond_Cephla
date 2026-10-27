"""One supervised candidate trial through Flask; restore baseline after trial."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from autonomy import wrap
from execute_alignment_home import api
from pick_and_hold.Descend.correction import PROFILE, corrected_plan

ROOT=Path(__file__).resolve().parents[1]


def validate_start(review,state,cfg,band):
    robot=state['robot']
    if (state['sequence']['active'] or not robot.get('ok') or not robot.get('connected')
            or robot.get('errors') or not robot.get('enabled')
            or robot['control_mode']['mode']!='auto' or robot['program_state']['state']!='running'):
        raise RuntimeError('Require healthy idle already-running Auto; no reset/enable allowed.')
    if cfg!=review['config'] or band!=review['band']:
        raise RuntimeError('Configuration changed after review.')
    if state['envelope']!=review['state']['envelope'] or not state['envelope']['enabled']:
        raise RuntimeError('Workspace changed after review.')
    if state['target']!=review['state']['target']:
        raise RuntimeError('Vision target changed; prepare a new candidate.')
    for k in ('X','Y','Z','Rz'):
        delta=robot['pose_mm'][k]-review['state']['robot']['pose_mm'][k]
        if k=='Rz':delta=wrap(delta)
        if abs(delta)>.05:raise RuntimeError('Arm moved from the reviewed start.')
    for k in ('J1','J2','J3','J4'):
        if abs(robot['joints'][k]-review['state']['robot']['joints'][k])>.1:
            raise RuntimeError('Joint configuration changed after review.')
    if abs(robot['external_axes']['E1']-review['state']['robot']['external_axes']['E1'])>.05:
        raise RuntimeError('Claw position changed after review.')


def replace_profile(raw):
    temporary=PROFILE.with_suffix('.trial-tmp')
    temporary.write_bytes(raw)
    os.replace(temporary,PROFILE)


def validate_completed_alignment(seq,review):
    if (seq.get('active') or seq.get('name') not in ('align','researcher_align')
            or seq.get('state')!='done' or (seq.get('result') or {}).get('ok') is not True
            or seq.get('target')!=review['state']['target']):
        raise RuntimeError('A completed matching Align is required; no manufactured receipt.')


def execute(path,confirmed,use_completed_alignment=False):
    if not confirmed:raise RuntimeError('Physical trial confirmation required.')
    path=Path(path).resolve()
    if path.parent.parent!=(ROOT/'operator_ui/reports/descent_trials').resolve():
        raise RuntimeError('Use a saved descent trial review.')
    raw=path.read_bytes();review=json.loads(raw)
    if review.get('schema')!='cephla.adapted-descent-review.v1' or not review.get('ik_and_limits_passed'):
        raise RuntimeError('Invalid review.')
    output=path.with_name('trial_attempt.json')
    if output.exists():raise RuntimeError('Already attempted; no automatic retry.')
    candidate_path=(ROOT/review['candidate_profile']).resolve()
    if candidate_path.parent!=path.parent:raise RuntimeError('Candidate outside review folder.')
    candidate_raw=candidate_path.read_bytes()
    if hashlib.sha256(candidate_raw).hexdigest()!=review['candidate_sha256']:
        raise RuntimeError('Candidate changed.')
    evidence=json.loads((path.parent/'evidence.json').read_bytes())
    original=PROFILE.read_bytes()
    if hashlib.sha256(original).hexdigest()!=evidence['parent_profile_sha256']:
        raise RuntimeError('Active baseline changed.')
    state=api('/state');cfg=api('/robot_params');band=api('/torque_threshold')['band_counts']
    validate_start(review,state,cfg,band)
    if api('/researcher/api/status')['hand_guiding']['state']!='off':
        raise RuntimeError('Hand-guiding must be off.')
    plan=corrected_plan(state['robot']['pose_mm'],state['robot']['joints'],state['target'],
        cfg,review['envelope'],band,profile_path=candidate_path)
    if plan['endpoint']!=review['plan']['endpoint']:
        raise RuntimeError('Candidate endpoint changed.')
    record=dict(schema='cephla.adapted-descent-trial.v1',status='authorized',started_at=time.time(),
        review_sha256=hashlib.sha256(raw).hexdigest(),review=str(path),
        authorization='Operator confirmed same supporting surface, empty gripper, clear correction/descent, arm released, hands clear and supervised E-stop; run supervised trial.',
        before=state,observations=[],operator_visual_acceptance=None,grip_requested=False)
    with output.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    def save():output.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
    current=None;installed=False
    def wait_for(name,timeout):
        deadline=time.monotonic()+timeout;last=None
        while True:
            snapshot=api('/state');seq=api('/seq')
            record['observations'].append(dict(at=time.time(),robot=snapshot['robot'],sequence=seq));save()
            if seq['name']!=name:raise RuntimeError('Another sequence replaced the trial.')
            if seq.get('log'):
                msg=seq['log'][-1]['msg']
                if msg!=last:print(msg,flush=True);last=msg
            if not seq['active']:
                if seq['state']!='done' or (seq.get('result') or {}).get('ok') is not True:
                    raise RuntimeError(str(seq.get('result')))
                return seq
            if snapshot['robot'].get('errors') or not snapshot['robot'].get('ok'):
                raise RuntimeError('Controller fault or feedback unavailable.')
            if time.monotonic()>deadline:raise RuntimeError('Trial timed out; no retry.')
            time.sleep(.2)
    try:
        if use_completed_alignment:
            # The existing researcher Align validates hover separately from the
            # raw vision height. The corrected taught depth is checked above.
            # ResearcherDescent still enforces its own 600-second freshness.
            aligned=api('/seq')
            validate_completed_alignment(aligned,review)
            record['completed_alignment']=aligned
            save()
        else:
            # Real alignment recheck at the same raw target; no fabricated freshness.
            current='align'
            reply=api('/seq/align',dict(hover_z=300))
            record['alignment_start']=reply;save()
            if reply.get('ok') is not True:raise RuntimeError(str(reply))
            wait_for('align',30)
        validate_start(review,api('/state'),api('/robot_params'),api('/torque_threshold')['band_counts'])
        if PROFILE.read_bytes()!=original:raise RuntimeError('Baseline changed during alignment.')
        (path.parent/'original_profile_bytes.json').write_bytes(original)
        replace_profile(candidate_raw);installed=True
        current='researcher_descend'
        reply=api('/researcher/api/descent/start',dict(ready=True))
        record['descent_start']=reply;save()
        if reply.get('ok') is not True:raise RuntimeError(str(reply))
        print('Adapted descent started; no grip will be requested.',flush=True)
        final_seq=wait_for(current,180)
        final=api('/state');robot=final['robot']
        if robot.get('errors') or not robot.get('ok'):raise RuntimeError('Final robot state is unhealthy.')
        for k,value in plan['endpoint'].items():
            delta=robot['pose_mm'][k]-value
            if k=='Rz':delta=wrap(delta)
            if abs(delta)>.1:raise RuntimeError('Final endpoint not confirmed.')
        if not 27.95<=robot['external_axes']['E1']<=28.1:
            raise RuntimeError('Final open-claw position not confirmed.')
        record.update(status='completed_awaiting_visual_inspection',finished_at=time.time(),
            final=final,result=final_seq['result'])
        save()
    except Exception as error:
        record.update(status='failed_or_uncertain',error=str(error),finished_at=time.time())
        try:
            seq=api('/seq')
            if seq.get('active') and seq.get('name')==current:
                record['stop_response']=api('/seq/stop',{})
                deadline=time.monotonic()+15
                while api('/seq')['active'] and time.monotonic()<deadline:time.sleep(.2)
        except Exception as stop_error:record['stop_error']=str(stop_error)
        save();raise
    finally:
        if installed:
            try:
                if not api('/seq')['active'] and PROFILE.read_bytes()==candidate_raw:
                    replace_profile(original);record['baseline_restored']=True
                else:record['baseline_restored']=False
            except Exception as restore_error:record['restore_error']=str(restore_error)
            save()
    print(json.dumps(dict(status=record['status'],pose=record['final']['robot']['pose_mm'],
        open_e1=record['final']['robot']['external_axes']['E1'],
        duration_s=record['finished_at']-record['started_at'],record=str(output),
        baseline_restored=record.get('baseline_restored')),indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('review')
    parser.add_argument('--operator-confirmed',action='store_true')
    parser.add_argument('--use-completed-alignment',action='store_true')
    args=parser.parse_args()
    execute(args.review,args.operator_confirmed,args.use_completed_alignment)
