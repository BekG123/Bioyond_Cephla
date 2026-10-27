"""One confirmed, counted plate loop. Models select recipes, never coordinates."""
from copy import copy,deepcopy
import json
from pathlib import Path
import threading
import time
from uuid import uuid4
from researcher_teaching import TeachingError
from scope_step_trial import near
from squid_execution import SquidExecution,digest
from squid_handling import plan as handling_plan
from autonomous_squid import AutonomousSquid

ROOT=Path(__file__).resolve().parent


def hamilton_acceptance():
    """Only recorded loaded-handling acceptance can replace inspection pauses."""
    from hamilton_handling import reference
    path=ROOT/'reports/hamilton/automatic_handling_acceptance.json'
    if not path.exists():
        raise TeachingError('Hamilton unattended loaded handling is not commissioned. Saved travel and completed supervised handoffs are separate evidence; use the supervised pickup/drop-off routines.')
    record=json.loads(path.read_text(encoding='utf-8-sig'))
    if record.get('status')!='operator_accepted' or record.get('handling_evidence')!=reference()[2]:
        raise TeachingError('Hamilton automatic handling acceptance is missing or out of date.')
    for action in ('hamilton_dropoff','hamilton_retrieve'):
        trial=record.get(action,{})
        path=(ROOT/trial.get('report','')).resolve()
        if not path.is_relative_to((ROOT/'reports').resolve()) or not path.is_file():
            raise TeachingError('Hamilton handling trial evidence is unavailable.')
        evidence=json.loads(path.read_text(encoding='utf-8-sig'))
        if trial.get('operator_accepted') is not True or evidence.get('ok') is not True:
            raise TeachingError('Hamilton loaded handling trial has not been accepted.')
    return digest(record)


def phases(count):
    if type(count) is not int or not 1<=count<=100:
        raise TeachingError('Choose 1 to 100 complete cycles.')
    rows=[dict(cycle=1,phase='hamilton_dropoff',label='Leave the plate at Hamilton and return Home')]
    for cycle in range(1,count+1):
        for phase,label in (
            ('dispense_start','Start Hamilton dispensing'),('dispense_wait','Wait at Home for this Hamilton job'),
            ('hamilton_retrieve','Retrieve from Hamilton and return Home'),
            ('stage_prepare','Prepare Squid loading position'),
            ('squid_dropoff','Leave the plate at Squid and return Home'),
            ('scan_entry','Move Squid into imaging area'),
            ('image_start','Start Squid imaging'),('image_wait','Wait at Home for imaging and stage cleanup'),
            ('stage_return','Return Squid stage to the accepted drop-off'),
            ('squid_retrieve','Retrieve from Squid and return Home'),
            ('hamilton_dropoff','Return the plate to Hamilton and park at Home')):
            rows.append(dict(cycle=cycle,phase=phase,label=f'Cycle {cycle}/{count}: {label}'))
    return rows


class LabRoundTrip:
    def __init__(self,agent,imaging=None,hamilton=None,acceptance=None,folder=None):
        self.agent,self.backend=agent,agent.backend
        self.imaging=imaging or SquidExecution(self.backend.squid)
        self.hamilton=hamilton or self.backend.instrument
        self.acceptance=acceptance or hamilton_acceptance
        self.folder=Path(folder or ROOT/'reports/lab_roundtrip')
        self.thread=None;self.cancel=threading.Event();self.running=False

    @property
    def active(self):
        return self.running or bool(self.thread and self.thread.is_alive())

    def history_blocker(self):
        for path in self.folder.glob('*/workflow.json'):
            try:record=json.loads(path.read_text(encoding='utf-8'))
            except (ValueError,OSError):return 'A lab round-trip record cannot be read. Review it before another run.'
            if record.get('status') in ('confirmed','running'):
                return 'A previous lab round trip has no recorded ending. Review its record before another run.'
        return ''

    def catalog(self):
        blockers=[]
        state=self.hamilton.status()
        if not state.get('available'):blockers.append(state['message'])
        if state.get('door_automation_ready') is False:
            blockers.append('Automatic Hamilton door access is not commissioned. A supported door actuator or Hamilton-approved robot access arrangement is required for unattended plate transfers.')
        try:self.acceptance()
        except Exception as error:blockers.append(str(error))
        if self.history_blocker():blockers.append(self.history_blocker())
        return dict(recipe='home_hamilton_squid_hamilton',confirmation='one_for_all_cycles',
            same_plate=True,final_plate='Hamilton',final_arm='Home',blockers=blockers,
            route='Home → Hamilton → Home → Squid → Home → Hamilton → Home',
            protocols=state.get('protocols',[]),automatic_retry=False)

    def projected(self,action):
        _,_,trials,_=self.backend.evidence();home,_=self.backend.home.target()
        view=copy(self.backend)
        predicted=dict(pose_mm=deepcopy(home),joints=deepcopy(trials['reverse']['final_robot']['joints']),
                       external_axes={'E1':3.7 if action.endswith('dropoff') else 5.})
        view.healthy=lambda *a,**kw:deepcopy(predicted)
        return handling_plan(view,action)

    def propose(self,repetitions=1,hamilton_protocol='',squid_protocol=None,pickup_from_calibration=False,hamilton_calibration=False):
        if type(hamilton_calibration) is not bool:raise TeachingError('Choose whether Hamilton calibration is included.')
        if type(pickup_from_calibration) is not bool:raise TeachingError('Choose where the plate starts.')
        rows=phases(repetitions)
        if hamilton_calibration:rows.insert(0,dict(cycle=0,phase='hamilton_calibration',label='Hamilton full calibration once: self-calibrate, calibrate channel height/squeeze'))
        with self.agent.lock:
            self.agent.pending=None
            if self.agent.review:raise TeachingError('Finish the current inspection first.')
        run=self.agent.get_runner()
        if run.active or run.reserved:raise TeachingError('Wait for the current workflow to finish.')
        blockers=self.catalog()['blockers'];prefix=None
        parts={}
        for key,fn in (
            ('hamilton',lambda:self.hamilton.prepare(hamilton_protocol,repetitions=repetitions,allow_uninitialized=hamilton_calibration)),
            ('imaging',lambda:self.imaging.prepare(squid_protocol,allow_loading_return=True)),
            ('acceptance',self.acceptance)):
            try:parts[key]=fn()
            except Exception as error:blockers.append(str(error))
        try:
            if pickup_from_calibration:
                prefix=self.agent.propose(['move_home','full_calibration'],source='roundtrip',_publish=False)
            else:
                robot=self.backend.healthy();home,_=self.backend.home.target()
                near(robot['pose_mm'],home,.2)
                if abs(robot['external_axes']['E1']-3.7)>.05:
                    raise TeachingError('Start with the plate securely held at Home, or request calibration pickup first.')
            parts['handling']={a:self.projected(a) for a in ('hamilton_dropoff','hamilton_retrieve','squid_dropoff','squid_retrieve')}
        except Exception as error:blockers.append(str(error))
        plan=dict(id=uuid4().hex,at=time.time(),dispatch='lab_roundtrip',actions=['lab_roundtrip'],
            repetitions=repetitions,hamilton_calibration=hamilton_calibration,plate_id='plate_'+uuid4().hex,parts=parts,prefix=prefix,
            executable=not blockers,blockers=list(dict.fromkeys(blockers)),phases=rows,
            labels=[f'Hamilton and Squid round trip × {repetitions}'],
            steps=(prefix['steps'] if prefix else [])+[dict(kind='lab_cycle',**row) for row in rows],
            summary=f'Deliver the plate to Hamilton once, then run {repetitions} complete cycle(s) with that same plate: dispense, retrieve via Home, image at Squid, and return the plate to Hamilton via Home. Finish with the arm at Home.',
            requirements=(list(prefix['requirements']) if prefix else ['The plate is securely held at Home.'])+[
                'Both station holders and all taught travel, loading and pickup paths are clear; supervise the E-stop.',
                'One Yes authorizes the entire listed run, including pickup and release at both stations and all requested cycles.',
                'Waits use exact instrument job completion. Failures or uncertain results stop the run without retry.',
                'Tips, reservoir volumes, waste capacity and plate contents cover all requested cycles.',
                'Stop prevents subsequent robot steps and requests abort for a Lacry-owned Hamilton operation. Check instrument status to confirm it stopped.'])
        if parts.get('imaging',{}).get('simulation'):
            plan['requirements'].append('Squid camera images are simulated in this session; the robot and configured XYZ stage are physical.')
        imaging_profile=parts.get('imaging',{}).get('profile',{})
        if imaging_profile.get('selection_source',{}).get('kind')=='saved_coordinates':
            plan['requirements'].append('Squid currently has no imaging site selected at loading. This run uses saved XY locations with live time-point, channel and Z settings. Confirm these locations and current settings for all cycles.')
        with self.agent.lock:self.agent.pending=plan
        self.agent._announce_plan(plan)
        return deepcopy(plan)

    def verify(self,plan):
        if not plan.get('executable'):raise TeachingError('Experiment blocked: '+' '.join(plan['blockers']))
        if self.history_blocker():raise TeachingError(self.history_blocker())
        if self.acceptance()!=plan['parts']['acceptance']:raise TeachingError('Hamilton handling acceptance changed.')
        self.hamilton.verify(plan['parts']['hamilton'],robot_access=True,allow_uninitialized=plan.get('hamilton_calibration',False))
        self.imaging.verify(plan['parts']['imaging'],check_position=False)
        for action,expected in plan['parts']['handling'].items():
            if digest(self.projected(action))!=digest(expected):raise TeachingError('A taught station route changed. Request a new plan.')

    def start(self,plan):
        self.verify(plan)
        for path in self.folder.glob('*/workflow.json'):
            if json.loads(path.read_text())['plan_id']==plan['id']:raise TeachingError('This confirmation was already used.')
        folder=self.folder/plan['id'];folder.mkdir(parents=True,exist_ok=False)
        record=dict(plan_id=plan['id'],plan=plan,status='confirmed',events=[],tickets={},plate_location='calibration_holder' if plan['prefix'] else 'gripper_at_Home')
        path=folder/'workflow.json'
        write=lambda:AutonomousSquid.write(path,record)
        write();self.cancel=threading.Event();self.running=True
        agent=self.agent;run=agent.get_runner();done=[]
        def save_ticket(kind,ticket):
            record['tickets'][kind]=deepcopy(ticket)
            record['events'].append(dict(at=time.time(),instrument=kind,ticket=deepcopy(ticket)))
            write()
        def check_stop():
            if self.cancel.is_set() or run.stopped():raise TeachingError('Workflow stopped. No subsequent step was started.')
        def home():
            state=self.backend.healthy();target,_=self.backend.home.target();near(state['pose_mm'],target,.2)
        def dispatch(row):
            check_stop();home()
            phase=row['phase'];parts=plan['parts'];handling=parts['handling'].get(phase)
            if self.acceptance()!=parts['acceptance']:raise TeachingError('Hamilton acceptance changed during the experiment.')
            if handling:
                if phase.startswith('hamilton'):self.hamilton.verify(parts['hamilton'],robot_access=True)
                else:self.imaging.verify(parts['imaging'],check_selection=False)
                if phase=='hamilton_retrieve':
                    self.hamilton.completed_for_pickup(parts['hamilton'],record['tickets']['hamilton'])
                if phase=='squid_retrieve':
                    observed=self.imaging.observe(parts['imaging'],record['tickets']['squid'],lambda t:save_ticket('squid',t))
                    if observed.get('completion_confirmed') is not True or record['tickets']['squid'].get('status')!='completed':
                        raise TeachingError('This Squid imaging job is no longer confirmed complete. Pickup blocked.')
                self.backend.verify_confirmation(handling,prepared=True)
            record['status']='running';record['phase']=row;record['events'].append(dict(at=time.time(),status='dispatch',**row));write()
            with agent.lock:agent.run_state.update(active=True,step=row['label'],done=list(done),message=row['label'])
            def execute(r):
                check_stop()
                if handling:
                    for step in handling['steps']:
                        check_stop()
                        if step['kind']=='hamilton_inspect':
                            if self.acceptance()!=parts['acceptance']:raise TeachingError('Automatic Hamilton handoff is not commissioned.')
                            r.audit('commissioned_hamilton_checkpoint',label=step['label'],acceptance=parts['acceptance'])
                            continue
                        result=self.backend.execute_step(r,step,handling)
                        if result.get('ok') is not True or result.get('review_required'):
                            raise TeachingError(step['label']+' did not verify automatic completion.')
                    home();record['plate_location']=phase.split('_')[0] if phase.endswith('dropoff') else 'gripper_at_Home'
                    return dict(ok=True)
                ticket=record['tickets']
                if phase=='hamilton_calibration':
                    return self.hamilton.run_action('full_calibration',r.stopped,lambda s:home())
                if phase=='stage_prepare':
                    return self.imaging.prepare_loading(parts['imaging'],r.stopped,home)
                if phase=='dispense_start':
                    if record['plate_location']!='hamilton':raise TeachingError('Plate delivery to Hamilton is not recorded.')
                    self.hamilton.start(parts['hamilton'],plan['plate_id'],lambda t:save_ticket('hamilton',t));return dict(ok=True)
                if phase=='dispense_wait':
                    return self.hamilton.wait(parts['hamilton'],ticket['hamilton'],lambda t:save_ticket('hamilton',t),r.stopped,lambda s:home())
                if phase=='image_start':
                    if record['plate_location']!='squid':raise TeachingError('Plate delivery to Squid is not recorded.')
                    cycle_folder=folder/str(row['cycle']);cycle_folder.mkdir(exist_ok=False)
                    self.imaging.start(parts['imaging'],cycle_folder,lambda t:save_ticket('squid',t),r.stopped);return dict(ok=True)
                if phase=='scan_entry':
                    return self.imaging.prepare_imaging(parts['imaging'],r.stopped,home)
                if phase=='image_wait':
                    return self.imaging.wait(parts['imaging'],ticket['squid'],lambda t:save_ticket('squid',t),r.stopped,lambda s:home())
                if phase=='stage_return':
                    return self.imaging.restore_loading(parts['imaging'],ticket['squid'],lambda t:save_ticket('squid',t),r.stopped,home)
                raise TeachingError('Unknown experiment phase.')
            return run.start('lacry_roundtrip_step',execute)
        def finished(final):
            if not final.get('ok') and record['tickets'].get('squid') and (self.cancel.is_set() or run.stopped()):
                try:self.imaging.abort_owned(plan['parts']['imaging'],record['tickets']['squid'],lambda t:save_ticket('squid',t))
                except Exception as error:final['message']+=' Squid cancellation uncertain: '+str(error)
            record.update(status='completed' if final.get('ok') else 'stopped_or_failed',result=final)
            try:write()
            finally:self.running=False
            with agent.lock:agent.run_state=deepcopy(final)
            agent._say('lacry',final['message'])
        message=f'Completed {plan["repetitions"]} cycle(s). The plate is at Hamilton and the arm is at Home.'
        with agent.lock:
            agent.pending=None;agent.run_meta=dict(name=plan['labels'][0],total_steps=len(plan['steps']),automatic=True)
            agent.run_state=dict(active=True,step='Starting',done=[],ok=None,error='',message='Starting the confirmed experiment.')
        if plan['prefix']:
            tails=[dict(label=row['label'],start=lambda row=row:dispatch(row),timeout_s=86460) for row in plan['phases']]
            try:
                return agent.classic.start(on_finish=finished,
                    home_prefix=agent._pickup_home_callbacks(plan['prefix']['home_prefix']) if plan['prefix'].get('home_prefix') else None,
                    tail_steps=tails,completion_message=message)
            except Exception as error:
                finished(dict(active=False,ok=False,done=[],error=str(error),message=str(error)));raise
        token=object()
        if not run.reserve(token,self.cancel):
            finished(dict(active=False,ok=False,done=[],error='busy',message='Another workflow owns the arm.'));raise TeachingError('Another workflow owns the arm.')
        def worker():
            try:
                run.claim(token)
                for row in plan['phases']:
                    result=dispatch(row)
                    if result.get('ok') is not True:raise TeachingError('Could not start '+row['label'])
                    run._thread.join(86460)
                    if run.active:run.request_stop();raise TeachingError('Timed out; in-progress command is uncertain.')
                    if run.stopped() or not (run.result or {}).get('ok'):raise TeachingError((run.result or {}).get('error','Stopped'))
                    done.append(row['label']);record['events'].append(dict(at=time.time(),status='completed',**row));write()
                finished(dict(active=False,ok=True,done=done,step=None,error='',message=message))
            except Exception as error:
                finished(dict(active=False,ok=False,done=done,step=record.get('phase',{}).get('label'),error=str(error),message='Stopped: '+str(error)))
            finally:run.release(token)
        self.thread=threading.Thread(target=worker,daemon=True);self.thread.start()
        return dict(ok=True,message='Complete experiment started. No further Yes is needed while steps succeed.')
