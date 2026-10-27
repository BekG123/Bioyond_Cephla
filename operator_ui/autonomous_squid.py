"""One confirmation: existing pickup, Squid delivery, exact-job imaging, retrieval."""
from copy import copy, deepcopy
import json
from pathlib import Path
import time
from uuid import uuid4

from researcher_teaching import TeachingError
from scope_step_trial import near
from squid_handling import plan as handling_plan
from squid_execution import SquidExecution, digest

ROOT = Path(__file__).resolve().parent
MAX_REPETITIONS = 1000


def repetitions_count(value):
    if type(value) is not int or not 1 <= value <= MAX_REPETITIONS:
        raise TeachingError(f'Choose a whole-number repetition count from 1 to {MAX_REPETITIONS}.')
    return value


class AutonomousSquid:
    def __init__(self, agent, instrument=None, folder=None):
        self.agent, self.backend = agent, agent.backend
        self.instrument = instrument or SquidExecution(self.backend.squid)
        self.folder = Path(folder or ROOT/'reports/autonomous_squid')
        self.active_record = None

    def history_blocker(self):
        for path in self.folder.glob('*/workflow.json'):
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
            except (ValueError,OSError):
                return 'An experiment record is unreadable. Developer review is needed before another automatic experiment.'
            if record.get('status') in ('confirmed','running','interrupted'):
                return 'A previous automatic experiment has no recorded ending. Review its log before starting another; it will not resume automatically.'
        return ''

    def catalog(self):
        try:
            return dict(**self.instrument.profiles(), blocker=self.history_blocker(),
                        confirmation='one_for_all_cycles', automatic_retry=False,
                        repetitions_supported=True,max_repetitions=MAX_REPETITIONS)
        except Exception as error:
            return dict(profiles=[], default=None, blocker=str(error))

    def projected_handling(self, action):
        """Compile at recorded Home; execution rechecks all actual feedback."""
        _,_,trials,_ = self.backend.evidence()
        home,_ = self.backend.home.target()
        predicted = dict(pose_mm=deepcopy(home),
                         joints=deepcopy(trials['reverse']['final_robot']['joints']),
                         external_axes={'E1':3.7 if action=='squid_dropoff' else 5.})
        view = copy(self.backend)
        view.healthy = lambda *a,**kw: deepcopy(predicted)
        return handling_plan(view, action)

    def propose(self, protocol=None, retrieve=True, pickup_from_calibration=True, repetitions=1):
        # An invalid replacement request must not leave an older plan actionable.
        with self.agent.lock:
            self.agent.pending = None
        repetitions=repetitions_count(repetitions)
        if type(retrieve) is not bool:
            raise TeachingError('Choose whether to retrieve the plate after imaging.')
        if type(pickup_from_calibration) is not bool:
            raise TeachingError('Choose whether the plate needs calibration pickup or is already held at Home.')
        if repetitions > 1 and not retrieve:
            raise TeachingError('Repeated plate-transfer cycles require retrieval between cycles. For repeated imaging while the plate stays at Squid, use its imaging time-point settings.')
        # A failed compound request must not leave an older partial plan actionable.
        with self.agent.lock:
            self.agent.pending = None
        blocker=self.history_blocker()
        if blocker:
            raise TeachingError(blocker)
        if pickup_from_calibration:
            base = self.agent.propose(['move_home','full_calibration'], source='automatic', _publish=False)
            if self.agent.classic.transport is None:
                raise TeachingError('The accepted pickup-to-Home workflow is not configured.')
        else:
            # Reuse the taught handling planner's actual state checks, including
            # Auto readiness. Never restart a controller with a held plate.
            state=self.backend.healthy()
            home,_=self.backend.home.target()
            near(state['pose_mm'],home,.2)
            base=self.agent.propose(['squid_dropoff'],source='automatic',_publish=False)
            # Standalone handling says it does not start the instrument and
            # assumes loading already. Neither describes this combined plan.
            base.update(steps=[],home_prefix=None,requirements=[
                'The plate is securely held at Home; the Squid holder is empty and ready to support it.',
                'Jaw clearance, 5 mm lift headroom and the loaded return are clear.',
                'Hands are clear, the arm is released, and the emergency stop is supervised.'])
            if self.agent.classic is None:
                raise TeachingError('The experiment dispatcher is unavailable.')
        imaging = self.instrument.prepare(protocol, allow_loading_return=True)
        delivery = self.projected_handling('squid_dropoff')
        retrieval = self.projected_handling('squid_retrieve') if retrieve else None
        phases = [dict(kind='stage',label='Prepare Squid loading position')]
        phases += [dict(kind='autonomous',label=s['label']) for s in delivery['steps']]
        phases += [dict(kind='imaging',label=s) for s in
                   ('Move Squid into imaging area','Start Squid imaging','Wait for this imaging run and stage cleanup to finish','Verify Squid returned to loading position')]
        if retrieve:
            phases += [dict(kind='autonomous',label=s['label']) for s in retrieval['steps']]
        cycle_phases=[dict(s,cycle=cycle,label=(f'Cycle {cycle}/{repetitions}: '+s['label'] if repetitions>1 else s['label']))
                      for cycle in range(1,repetitions+1) for s in phases]
        mock = imaging['simulation']
        base.update(dispatch='autonomous_squid', actions=[('calibrate_' if pickup_from_calibration else 'deliver_')+('image_retrieve' if retrieve else 'image_leave')],
                    labels=[('Calibrate, image' if pickup_from_calibration else 'Deliver and image')+(' and retrieve' if retrieve else '')], imaging=imaging,
                    pickup_from_calibration=pickup_from_calibration,
                    retrieve_after_imaging=retrieve,
                    repetitions=repetitions,plate_policy='same_plate',
                    delivery=delivery, retrieval=retrieval, pickup_step_count=len(base['steps']),
                    steps=base['steps']+cycle_phases, auto_workflow=True,
                    summary=(('Calibrate and pick up the plate, ' if pickup_from_calibration else 'With the plate already held at Home, ')
                             +'leave it at Squid, return Home, '
                             +('run MOCK imaging' if mock else 'run imaging')+
                             (', wait for confirmed completion, then retrieve the plate to Home.' if retrieve
                               else ', wait for confirmed completion, and leave the plate at Squid with the arm at Home.')))
        base['requirements'] += [
            ('One Yes authorizes this entire experiment, including automatic retrieval after its imaging job succeeds.' if retrieve
             else 'One Yes authorizes pickup, delivery and imaging. The plate remains at Squid; no retrieval is included.'),
            'With the arm at Home, Squid will return to its saved loading position before delivery. The stage path and all pickup/return paths are clear, and the plate will be supported on release.',
            'Imaging protocol: '+imaging['profile']['label']+'.',
            ('Squid is in simulation mode: images are MOCK. Robot movement is REAL when you confirm.'
             if mock else 'Real Squid imaging and the configured microscope return route are included.'),
            'Stay able to supervise the E-stop. Stop ends the workflow; a fault or uncertain result stops progression without a retry.']
        if not pickup_from_calibration:
            base['requirements'].append('The plate is already securely held at Home. Calibration will not be repeated.')
        if repetitions>1:
            base['labels']=[f'Squid experiment: {repetitions} cycles']
            base['summary']=(('Calibrate and pick up the plate once. ' if pickup_from_calibration else 'Use the plate already held at Home. ')+
                f'Run {repetitions} complete cycles with the same plate: deliver to Squid, image, retrieve and return Home. '
                'One Yes starts all cycles; no confirmations between successful cycles.')
            base['requirements'].append(f'One confirmation covers all {repetitions} cycles with this same plate and the same imaging settings. '
                'The next cycle starts only after the previous plate retrieval and Home return are verified. A fault, Stop or uncertain result ends the run without retry.')
        base['requirements'] += ['The microscope return waypoints in the selected protocol are clear.'] if imaging['profile'].get('return_waypoints') else []
        if mock and imaging.get('stage_simulated') is False:
            base['requirements'].append('The Squid stage moves PHYSICALLY; only camera images are simulated. This verifies integration, not optical imaging.')
        selected = imaging['profile'].get('selected_settings')
        saved=imaging['profile'].get('selection_source',{}).get('kind')=='saved_coordinates'
        if saved:
            capture=imaging['profile']['settings_capture_position']
            note=(f"Use saved imaging XY locations from stage X{capture['x_mm']:.3f}, "
                  f"Y{capture['y_mm']:.3f} mm with the current Squid acquisition controls. "
                  'Squid is at loading and its current imaging-site selection is empty. '
                  'Time points, channels and Z settings are read live. This Yes approves a new run; it does not resume the previous attempt.')
            base['requirements'].append(note)
            base['summary']+=' Using saved XY locations with current imaging settings because the current site selection is empty.'
        if selected:
            base['requirements'].append('Selected imaging: '+', '.join(selected['channels'])+
                f"; {selected['fovs']} fields, {selected['nz']} Z planes, {selected['nt']} time points "
                f"({selected['total_images']} images). "+('Review the locations and current settings before confirming.' if saved else
                'Keep these selections unchanged until you confirm. The confirmed run uses this saved snapshot.'))
        with self.agent.lock:
            self.agent.pending=base
        self.agent._announce_plan(base)
        return deepcopy(base)

    @staticmethod
    def write(path, record):
        temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
        temporary.replace(path)

    def start(self, plan):
        repetitions=repetitions_count(plan.get('repetitions',1))
        if repetitions>1 and not plan.get('retrieve_after_imaging',True):
            raise TeachingError('Repeated transfer cycles require retrieval.')
        blocker=self.history_blocker()
        if blocker:
            raise TeachingError(blocker)
        self.instrument.verify(plan['imaging'], check_position=False)
        for key,action in (('delivery','squid_dropoff'),('retrieval','squid_retrieve')):
            if key=='retrieval' and not plan.get('retrieve_after_imaging',True):
                continue
            if digest(self.projected_handling(action)) != digest(plan[key]):
                raise TeachingError('The complete experiment route changed. Request a fresh plan.')
        if not plan.get('pickup_from_calibration',True):
            self.backend.verify_confirmation(plan['delivery'],prepared=True)
        # No repeat confirmation ID, even after a failure.
        for path in self.folder.glob('*/workflow.json'):
            if json.loads(path.read_text(encoding='utf-8')).get('plan_id')==plan['id']:
                raise TeachingError('This experiment confirmation was already used.')
        folder=self.folder/(time.strftime('%Y%m%dT%H%M%S')+'_'+uuid4().hex[:8])
        folder.mkdir(parents=True,exist_ok=False)
        path=folder/'workflow.json'
        record=dict(status='confirmed',plan_id=plan['id'],plan=deepcopy(plan),
                    confirmed_at=time.time(),events=[],ticket=None,current_cycle=0,completed_cycles=0,
                    cycles=[dict(number=n,status='not_started',ticket=None) for n in range(1,repetitions+1)])
        self.write(path,record)
        self.active_record=path
        agent,backend,run=self.agent,self.backend,self.agent.get_runner()
        active={}
        def event(cycle,label,status,result=None):
            record['events'].append(dict(at=time.time(),cycle=cycle,step=label,status=status,result=result))
            record['status']='running'
            self.write(path,record)
        def arm_home():
            state=backend.healthy()
            near(state['pose_mm'],plan['delivery']['start'],.2)
            if abs(state['external_axes']['E1']-5.)>.05:
                raise TeachingError('The empty gripper changed while waiting for imaging.')
        def job(cycle,label,fn,before=None,timeout_s=1200,last=False):
            label=f'Cycle {cycle}/{repetitions}: '+label if repetitions>1 else label
            def dispatch():
                if agent.classic.cancel.is_set():
                    raise TeachingError('Experiment stopped before '+label+'.')
                record['current_cycle']=cycle
                record['cycles'][cycle-1]['status']='running'
                with agent.lock:agent.run_meta.update(current_cycle=cycle,completed_cycles=record['completed_cycles'])
                self.write(path,record)
                if cycle>1 and record['cycles'][cycle-2]['status']!='completed':
                    raise TeachingError('The previous cycle has not completed its verified return Home.')
                if before:
                    before()
                event(cycle,label,'dispatch_requested')
                def execute(runner):
                    try:
                        result=fn(runner)
                        if not isinstance(result,dict) or result.get('ok') is not True:
                            raise TeachingError(label+' did not confirm success.')
                        if last:
                            if plan.get('retrieve_after_imaging',True):delivery_home()
                            record['cycles'][cycle-1]['status']='completed'
                            record['cycles'][cycle-1]['finished_at']=time.time()
                            record['completed_cycles']=cycle
                            with agent.lock:agent.run_meta['completed_cycles']=cycle
                        event(cycle,label,'completed',result)
                        return result
                    except Exception as error:
                        record['cycles'][cycle-1]['status']='failed'
                        event(cycle,label,'failed',dict(error=str(error)))
                        raise
                return run.start('autonomous_squid_step',execute)
            return dict(label=label,start=dispatch,timeout_s=timeout_s)
        def delivery_home():
            state=backend.healthy()
            near(state['pose_mm'],plan['delivery']['start'],.2)
            if abs(state['external_axes']['E1']-3.7)>.05:
                raise TeachingError('The held plate gripper position changed before delivery.')
        def cycle_tasks(cycle):
            # Each cycle owns its ticket, files and closures. A previous imaging
            # completion can never authorize retrieval for the next cycle.
            ticket={}
            cycle_folder=folder if repetitions==1 else folder/f'cycle_{cycle:04d}'
            cycle_folder.mkdir(exist_ok=True)
            def save_ticket(value):
                record['ticket']=deepcopy(value)
                record['cycles'][cycle-1]['ticket']=deepcopy(value)
                self.write(path,record)
            def begin_cycle(r):
                active.update(ticket=ticket,save=save_ticket)
                return self.instrument.prepare_loading(plan['imaging'],r.stopped,delivery_home)
            tasks=[job(cycle,'Prepare Squid loading position',begin_cycle)]
            for index,step in enumerate(plan['delivery']['steps']):
                def delivery_ready(first=index==0):
                    self.instrument.verify(plan['imaging'],check_selection=False)
                    if first:backend.verify_confirmation(plan['delivery'],prepared=True)
                tasks.append(job(cycle,step['label'],lambda r,s=step:backend.execute_step(r,s,plan['delivery']),delivery_ready))
            def start_imaging(r):
                arm_home()
                ticket.update(self.instrument.start(plan['imaging'],cycle_folder,save_ticket,r.stopped))
                return dict(ok=True,request_id=ticket['request_id'],simulation=ticket['simulation'])
            def wait_imaging(r):
                def progress(state):
                    arm_home()
                    agent.classic._note(message=f'Cycle {cycle}/{repetitions}: waiting at Home while Squid images this plate. No further Yes is needed.')
                return self.instrument.wait(plan['imaging'],ticket,save_ticket,r.stopped,progress)
            tasks.append(job(cycle,'Move Squid into imaging area',lambda r:self.instrument.prepare_imaging(plan['imaging'],r.stopped,arm_home)))
            tasks.append(job(cycle,'Start Squid imaging',start_imaging))
            tasks.append(job(cycle,'Wait for this imaging run and stage cleanup to finish',wait_imaging,
                             timeout_s=plan['imaging']['profile']['timeout_s']+60))
            retrieval_steps=(plan.get('retrieval') or {}).get('steps', [])
            tasks.append(job(cycle,'Verify Squid returned to loading position',
                lambda r:self.instrument.restore_loading(plan['imaging'],ticket,save_ticket,r.stopped,arm_home),last=not retrieval_steps))
            for index,step in enumerate(retrieval_steps):
                def retrieval_ready(first=index==0):
                    if first:arm_home()
                    observed=self.instrument.observe(plan['imaging'],ticket,save_ticket)
                    if ticket.get('status')!='completed' or observed.get('completion_confirmed') is not True:
                        raise TeachingError('The confirmed imaging job is not complete. Retrieval blocked.')
                    self.instrument.verify(plan['imaging'],check_selection=False)
                    if first:backend.verify_confirmation(plan['retrieval'],prepared=True)
                tasks.append(job(cycle,step['label'],lambda r,s=step:backend.execute_step(r,s,plan['retrieval']),
                                 retrieval_ready,last=index==len(retrieval_steps)-1))
            return tasks
        tail=[task for cycle in range(1,repetitions+1) for task in cycle_tasks(cycle)]
        message=('Experiment complete: plate returned Home after '+
                 ('mock imaging.' if plan['imaging']['simulation'] else 'imaging.'))
        if not plan.get('retrieve_after_imaging',True):
            message=('Experiment complete: '+('mock imaging' if plan['imaging']['simulation'] else 'imaging')+
                     ' finished. The plate remains at Squid and the arm is at Home.')
        if repetitions>1:
            message=f'Completed all {repetitions} Squid cycles. The plate is back at Home.'+(' Imaging was simulated.' if plan['imaging']['simulation'] else '')
        def finished(final):
            ticket=active.get('ticket',{})
            save_ticket=active.get('save')
            if (not final.get('ok') and ticket.get('experiment_id')
                    and (agent.classic.cancel.is_set() or run.stopped())):
                try:
                    self.instrument.abort_owned(plan['imaging'],ticket,save_ticket)
                except Exception as error:
                    final = {**final, 'message':final['message']+
                             ' Imaging cancellation could not be verified: '+str(error)}
            record.update(status='completed' if final.get('ok') else 'stopped_or_failed',
                          finished_at=time.time(),result=deepcopy(final))
            if not final.get('ok') and record['current_cycle']:
                current=record['cycles'][record['current_cycle']-1]
                if current['status']!='completed':
                    current['status']='stopped_or_failed'
                    record['failed_cycle']=record['current_cycle']
                elif record['current_cycle']<repetitions:
                    record['stopped_before_cycle']=record['current_cycle']+1
            try:self.write(path,record)
            except Exception as error:
                final={**final,'ok':False,'error':str(error),'message':'Experiment ended but its final record could not be saved. Review before another run.'}
            with agent.lock:
                agent.run_state={k:deepcopy(final.get(k)) for k in ('active','step','done','ok','error','message')}
            agent.note(final['message']);agent._say('lacry',final['message'])
        with agent.lock:
            agent.pending=None
            agent.run_meta=dict(name='Automatic experiment'+(' · MOCK imaging' if plan['imaging']['simulation'] else ''),
                                total_steps=len(plan['steps']), automatic=True,
                                repetitions=repetitions,current_cycle=0,completed_cycles=0)
            agent.run_state=dict(active=True,step=plan['steps'][0]['label'],done=[],ok=None,error='',message='Starting the confirmed experiment.')
        try:
            return agent.classic.start(on_finish=finished,
                home_prefix=agent._pickup_home_callbacks(plan['home_prefix']) if plan.get('home_prefix') else None,
                tail_steps=tail,completion_message=message,
                include_pickup=plan.get('pickup_from_calibration',True))
        except Exception as error:
            record.update(status='stopped_or_failed',error=str(error));self.write(path,record)
            with agent.lock:
                agent.run_state.update(active=False,ok=False,error=str(error),message=str(error))
            raise
