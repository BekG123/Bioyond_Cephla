"""Hamilton plans use Lacry's existing confirmation and shared runner."""
from copy import deepcopy
from contextlib import nullcontext
import time
from uuid import uuid4
from researcher_teaching import TeachingError
from scope_step_trial import near
from hamilton_prep import ACTION_LABELS, FULL_CALIBRATION_STEPS, digest


class HamiltonWorkflow:
    def __init__(self,agent):
        self.agent=agent
        self.adapter=agent.backend.instrument

    def arm_clear(self):
        backend=self.agent.backend
        robot=backend.healthy(prepared=False)
        home,_=backend.home.target()
        near(robot['pose_mm'],home,.2)

    def propose(self,action,protocol=None,repetitions=1,tip_site=None,tip_labware_id=None,polling_test=None):
        if polling_test is not None and (polling_test not in ('normal','reduced') or action!='self_calibration'):
            raise TeachingError('Polling comparison supports one native self-calibration only.')
        if action not in (*ACTION_LABELS,'protocol'):
            raise TeachingError('Choose initialization, self-calibration, channel calibration, full calibration or a saved recipe.')
        if type(repetitions) is not int or not 1<=repetitions<=100:
            raise TeachingError('Choose 1 to 100 cycles.')
        if action!='protocol' and repetitions!=1:
            raise TeachingError('Calibration runs once. Use experiment repetitions for liquid handling.')
        run=self.agent.get_runner()
        if run.active or run.reserved: raise TeachingError('Another workflow owns the lab.')
        blockers=[];prepared=None;setup=None
        try:
            self.arm_clear()
            self.adapter.preflight()
            if action=='park':
                from hamilton_park import preflight,driver_types
                preflight(self.adapter)
                driver_types()  # Import/revision check only; never connects.
            if action in ('channel_calibration','full_calibration'):
                setup=self.adapter.calibration_setup(tip_site,tip_labware_id)
            if action=='protocol': prepared=self.adapter.prepare(protocol,repetitions=repetitions)
        except Exception as error: blockers.append(str(error))
        label=ACTION_LABELS.get(action,f'Run Hamilton recipe {protocol} × {repetitions}')
        stages=FULL_CALIBRATION_STEPS if action=='full_calibration' else [action]
        labels=[ACTION_LABELS.get(s,label) for s in stages]
        plan=dict(id=uuid4().hex,at=time.time(),dispatch='hamilton',actions=['hamilton_'+action],
            action=action,protocol=protocol,prepared=prepared,repetitions=repetitions,polling_test=polling_test,
            calibration_setup=setup,settings_hash=digest(self.adapter.settings()),
            session_id=self.adapter.session,labels=[label],summary=label+'. '+
                ('Self-calibrate → calibrate channel height and squeeze. ' if action=='full_calibration' else '')+
                (f"For the channel stage, use {setup['label']} at site {setup['tip_site']}. " if setup else '')+'Keep the arm at Home.',
            steps=[dict(kind='hamilton',label=x) for x in labels],executable=not blockers,blockers=blockers,
            requirements=['Hands clear, secure compatible holders, and Bioyond arm parked at Home.',
                'One confirmation covers this entire plan and all listed cycles. Faults stop the sequence without retry.',
                'Any Hamilton instruction needing a physical change appears in the Hamilton panel.'])
        if action in ('self_calibration','full_calibration'):
            plan['requirements'].append('The teaching needle is seated in its dedicated waste-block holder.')
            plan['requirements'].append('Follow Hamilton instructions to clear the deck for self-calibration; this stage does not require a tip rack at site 7.')
        if setup:
            when='After self-calibration, when requested, load' if action=='full_calibration' else 'Before channel calibration, load'
            plan['requirements'].append(f"{when} a full compatible tip rack at site {setup['tip_site']}, with its lid removed. The camera must confirm it before channel calibration starts.")
        if polling_test:
            plan['summary']+=' Polling comparison: '+polling_test+'; all Lacry Hamilton API requests recorded.'
        if action=='park':
            plan['requirements'].append('Hamilton channels hold no plate, tips or tools; the native parking path is clear and the door closed. This moves Hamilton, not the robot arm, and does not clear faults.')
        with self.agent.lock:
            if self.agent.review: raise TeachingError('Finish the current inspection first.')
            self.agent.pending=plan
        self.agent._announce_plan(plan)
        return deepcopy(plan)

    def start(self,plan):
        self.arm_clear();self.adapter.preflight()
        if plan['session_id']!=self.adapter.session: raise TeachingError('Hamilton session changed.')
        if plan.get('settings_hash')!=digest(self.adapter.settings()):raise TeachingError('Hamilton settings changed. Review a new plan.')
        if plan.get('calibration_setup'):self.adapter.verify_calibration_setup(plan['calibration_setup'])
        with self.agent.lock:
            if not self.agent.pending or self.agent.pending['id']!=plan['id']:
                raise TeachingError('This plan has already been used.')
            self.agent.pending=None
            self.agent.run_meta=dict(name=plan['labels'][0],total_steps=plan['repetitions'] if plan['action']=='protocol' else len(plan['steps']))
            self.agent.run_state=dict(active=True,step=plan['labels'][0],done=[],ok=None,message='Starting Hamilton.',error='')
        result=self.agent.get_runner().start('lacry_hamilton',self.execute,plan)
        if not result.get('ok'):
            with self.agent.lock:self.agent.run_state.update(active=False,ok=False,message='Another task owns the lab.')
            raise TeachingError('Another task owns the lab. No Hamilton command was sent.')
        return dict(ok=True,message='Hamilton plan started.')

    def execute(self,run,plan):
        done=[]
        def progress(state):
            self.arm_clear()
            with self.agent.lock:
                self.agent.run_state.update(message=state.get('message','Working'),done=list(done))
                if state.get('completed_steps') is not None:
                    self.agent.run_state.update(done=[ACTION_LABELS[x] for x in state['completed_steps']],step=ACTION_LABELS.get(state.get('step'),plan['labels'][0]))
        try:
            if plan['action']=='protocol':
                for i in range(plan['repetitions']):
                    if run.stopped(): raise TeachingError('Hamilton sequence stopped.')
                    self.arm_clear()
                    def save(ticket):run.audit('hamilton_ticket',cycle=i+1,ticket=ticket)
                    ticket=self.adapter.start(plan['prepared'],'stationary_plate',save)
                    self.adapter.wait(plan['prepared'],ticket,save,run.stopped,progress)
                    done.append(f'Cycle {i+1}/{plan["repetitions"]}')
            else:
                comparison=self.adapter.polling_comparison(plan['polling_test']) if plan.get('polling_test') else nullcontext()
                with comparison:
                    result=self.adapter.run_action(plan['action'],run.stopped,progress,calibration_setup=plan.get('calibration_setup'))
                done.extend(ACTION_LABELS[x] for x in result.get('completed_steps',[plan['action']]))
            result=dict(ok=True,active=False,step=None,done=done,error='',message='Hamilton plan completed.')
        except Exception as error:
            result=dict(ok=False,active=False,step=plan['labels'][0],done=done,error=str(error),message='Hamilton stopped: '+str(error))
        with self.agent.lock:self.agent.run_state=deepcopy(result)
        self.agent._say('lacry',result['message'])
        return result
