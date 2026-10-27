"""Authorized empty-jaw sweep at the accepted centered pose, followed by opening."""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from review_grip_centering_retreat import api
from pick_and_hold.Descend.correction import PROFILE


def main():
    if sys.argv[1:] != ['--empty-confirmed']:
        raise RuntimeError('Explicit plate-removed, hands-clear and E-stop confirmation required.')
    root=Path(__file__).parent
    folder=root/'reports/grip_centering'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True,exist_ok=False)
    output=folder/'empty_baseline_trial.json'
    record=dict(started_at=time.time(),status='preflight',observations=[],
                authorization='Operator confirmed plate removed, hands clear, E-stop supervised; record empty baseline then reopen.',
                plate_present=False,arm_travel_requested=False,lift_requested=False)
    goal=json.loads(PROFILE.read_bytes())['endpoint']

    def save():
        output.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')

    def healthy():
        state=api('/state');robot=state['robot']
        if (not robot.get('ok') or not robot.get('connected') or robot.get('errors')
                or not robot.get('enabled') or robot['control_mode']['mode']!='auto'
                or robot['program_state']['state']!='running'):
            raise RuntimeError('Healthy already-running Auto required; no reset or enable.')
        if any(abs(robot['pose_mm'][k]-v)>.05 for k,v in goal.items()):
            raise RuntimeError('Arm moved from the accepted centered pose.')
        return state

    sent=False
    try:
        state=healthy()
        if state['sequence']['active'] or api('/researcher/api/status')['hand_guiding']['state']!='off':
            raise RuntimeError('Require idle arm with hand-guiding off.')
        if abs(state['robot']['external_axes']['E1']-28)>.02:
            raise RuntimeError('Expected initially open jaws at 28 mm.')
        record['before']=state
        record['request']=dict(empty=True,ready=True)
        save()
        sent=True
        reply=api('/developer/api/grip/empty-baseline',record['request'])
        record['start_response']=reply;save()
        if reply.get('ok') is not True:
            raise RuntimeError(str(reply))
        deadline=time.monotonic()+900
        previous=None
        while True:
            state=healthy();seq=api('/seq')
            record['observations'].append(dict(at=time.time(),state=state,sequence=seq));save()
            if seq['name']!='empty_grip_baseline':
                raise RuntimeError('Another sequence replaced the baseline.')
            if seq.get('log'):
                message=seq['log'][-1]['msg']
                if message!=previous:print(message,flush=True);previous=message
            if not seq['active']:
                if seq['state']!='done' or (seq.get('result') or {}).get('ok') is not True:
                    raise RuntimeError(str(seq.get('result')))
                break
            if time.monotonic()>deadline:
                raise RuntimeError('Baseline observation timeout; no retry.')
            time.sleep(2)
        result=seq['result']
        baseline_path=Path(result['record']).resolve()
        if baseline_path.parent!=(root/'demonstrations/empty_grip_baseline').resolve():
            raise RuntimeError('Unexpected baseline output location.')
        baseline=json.loads(baseline_path.read_bytes())
        targets=[row['target_mm'] for row in baseline['positions']]
        expected=[n/10 for n in range(280,37,-1)]
        if (baseline.get('ok') is not True or baseline.get('operator_confirmed_empty') is not True
                or baseline.get('kind')!='empty_claw_baseline' or targets!=expected):
            raise RuntimeError('Completed dense empty baseline could not be verified.')
        record.update(baseline=str(baseline_path),baseline_result=result,
                      baseline_completed_at=time.time(),before_reopen=healthy(),
                      reopen_request=dict(action='move',e1=28,speed=5))
        save()
        print('Dense empty baseline complete. Reopening the empty jaws to 28 mm.',flush=True)
        opened=api('/gripper',record['reopen_request'])
        record['reopen_response']=opened;save()
        if opened.get('ok') is not True or opened.get('recovered') or opened.get('gripper_warning'):
            raise RuntimeError('Reopening not confirmed; no retry.')
        final=healthy()
        if abs(final['robot']['external_axes']['E1']-28)>.05:
            raise RuntimeError('Final 28 mm opening not confirmed.')
        record.update(status='completed',finished_at=time.time(),after=final)
        save()
        print(json.dumps(dict(record=str(output),baseline=str(baseline_path),
                              positions=len(targets),samples=sum(len(p['samples']) for p in baseline['positions'])+len(baseline['final_observation']),
                              duration_s=record['baseline_completed_at']-record['started_at'],
                              final_pose=final['robot']['pose_mm'],e1=final['robot']['external_axes']['E1']),indent=2))
    except Exception as error:
        record.update(status='failed_or_uncertain',error=str(error),finished_at=time.time())
        if sent:
            try:
                seq=api('/seq')
                if seq.get('active') and seq.get('name')=='empty_grip_baseline':
                    record['stop_response']=api('/seq/stop',{})
            except Exception as stop_error:
                record['stop_error']=str(stop_error)
        save()
        raise


if __name__=='__main__':
    main()
