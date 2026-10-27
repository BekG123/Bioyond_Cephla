"""Named microscope-stage actions. No model-supplied coordinates or robot moves."""
from copy import deepcopy
import json
from pathlib import Path
import time
from uuid import uuid4

from researcher_teaching import TeachingError
from scope_step_trial import near
from squid_execution import AXES, at_position, digest, position
from squid_adapter import native_command

ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT / 'squid_stage_reference.json'


def validate_loading_target(ref):
    """This commissioned controller homes XY at their negative ends.

    Never use a negative taught readback as a repeatable absolute target after
    rehoming. Virtual scanning limits do not change the driver's homed range.
    Do not silently clamp a target: it changes the plate-to-robot relationship.
    """
    target = position(ref['dropoff'])
    if ref.get('controller_serial') == '12769210' and min(target['x_mm'],target['y_mm']) < 0:
        raise TeachingError('Squid loading XY is outside the repeatable positive homed range. Review an inward loading target; no motion was sent.')
    return target


class SquidStage:
    def __init__(self, agent, reference=REFERENCE, command=None, sleep=time.sleep, location_capture=None):
        self.agent = agent
        self.adapter = agent.backend.squid
        self.reference = Path(reference)
        self.command = command or (lambda name, params: native_command(
            name, params, self.adapter.port, timeout=180))
        self.sleep = sleep
        self.location_capture=location_capture

    def saved(self):
        ref = json.loads(self.reference.read_text(encoding='utf-8-sig'))
        position(ref['dropoff'])
        if ref.get('operator_confirmed') is not True:
            raise TeachingError('The Squid drop-off location needs operator review.')
        return ref

    def status(self):
        state = self.adapter.poll()
        ref = self.saved()
        actual = position(self.command('get_position', {})) if state.get('connected') else None
        return dict(instrument=state, position_mm=actual, dropoff_mm=ref['dropoff'],
                    at_dropoff=actual is not None and all(abs(actual[k]-ref['dropoff'][k]) <= .02 for k in AXES),
                    controller_serial=ref['controller_serial'],
                    motion_hold=ref.get('motion_hold'),
                    home_definition='Native Squid XYZ referencing; different from saved drop-off and robot Home.',
                    reference_source=ref['source'])

    def ready(self, plan=None):
        state = self.adapter.poll()
        if not state.get('connected') or state.get('status') not in ('idle','historical','running','finishing','completed'):
            raise TeachingError('Squid is disconnected, failed or uncertain. Inspect its status before moving the stage.')
        ref = self.saved()
        if ref.get('motion_hold'):
            raise TeachingError(ref['motion_hold'])
        validate_loading_target(ref)
        if state.get('stage_simulated') is not False or state.get('controller_serial') != ref['controller_serial']:
            raise TeachingError('The connected physical Squid controller does not match the saved drop-off reference.')
        if plan and (state['session'] != plan['session'] or digest(ref) != plan['reference_hash']):
            raise TeachingError('Squid session or drop-off reference changed. Request a fresh plan.')
        bridge = self.command('get_stage_reference',{})
        if bridge.get('reference_hash') != digest(ref) or bridge.get('controller_serial') != ref['controller_serial']:
            raise TeachingError('Squid loading extension or controller reference is out of date.')
        return state

    def arm_clear(self):
        backend = self.agent.backend
        robot = backend.healthy(prepared=False)
        home, _ = backend.home.target()
        near(robot['pose_mm'], home, .2)

    def propose(self, destination, after_scan=False, _publish=True):
        with self.agent.lock:
            if _publish:self.agent.pending = None
            if self.agent.review:
                raise TeachingError('Finish the pending inspection first.')
        if destination not in ('dropoff','home') or type(after_scan) is not bool:
            raise TeachingError('Choose Squid stage dropoff or home, and whether to wait for the current scan.')
        runner = self.agent.get_runner()
        if runner.active or runner.reserved:
            raise TeachingError('Another lab workflow is running. Its stage return cannot be replaced.')
        state = self.ready()
        self.arm_clear()
        busy = state['status'] in ('running','finishing')
        if busy and not after_scan:
            raise TeachingError('Squid is scanning. Ask to return after the current scan finishes.')
        job = state.get('job') if busy or (after_scan and state.get('completion_confirmed') is True) else None
        if busy and (not job or not job.get('run_id') or not job.get('experiment_id')):
            raise TeachingError('The current scan has no verified job identity. No deferred movement was queued.')
        label = 'Return Squid stage to drop-off' if destination == 'dropoff' else 'Home the Squid stage'
        steps = ([dict(kind='imaging',label='Wait for the current Squid scan to finish')] if busy else [])
        steps.append(dict(kind='squid_stage',label=label))
        plan = dict(id=uuid4().hex,at=time.time(),source='chat',dispatch='squid_stage',
                    actions=['squid_stage_'+destination],labels=[label],steps=steps,
                    destination=destination,job=deepcopy(job),session=state['session'],
                    reference_hash=digest(self.saved()),start=position(self.command('get_position',{})),
                    summary=('Wait for this scan to finish successfully, then ' if busy else '')+label+'.',
                    requirements=['The robot remains at Home, the microscope stage path is clear, and the E-stop is supervised.',
                                  'This moves only the microscope stage. It does not fetch the plate.',
                                  'Stop cancels remaining steps after the current native stage move finishes. It does not abort an independently started scan.'])
        if destination == 'home':
            plan['requirements'].append('This runs Squid’s native XYZ homing sequence; it does not return to the saved drop-off location.')
        if _publish:
            with self.agent.lock:
                self.agent.pending = plan
            self.agent._announce_plan(plan)
        return deepcopy(plan)

    def check_job(self, plan, state):
        job = state.get('job') or {}
        wanted = plan.get('job')
        if wanted:
            if any(job.get(k) != wanted[k] for k in ('run_id','experiment_id')):
                raise TeachingError('The Squid imaging job changed. The stage will not move.')
            if state['status'] == 'completed' and state.get('completion_confirmed') is True:
                return True
            if state['status'] not in ('running','finishing'):
                raise TeachingError('This scan did not confirm successful completion. The stage will not move.')
            return False
        if state['status'] in ('running','finishing'):
            raise TeachingError('A scan started after this plan was proposed. Request a new plan.')
        return True

    def start(self, plan):
        self.arm_clear()
        state = self.ready(plan)
        self.check_job(plan,state)
        if not plan.get('job'):
            at_position(self.command('get_position',{}),plan['start'])
        with self.agent.lock:
            if not self.agent.pending or self.agent.pending['id'] != plan['id']:
                raise TeachingError('This stage confirmation has already been used.')
            self.agent.pending = None
            self.agent.run_meta = dict(name=plan['labels'][0],total_steps=len(plan['steps']))
            self.agent.run_state = dict(active=True,step=plan['steps'][0]['label'],done=[],ok=None,error='',message='Starting Squid stage task.')
        result = self.agent.get_runner().start('lacry_squid_stage',self.execute,plan)
        if not result.get('ok'):
            with self.agent.lock:
                self.agent.run_state.update(active=False,ok=False,error='Another task owns the runner.')
            raise TeachingError('Another lab task owns the runner. No stage command was sent.')
        return dict(ok=True,message='Squid stage task started. Robot movement is not included.')

    def execute(self, run, plan, publish_progress=True):
        done = []
        folder = ROOT/'reports/squid_stage'
        folder.mkdir(parents=True,exist_ok=True)
        path = folder/(plan['id']+'.json')
        record = dict(plan=plan,status='running',events=[])
        def save(event, **fields):
            record['events'].append(dict(at=time.time(),event=event,**fields))
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
            temporary.replace(path)
            run.audit('squid_stage_'+event,**fields)
        def guard():
            if run.stopped():
                raise TeachingError('Squid stage task stopped. No further stage command was sent.')
            self.arm_clear()
            return self.ready(plan)
        try:
            save('started',plan=plan)
            deadline = time.monotonic()+86400
            while not self.check_job(plan,guard()):
                if time.monotonic() > deadline:
                    raise TeachingError('Timed out waiting for this scan. No stage movement was started.')
                self.sleep(.5)
            if plan.get('job'):
                if plan['steps'][0]['kind']=='imaging':done.append(plan['steps'][0]['label'])
                save('scan_completed',squid_run_id=plan['job']['run_id'],
                     squid_experiment_id=plan['job']['experiment_id'])
            label = plan['steps'][-1]['label']
            if publish_progress:
                with self.agent.lock:
                    self.agent.run_state.update(step=label,done=list(done),message=label)
            run.say(label)
            self.check_job(plan,guard())
            before = position(self.command('get_position',{}))
            if self.location_capture is not None:
                save('locations_preserved',result=self.location_capture())
                self.check_job(plan,guard())
            if plan['destination'] == 'home':
                save('command_requested',command='home',before=before)
                result = self.command('home',{})
                if result.get('homed') is not True:
                    raise TeachingError('Squid homing did not confirm completion. Do not retry automatically.')
                expected = position(result['position'])
            else:
                expected = self.saved()['dropoff']
                if any(abs(before[k]-expected[k]) > .02 for k in AXES):
                    self.check_job(plan,guard())
                    save('command_requested',command='return_to_recorded_dropoff',target=expected)
                    result = self.command('return_to_recorded_dropoff',{'reference_hash':plan['reference_hash']})
                    if result.get('at_dropoff') is not True:
                        raise TeachingError('Squid did not confirm its loading move. Inspect the stage; no retry was sent.')
            self.check_job(plan,guard())
            actual = position(self.command('get_position',{}))
            self.sleep(.2)
            at_position(self.command('get_position',{}),expected)
            at_position(actual,expected)
            done.append(label)
            record.update(status='completed',final_position=actual)
            save('verified',position=actual)
            message = 'Squid is at its saved drop-off location.' if plan['destination']=='dropoff' else 'Squid stage homing is complete.'
            if publish_progress:
                with self.agent.lock:
                    self.agent.run_state.update(active=False,step=label,done=done,ok=True,error='',message=message)
                self.agent._say('lacry',message)
            return dict(ok=True,position=actual,done=done,report=str(path))
        except Exception as error:
            record.update(status='stopped' if run.stopped() else 'failed',error=str(error))
            save('failed',error=str(error))
            message = 'Squid stage task stopped: '+str(error)
            if publish_progress:
                with self.agent.lock:
                    self.agent.run_state.update(active=False,done=done,ok=False,error=str(error),message=message)
                self.agent._say('lacry',message)
            run.state = 'stopped' if run.stopped() else 'error'
            return dict(ok=False,error=str(error),report=str(path))
