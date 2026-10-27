"""One explicitly confirmed Home connection via the existing Flask controller owner."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parent


def api(path,body=None):
    request=Request('http://127.0.0.1:5002'+path,
                    data=None if body is None else json.dumps(body).encode(),
                    headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=30) as response:return json.load(response)


def execute(path,confirmed):
    if not confirmed:raise RuntimeError('Explicit operator confirmation required.')
    path=Path(path).resolve()
    folder=(ROOT/'reports/alignment_home').resolve()
    if path.parent!=folder:raise RuntimeError('Use a saved alignment/Home review.')
    raw=path.read_bytes();plan=json.loads(raw)
    if plan.get('schema')!='cephla.alignment-home-review.v1' or not plan.get('ik_and_limits_passed'):
        raise RuntimeError('Invalid route review.')
    output=path.with_name(path.stem+'_attempt.json')
    if output.exists():raise RuntimeError('Already attempted. Review the outcome; no automatic retry.')
    state=api('/state');robot=state['robot']
    if (state['sequence']['active'] or not robot.get('ok') or not robot.get('connected') or
        robot.get('errors') or not robot.get('enabled') or
        robot['control_mode']['mode']!='auto' or robot['program_state']['state']!='running'):
        raise RuntimeError('Require idle, healthy, already-running Auto; no reset or enable sent.')
    if api('/robot_params')!=plan['config']:
        raise RuntimeError('Robot parameters changed after review.')
    envelope={a:[state['envelope'][a]['min'],state['envelope'][a]['max']] for a in ('X','Y','Z')}
    if not state['envelope']['enabled'] or envelope!=plan['envelope']:
        raise RuntimeError('Workspace changed after review.')
    if hashlib.sha256((ROOT/'points.json').read_bytes()).hexdigest()!=plan['points_sha256']:
        raise RuntimeError('Saved Home changed after review.')
    for key in ('X','Y','Z','Rz'):
        if abs(robot['pose_mm'][key]-plan['start'][key])>.05:
            raise RuntimeError('Arm moved from the reviewed start.')
    for key in ('J1','J2','J3','J4'):
        if abs(robot['joints'][key]-plan['start_joints'][key])>.1:
            raise RuntimeError('Joint configuration changed after review.')
    if abs(robot['external_axes']['E1']-plan['observed_e1'])>.05:
        raise RuntimeError('Gripper position changed after review.')
    record=dict(status='authorized',started_at=time.time(),review_sha256=hashlib.sha256(raw).hexdigest(),
        review=str(path),authorization='Operator confirmed empty gripper, full sweep/path clear, arm released, E-stop supervised; run this Home return.',
        before=state,observations=[],gripper_commands=False)
    with output.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    def save():output.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
    sent=False
    try:
        sent=True
        result=api('/researcher/api/home/start',dict(ready=True,target_id=plan['target_id']))
        record['start_response']=result;save()
        if result.get('ok') is not True:raise RuntimeError(str(result))
        print('Home return started through the existing controller owner.',flush=True)
        deadline=time.monotonic()+180
        while True:
            snapshot=api('/state');seq=api('/seq')
            record['observations'].append(dict(at=time.time(),robot=snapshot['robot'],sequence=seq))
            save()
            if seq['name']!='researcher_home':raise RuntimeError('Another sequence replaced this Home return.')
            if not seq['active']:
                if seq['state']!='done' or (seq.get('result') or {}).get('ok') is not True:
                    raise RuntimeError(str(seq.get('result')))
                break
            if snapshot['robot'].get('errors') or not snapshot['robot'].get('ok'):
                raise RuntimeError('Robot fault or lost feedback during Home return.')
            if time.monotonic()>deadline:raise RuntimeError('Home return timed out; no retry.')
            time.sleep(.5)
        final=api('/state');robot=final['robot']
        for key in ('X','Y','Z','Rz'):
            if abs(robot['pose_mm'][key]-plan['home'][key])>.1:
                raise RuntimeError('Final Home position was not confirmed.')
        if robot.get('errors') or abs(robot['external_axes']['E1']-plan['observed_e1'])>.05:
            raise RuntimeError('Final state or unchanged gripper was not confirmed.')
        record.update(status='completed',finished_at=time.time(),final=final)
        save()
        print(json.dumps(dict(ok=True,pose=robot['pose_mm'],e1=robot['external_axes']['E1'],
                              duration_s=record['finished_at']-record['started_at'],record=str(output)),indent=2))
    except Exception as error:
        record.update(status='failed_or_uncertain',finished_at=time.time(),error=str(error))
        if sent:
            try:
                seq=api('/seq')
                if seq.get('active') and seq.get('name')=='researcher_home':
                    record['stop_response']=api('/researcher/api/home/stop',{})
            except Exception as stop_error:record['stop_error']=str(stop_error)
        save();raise


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('review')
    parser.add_argument('--operator-confirmed',action='store_true')
    args=parser.parse_args()
    execute(args.review,args.operator_confirmed)
