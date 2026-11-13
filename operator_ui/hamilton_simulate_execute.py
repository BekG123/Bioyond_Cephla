"""One human approval: create if needed, native simulation, then exact live job."""
from copy import deepcopy
import time
from uuid import uuid4

from dilution_protocol import obj, verify_protocol, verify_simulation
from hamilton_prep import digest
from researcher_teaching import TeachingError

RULES='''
For a fully specified Hamilton experiment, use draft_protocol (or
adopt_hamilton_protocol for a matching native method), then
plan_hamilton_experiment. This single plan covers native creation if needed,
Hamilton simulation, and automatic physical execution ONLY if that exact
simulation succeeds. The researcher approves the complete plan once. Do not
ask for separate simulation review, commissioning, another Yes, or a physical
validation trial between those phases. No permanent recipe is required.
Collect exact liquid amounts, initial volumes, wells, tips and mixing first.
This tool operates on a plate already at Hamilton site 4; it does not move the
arm or deliver a plate. For a transport-plus-protocol request, use plan_workflow
with the draft_id and all requested operations instead: it includes this same
executor after delivery within the one complete approval. Never split that
request into separately approved delivery and instrument plans.
Failed simulation, changed settings, Stop, timeout, or uncertain
physical outcome ends the run; never automatically retry or claim completion.
The initial approval includes exact deck/inventory and E-stop supervision for
the subsequent live run. Simulation alone is not permission without that plan.
'''
TOOLS=[dict(name='plan_hamilton_experiment',
    description='Propose one approved create-if-needed → native simulate → execute experiment. Successful exact simulation automatically advances to live pipetting, with no commissioning or second approval. Plate must already be at Hamilton site 4; no transport is included.',
    input_schema=obj(dict(draft_id=dict(type='string'),plate_id=dict(type='string',minLength=1,maxLength=512))))]
NAMES={t['name'] for t in TOOLS}


class HamiltonExperiment:
    def __init__(self,agent):self.agent=agent

    @property
    def author(self):return self.agent.protocol_authoring

    @property
    def h(self):return self.author.h

    def arm_checkpoint(self):
        from scope_step_trial import near
        from composed_cellvis_registration import delivery_steps
        from home_hamilton_exchange import native
        state=self.agent.backend.healthy(prepared=False)
        axes=native(self.agent.backend.s)
        if axes['moving'] or abs(axes['external_axes']['E1']-28)>.2:
            raise TeachingError('Hamilton experiment requires stationary empty jaws open to 28 mm outside Hamilton.')
        home=delivery_steps('Hamilton',False)[-1]['points'][-1]
        idle,_=self.agent.backend.home.target()
        for target in (home,idle):
            try:near(state['pose_mm'],target,.2)
            except Exception:continue
            return deepcopy(target)
        raise TeachingError('Park the empty arm at accepted HOME clearance or IDLE before Hamilton instrument work.')

    def check_setup(self,plan=None):
        target=self.arm_checkpoint()
        if plan is not None and target!=plan['arm_checkpoint']:
            raise TeachingError('Arm checkpoint changed after approval.')
        self.h.preflight(initialized=True);self.h.require_calibration()
        return target

    def prepare_bound(self,draft_id):
        """Read-only binding for an outer transport plan; no fabricated plate ID."""
        record=self.author.read(draft_id)
        if record['status'] not in ('draft','created','simulated'):
            raise TeachingError('Hamilton draft already used or uncertain; no automatic retry.')
        self.author.verify_catalog(record)
        if record['status']!='draft' and digest(self.h.call('GET','protocols/'+str(record['protocol_id'])))!=record['protocol_hash']:
            raise TeachingError('Native protocol changed; prepare a fresh draft.')
        self.h.preflight(initialized=True);self.h.require_calibration()
        timeout=float(self.h.settings().get('timeout_s',3600))
        if not 0<timeout<=4*3600:raise TeachingError('Hamilton timeout must be positive and at most four hours.')
        return dict(mode='simulate_execute',draft_id=draft_id,draft_hash=digest(record),
            session_id=self.h.session,settings_hash=digest(self.h.settings()),timeout_s=timeout,
            protocol_review=dict(kind='dilution_authoring',action='simulate_execute',physical_execution_authorized=True,
                draft_id=draft_id,name=record['spec']['name'],protocol_hash=record.get('protocol_hash'),
                transfer_kind='addition' if 'additions' in record['spec'] else 'dilution',dilution_table=record['compiled']['summary'],
                deck=record['spec']['deck'],tip_site=record['spec']['tip_site'],tip_wells=record['spec']['tip_wells'],
                initial_volumes=record['spec']['initial_volumes'],pipetting=record['spec']['pipetting'],
                height_reference='Internal well bottom (FromContainerBottom), millimetres',liquid_class='Aqueous; native speed settings'))

    def verify_bound(self,plan):
        self.verify_connection(plan)
        fresh=self.prepare_bound(plan['draft_id'])
        if fresh!=plan:raise TeachingError('Hamilton draft binding changed after approval.')

    def propose(self,draft_id,plate_id):
        self.author.available()
        with self.agent.lock:self.agent.pending=None
        if not isinstance(plate_id,str) or not 1<=len(plate_id.strip())<=512:raise TeachingError('Supply the actual transported plate ID.')
        record=self.author.read(draft_id)
        if record['status'] not in ('draft','created','simulated'):
            raise TeachingError('Draft already used or uncertain; no automatic experiment retry.')
        self.author.verify_catalog(record)
        if record['status']!='draft':
            if digest(self.h.call('GET','protocols/'+str(record['protocol_id'])))!=record['protocol_hash']:
                raise TeachingError('Native protocol changed; prepare a fresh draft.')
        checkpoint=self.check_setup()
        timeout=float(self.h.settings().get('timeout_s',3600))
        if not 0<timeout<=4*3600:raise TeachingError('Hamilton timeout must be positive and at most four hours.')
        labels=(['Create the exact native protocol'] if record['status']=='draft' else [])+[
            'Simulate the exact protocol in Hamilton','If simulation succeeds, execute once on Hamilton']
        plan=dict(id=uuid4().hex,at=time.time(),dispatch='hamilton_experiment',draft_id=draft_id,
            draft_hash=digest(record),session_id=self.h.session,settings_hash=digest(self.h.settings()),
            plate_id=plate_id.strip(),arm_checkpoint=checkpoint,timeout_s=timeout,
            summary='Simulate, then automatically execute '+record['spec']['name']+' on plate '+plate_id.strip(),
            executable=True,repetitions=1,labels=labels,steps=[dict(kind='hamilton_experiment',label=x) for x in labels],
            requirements=['Approve the displayed exact protocol, native simulation and one subsequent physical run as a single experiment.',
                'The specified plate is flat at Hamilton site 4. Source labware, liquid volumes and fresh tip wells match the displayed inventory; door closed.',
                'Arm remains at its empty clearance checkpoint, Hamilton area and hands clear, E-stop supervised throughout. Failure or uncertainty stops without retry.'],
            protocol_review=dict(kind='dilution_authoring',action='simulate_execute',physical_execution_authorized=True,
                draft_id=draft_id,name=record['spec']['name'],plate_id=plate_id,protocol_hash=record.get('protocol_hash'),
                transfer_kind='addition' if 'additions' in record['spec'] else 'dilution',dilution_table=record['compiled']['summary'],
                deck=record['spec']['deck'],tip_site=record['spec']['tip_site'],tip_wells=record['spec']['tip_wells'],
                initial_volumes=record['spec']['initial_volumes'],pipetting=record['spec']['pipetting']))
        with self.agent.lock:self.agent.pending=plan
        self.agent._announce_plan(plan)
        return dict(ok=True,awaiting_confirmation=True,plan=self.agent._plan_view(plan))

    def start(self,plan):
        self.author.available()
        if plan.get('confirmation_source') not in ('researcher_chat','researcher_button'):
            raise TeachingError('The researcher must approve the complete simulate-and-execute plan.')
        if not 0<=time.time()-plan['at']<=600:raise TeachingError('Experiment approval expired.')
        record=self.author.read(plan['draft_id'])
        if digest(record)!=plan['draft_hash']:raise TeachingError('Draft changed after approval.')
        self.verify_connection(plan);self.check_setup(plan)
        with self.agent.lock:
            if not self.agent.pending or self.agent.pending['id']!=plan['id']:raise TeachingError('Approval already consumed or changed.')
            self.agent.pending=None
            self.agent.run_meta=dict(name=plan['summary'],total_steps=len(plan['steps']))
            self.agent.run_state=dict(active=True,step=plan['labels'][0],done=[],ok=None,error='',message='Starting approved simulation-to-execution experiment.')
        result=self.agent.get_runner().start('lacry_hamilton_experiment',self.execute,plan)
        if not result.get('ok'):
            with self.agent.lock:self.agent.run_state.update(active=False,ok=False,error='Lab runner unavailable.')
            raise TeachingError('Lab runner unavailable; no commands sent.')
        return dict(ok=True,message='Simulation will advance directly to the approved live run if successful.')

    def verify_connection(self,plan):
        if self.h.session!=plan['session_id'] or digest(self.h.settings())!=plan['settings_hash']:
            raise TeachingError('Hamilton connection/settings changed after approval.')

    def execute(self,run,plan,*,checkpoint=None,composed=False):
        if composed and (checkpoint is None or plan.get('confirmation_source') not in ('researcher_chat','researcher_button','researcher_terminal')):
            raise TeachingError('Composed Hamilton execution needs the outer approved plan and its verified arm checkpoint.')
        record=None;done=[]
        deadline=time.monotonic()+900+plan['timeout_s']
        def check():
            if run.stopped() or time.monotonic()>deadline:raise TeachingError('Experiment stopped or time window expired; no retry.')
            self.verify_connection(plan)
            if checkpoint is not None:checkpoint()
            elif self.arm_checkpoint()!=plan['arm_checkpoint']:raise TeachingError('Arm left its approved checkpoint.')
        def setup():
            if checkpoint is None:self.check_setup(plan)
            else:
                checkpoint();self.h.preflight(initialized=True);self.h.require_calibration()
        def phase(message):
            run.say(message)
            with self.agent.lock:
                self.agent.run_state.update(step=message,message=message)
                if not composed:self.agent.run_state['done']=list(done)
        try:
            record=self.author.read(plan['draft_id'])
            if digest(record)!=plan['draft_hash']:raise TeachingError('Draft changed before dispatch.')
            check();setup();self.author.verify_catalog(record)
            create=record['status']=='draft'
            record.update(status='executing_experiment',experiment_plan_id=plan['id'],plate_id=plan['plate_id'])
            record['attempts'].append(dict(action='simulate_execute',plan_id=plan['id'],confirmed_by=plan['confirmation_source'],at=time.time()))
            self.author.save(record)
            with self.h.owned('experiment_simulation') as ticket:
                if create:
                    phase('Creating the approved Hamilton protocol')
                    self.author.create(record,ticket,check);done.append('Native protocol created')
                phase('Hamilton simulation running; live execution follows only on success')
                self.author.simulate(record,ticket,check,run)
                ticket['status']='completed';self.h.journal(ticket,'outcome',dict(status='simulation_completed',plan_id=plan['id']))
            done.append('Exact Hamilton simulation passed')
            check();setup();self.author.verify_catalog(record)
            native=self.h.call('GET','protocols/'+str(record['protocol_id']))
            if digest(native)!=record['protocol_hash']:raise TeachingError('Protocol changed after simulation.')
            verify_protocol(native,record['compiled'],record['spec'])
            verify_simulation(record['simulation_result'],record['simulation_report']['job_id'],native,record['compiled'])
            # Ephemeral single-use execution binding. No global recipe, no
            # invented commissioning attestation, and no inventory reset.
            recipe=dict(protocol_id=record['protocol_id'],protocol_hash=record['protocol_hash'],
                inventory_id='experiment-'+record['draft_id'],cycle_loads=[dict(
                    load_instructions_hash=record['load_instructions_hash'],load_complete=record['compiled']['load_complete'])])
            prepared=dict(protocol=record['spec']['name'],recipe=recipe,settings_hash=plan['settings_hash'],
                session_id=plan['session_id'],timeout_s=min(plan['timeout_s'],max(0,deadline-time.monotonic())))
            record.update(status='physical_dispatch_pending',execution_binding=prepared)
            self.author.save(record)
            phase('Simulation passed; executing the approved physical experiment')
            def save(ticket):
                record['physical_ticket']=deepcopy(ticket);self.author.save(record)
            check()
            ticket=self.h.start(prepared,plan['plate_id'],save)
            result=self.h.wait(prepared,ticket,save,lambda:run.stopped() or time.monotonic()>deadline,
                lambda state:check())
            if result.get('ok') is not True:raise TeachingError('Physical completion not verified.')
            record.update(status='experiment_completed',physical_result=result);self.author.save(record)
            done.append('Exact physical Hamilton job completed')
            result=dict(ok=True,active=False,step=None,done=done,error='',message='Hamilton simulation and physical experiment completed. Plate remains at Hamilton.')
            if composed:
                return dict(result,physical_ticket=deepcopy(record['physical_ticket']),execution_binding=deepcopy(prepared),
                    record=str(self.author.path(record['draft_id'])))
        except Exception as error:
            detail=str(error)
            if record is not None:
                record.update(status='failed_or_uncertain',error=detail)
                try:self.author.save(record)
                except Exception as save_error:detail+=' Record save failed: '+str(save_error)
            result=dict(ok=False,active=False,step=None,done=done,error=detail,message='Hamilton experiment stopped: '+detail+' Nothing was retried.')
            if composed:raise TeachingError(detail) from error
        with self.agent.lock:self.agent.run_state=deepcopy(result)
        self.agent._say('lacry',result['message'])
        return result
