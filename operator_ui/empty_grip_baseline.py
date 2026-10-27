"""Developer-only empty-claw measurement; no force settings or arm moves.

Must start with open empty jaws and an already-running healthy controller.
Never starts/enables/resets it. Runner owns the whole sweep. Stop prevents the
next command; an empty-claw move already in progress can complete. Short mode
uses wider moves above 7 mm and 0.1 mm increments from 7 to 3.8 mm.
"""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
from uuid import uuid4

SPEED=5
FLOOR=3.8
TARGETS=tuple(round(n/10,1) for n in range(279,37,-1))
SHORT_TARGETS=(20.,12.,8.)+tuple(round(n/10,1) for n in range(70,37,-1))


def finite(value):
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError('Missing or nonfinite measurement')
    return float(value)


def run_empty_baseline(run,svc,folder,short=False,start_mm=28.):
    start_mm=finite(start_mm)
    if not FLOOR < start_mm <= 28 or abs(start_mm*10-round(start_mm*10))>1e-6:
        raise ValueError('Baseline start must be on the 0.1 mm grid above 3.8 mm.')
    if short and start_mm!=28.:
        raise ValueError('Sparse short mode must start open at 28 mm.')
    targets=(SHORT_TARGETS if short else TARGETS if start_mm==28. else
             tuple(n/10 for n in range(round(start_mm*10)-1,37,-1)))
    record=dict(schema=1,id=uuid4().hex,started_utc=datetime.now(timezone.utc).isoformat(),
                kind='empty_claw_baseline',operator_confirmed_empty=True,
                speed=SPEED,step_mm=None if short else .1,
                fine_step_mm=.1,fine_start_mm=7. if short else start_mm,
                sampling_mode=('sparse_wide_fine_contact_range' if short else
                               'full_range' if start_mm==28. else 'dense_local_range'),
                initial_opening_mm=start_mm,
                targets_mm=list(targets),floor_mm=FLOOR,force_limits_changed=False,
                grasp_verified=False,positions=[])
    folder=Path(folder);path=folder/(record['id']+'.json')
    initial=svc.pose_mm()
    record['start_pose_mm']=initial

    def save():
        folder.mkdir(parents=True,exist_ok=True)
        temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
        temp.replace(path)

    def check():
        if run.stopped():raise ValueError('Operator stopped the baseline')
        refusal=svc._preflight()
        if refusal:raise ValueError(refusal)
        pose=svc.pose_mm()
        for k in ('X','Y','Z','Rz'):
            d=finite(pose[k])-finite(initial[k])
            if k=='Rz':d=(d+180)%360-180
            if abs(d)>.05:raise ValueError('Arm moved during empty-claw measurement: '+k)

    def stationary(target):
        deadline=time.monotonic()+2
        while True:
            check()
            actual=finite(svc.external_axes()['E1'])
            if abs(actual-target)<=.05:return actual
            if time.monotonic()>=deadline:raise ValueError('Claw did not reach the empty-claw target; no retry')
            time.sleep(.1)

    def reports(target):
        samples=[]
        for _ in range(3):
            stationary(target)
            report=svc.torque_report(wait_timeout=3)
            if report.get('ok') is not True or report.get('telemetry_live') is not True or report.get('recovered'):
                raise ValueError('Fresh torque report failed: '+str(report.get('error','invalid report')))
            e1=finite(report.get('e1_position'));torque=finite(report.get('e1_torque'))
            if abs(e1-target)>.05:raise ValueError('Torque report position differs from target')
            samples.append(dict(at_utc=datetime.now(timezone.utc).isoformat(),e1_mm=e1,
                                raw_torque=torque,joint_torque=report.get('joints')))
            check()
        return samples

    try:
        check()
        if abs(finite(svc.external_axes()['E1'])-start_mm)>.02:
            raise ValueError(f'Empty claw must start at the reviewed {start_mm:.1f} mm opening')
        save()  # Logging failure prevents the first motion.
        record['positions'].append(dict(target_mm=start_mm,samples=reports(start_mm)))
        save()
        for index,target in enumerate(targets,1):
            check();previous=record['positions'][-1]['target_mm']
            if abs(finite(svc.external_axes()['E1'])-previous)>.05:
                raise ValueError('Claw moved outside the baseline sequence')
            record['pending_target_mm']=target;save()
            result=svc.move_gripper(target,speed=SPEED,wait_timeout=5)
            record['last_command_result']=result;save()
            if (result.get('ok') is not True or result.get('recovered')
                    or result.get('gripper_warning')):
                raise ValueError('Empty-claw increment was not confirmed; no retry')
            sample=dict(target_mm=target,completion=result,samples=reports(target))
            record['positions'].append(sample)
            record.pop('pending_target_mm',None);save()
            if index==1 or index%10==0 or index==len(targets):
                run.say(f'Empty claw: {target:.1f} mm; {index}/{len(targets)} positions recorded.')
        # Watch for delayed faults after the last step, without re-closing.
        record['final_observation']=[]
        for _ in range(5):
            time.sleep(1);stationary(FLOOR)
            record['final_observation'].extend(reports(FLOOR));save()
        record.update(ok=True,finished_utc=datetime.now(timezone.utc).isoformat());save()
        return dict(ok=True,record=str(path),positions=len(record['positions']),
                    final_e1_mm=svc.external_axes()['E1'],grasp_verified=False)
    except Exception as error:
        # No reset, reopen, retry or force-limit change. Stop the program if a
        # command/report is uncertain; keep the operator's error visible.
        try:record['stop_result']=svc.program('stop')
        except Exception as stop_error:record['stop_error']=str(stop_error)
        record.update(ok=False,error=str(error))
        try:save()
        except (OSError,ValueError,TypeError):pass
        run.state='stopped' if run.stopped() else 'error'
        run.say(str(error),'err')
        return dict(ok=False,error=str(error),record=str(path),grasp_verified=False)
