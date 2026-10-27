"""Live-pose Home IK proposals; only a confirmed snapshot can execute."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time
from uuid import uuid4

from autonomy import TransferError, check_path, wrap
from imitation_agent import close_pose
from researcher_home import queued_station_stages, home_route_error
from researcher_teaching import TeachingError
from reviewed_home import ReviewedHomeConnection
from home_attempts import known_no_travel, UNCERTAIN_MESSAGE

ROOT=Path(__file__).resolve().parent


def ready_auto(state):
    return (state.get('enabled') is True and state.get('control_mode',{}).get('mode')=='auto'
            and state.get('program_state',{}).get('state')=='running')


def compare_snapshot(plan,state,cfg,envelope,target,ident):
    if cfg!=plan['cfg'] or envelope!=plan['envelope'] or target!=plan['home'] or ident!=plan['target_id']:
        raise TeachingError('Home or motion settings changed. Request a fresh Home plan.')
    for k in ('X','Y','Z','Rz'):
        delta=state['pose_mm'][k]-plan['start'][k]
        if k=='Rz':delta=wrap(delta)
        if not math.isfinite(delta) or abs(delta)>.05:
            raise TeachingError('The arm moved since the Home preview. Request Return Home again.')
    if any(not math.isfinite(state['joints'][k]) or abs(state['joints'][k]-plan['joints'][k])>.1 for k in ('J1','J2','J3','J4')):
        raise TeachingError('Arm configuration changed. Request a fresh Home plan.')
    e1=state.get('external_axes',{}).get('E1')
    if type(e1) not in (int,float) or not math.isfinite(e1) or abs(e1-plan['e1'])>.05:
        raise TeachingError('The claw changed since the Home preview. Request Return Home again.')
    if ready_auto(state)!=plan['preserve_gripper']:
        raise TeachingError('Controller readiness changed. Request a fresh Home plan.')


class IKHomeConnection:
    def __init__(self,home,folder=None):
        self.home=home
        self.folder=Path(folder) if folder else ROOT/'reports/ik_home'

    def history(self):
        records=[]
        for path in sorted(self.folder.glob('*.json')):
            record = None
            try:
                record=json.loads(path.read_text(encoding='utf-8'))
                seq=record.get('sequence') or {}
                complete=record.get('status')=='completed' and seq.get('state')=='done' and (seq.get('result') or {}).get('ok') is True
            except (OSError,ValueError,TypeError,AttributeError):complete=False
            if not complete and not known_no_travel(record):
                raise TeachingError(UNCERTAIN_MESSAGE)
            records.append(record)
        return records

    def propose(self):
        self.history()
        svc=self.home.get_service();run=self.home.get_runner();state=svc.status()
        if run.active or (getattr(run,'reserved',False) and not getattr(run,'owns_reservation',False)):
            raise TeachingError('Wait for the current action to finish.')
        if not state.get('connected') or not state.get('ok') or state.get('errors'):
            raise TeachingError('Resolve the robot alert or connection before returning Home.')
        if self.home.get_draggo().public(state).get('state')!='off':
            raise TeachingError('End human-guided teaching before planning Home.')
        if not svc.envelope_enabled:raise TeachingError('The travel workspace must be enabled.')
        if state.get('control_mode',{}).get('mode') not in ('manual','auto') or state.get('program_state',{}).get('state') not in ('stopped','running','paused'):
            raise TeachingError('Controller readiness is unavailable.')
        target,ident=self.home.target()
        start={k:state['pose_mm'][k] for k in ('X','Y','Z','Rz')}
        q=deepcopy(state['joints']);cfg=self.home.params()
        env={k:list(v) for k,v in svc.envelope.items()}
        if close_pose(start,target):raise TeachingError('The arm is already at Home.')
        e1=state.get('external_axes',{}).get('E1')
        if type(e1) not in (int,float) or not math.isfinite(e1):raise TeachingError('Claw feedback is unavailable.')
        try:
            stages=queued_station_stages(start,target,q,cfg,env)
            previous,joints=start,deepcopy(q);checked=[]
            for stage in stages:
                points=stage['points'] if stage['kind']=='queue' else [{**previous,'Rz':stage['rz']}]
                for point in points:
                    joints=check_path(previous,point,joints,cfg,env)
                    joints['J1']=q['J1']+point['Z']-start['Z']
                    if not 0<=joints['J1']<=400 or abs(joints['J3'])>180:
                        raise TransferError('Joint travel exceeds configured limits.')
                    checked.append(dict(pose=point,joints=deepcopy(joints)))
                    previous=point
        except TransferError as error:
            raise TeachingError(home_route_error(error,start,cfg,env)) from None
        preserve=ready_auto(state)
        requirements=['Confirm the lift, full wrist/arm/claw sweep, crossing and lowering shown below are clear; release the arm, keep hands clear and supervise the E-stop.']
        if preserve:
            requirements.append('Any held plate is secure and can lift clear of its support. The claw position will stay unchanged.')
        else:
            requirements.append('The gripper is empty. Auto preparation will enable the controller and start its program, which may close the jaws.')
        labels=[]
        for stage in stages:
            if stage['kind']=='rotate':labels.append('Turn the wrist to %.2f degrees at clearance height'%stage['rz'])
            else:
                for point in stage['points']:labels.append('Move to X%.2f / Y%.2f / Z%.2f mm'%(point['X'],point['Y'],point['Z']))
        return dict(actions=['move_home'],labels=['Return Home'],dispatch='ik_home_return',
            start=start,joints=q,e1=e1,cfg=cfg,envelope=env,home=target,target_id=ident,
            points_sha256=hashlib.sha256(self.home.path.read_bytes()).hexdigest(),
            stages=stages,checked=checked,preserve_gripper=preserve,
            steps=[dict(kind='home_return',label=label) for label in labels],requirements=requirements,
            summary='Return Home from the current position using IK. Translation speed 137; wrist speed 30. Review the physical route before confirming.')

    def start(self,plan):
        fresh=self.propose()
        state=self.home.get_service().status()
        compare_snapshot(plan,state,fresh['cfg'],fresh['envelope'],fresh['home'],fresh['target_id'])
        if fresh['points_sha256']!=plan['points_sha256'] or not ReviewedHomeConnection.same_stages(fresh['stages'],plan['stages']):
            raise TeachingError('Home path changed since preview. Request a new plan.')
        if any(record.get('plan_id')==plan['id'] for record in self.history()):
            raise TeachingError('That confirmation was already used. Request Return Home again.')
        self.folder.mkdir(parents=True,exist_ok=True)
        attempt=self.folder/(str(time.time_ns())+'_'+uuid4().hex+'.json')
        record=dict(status='confirmed',at=time.time(),plan_id=plan['id'],plan=deepcopy(plan),
            requirements_confirmed=plan['requirements'],physical_clearance_confirmed=True)
        with attempt.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2,allow_nan=False)
        dispatch_entered = False
        def before_dispatch():
            nonlocal dispatch_entered
            # Persist before invoking Runner.start. A crash/timeout after this
            # point is uncertain even if no completion was recorded.
            dispatch_entered = True
            record['dispatch_requested'] = True
            attempt.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
        try:
            result=self.home.start(dict(ready=True,target_id=plan['target_id']),
                                   approved_ik=plan,before_dispatch=before_dispatch)
            record.update(status='started',response=result)
        except Exception as error:
            record.update(status='failed_to_start',error=str(error))
            if not dispatch_entered:
                record['home_preflight_refusal'] = dict(schema=1,
                    reason='home_preflight_rejected', runner_start_called=False,
                    home_travel_dispatched=False, diagnostic=str(error))
            raise
        finally:attempt.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
        return result,attempt

    finish=ReviewedHomeConnection.finish
