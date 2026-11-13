"""Dilution authoring for Lacry. Model tools draft/preview; only human Yes executes."""
from copy import deepcopy
import json
from pathlib import Path
import re
import time
from uuid import uuid4

from dilution_protocol import SPEC_SCHEMA, AUTHORING_SCHEMA, compile_spec, verify_protocol, verify_simulation, obj
from hamilton_prep import digest
from researcher_teaching import TeachingError
from squid_bridge.state_io import atomic_write_json

RULES='''
Hamilton liquid-transfer authoring is available. For a new independent dilution, use
get_hamilton_authoring_catalog, collect the researcher's exact stock wells,
diluent identity/location, empty destination wells, dilution factors, final
volumes, initial liquid volumes/minimum remainders, fresh tip addresses and
pipetting/mixing settings, then draft_protocol. Never infer these from the
organism name or treat a historical dry-air method as a live-liquid recipe.
The first version supports Cellvis P24-1.5H-N at Hamilton site 4 and 300 uL
filtered tips (235903), one inventory cycle. For adding water/reagent to existing
culture wells, use the additions specification: exact source, destination,
volume_ul and mix_after, with initial volumes for occupied destinations. Never
claim these destinations must be empty. Read the native catalog first.
For an existing saved protocol use adopt_hamilton_protocol with its numeric ID
and a complete matching transfer specification. It binds the existing native
definition without creating or changing it, then follows simulation/review.
The deterministic compiler computes stock/diluent amounts. It does not validate
cell viability or select a mixing speed for the researcher.
For a simulation-to-execution experiment use plan_hamilton_experiment instead
of the optional separate commissioning process below; it needs one approval
and no separate physical trial or commissioning step after simulation succeeds.
For standalone authoring only, use plan_protocol_authoring(action="create") to request permission to save the
exact draft on Hamilton. After successful creation, request a SEPARATE human Yes
for action="simulate". Read get_protocol_draft for the exact-job simulation
report. Then request action="commission" with a recipe_name; the HUMAN reviews
the simulation, exact well/volume/mixing settings and one-cycle fresh inventory.
Commissioned recipes remain available to plan_hamilton/propose_experiment_plan.
The combined plan_hamilton_experiment does not require a commissioned recipe;
its initial human approval covers simulation and conditional live execution.
Standalone drafting/creation/simulation do not authorize physical pipetting.
No model tool can approve, start, commission or
retry an uncertain request. Report an uncertain result and stop.
'''
TOOLS=[dict(name='get_hamilton_authoring_catalog',description='Read native labware definitions and supported dilution schema; no instrument writes.',
    input_schema=obj(dict(labware_ids=dict(type='array',items=dict(type='integer',minimum=1),maxItems=8)),[])),
    dict(name='reconcile_hamilton_validation',description='Reconcile a stopped composed workflow only when the last uncertain request was protocol validation and no simulation or physical job was sent. Read back the exact approved method and verify completed delivery/current arm state; archive evidence and resolve only matching local holds. No motion, native writes, simulation or approval. Returns the remaining operations for one continuation plan; never repeat transport.',
         input_schema=obj(dict(run_id=dict(type='string',pattern='^[0-9a-f]{32}$')))),
    dict(name='draft_protocol',description='Validate and save independent dilutions or additions into occupied wells locally. Collect exact liquid volumes, wells and mixing; no Hamilton writes or approval.',
         input_schema=obj(dict(spec=AUTHORING_SCHEMA))),
    dict(name='adopt_hamilton_protocol',description='Read and bind an existing native protocol by ID to a complete matching liquid-transfer specification; no native writes. Use its draft_id in plan_workflow for transport plus simulation/conditional execution, or plan_hamilton_experiment when already delivered.',
         input_schema=obj(dict(protocol_id=dict(type='integer',minimum=1),spec=AUTHORING_SCHEMA))),
    dict(name='get_protocol_draft',description='Read dilution draft, native creation status, simulation evidence and commissioning status.',
         input_schema=obj(dict(draft_id=dict(type='string')))),
    dict(name='plan_protocol_authoring',description='Propose exactly ONE action for human confirmation: create native protocol, simulate it, or commission its reviewed successful simulation as a recipe. Never executes from this tool.',
         input_schema=obj(dict(draft_id=dict(type='string'),action=dict(type='string',enum=['create','simulate','commission']),recipe_name=dict(type='string')),['draft_id','action']))]
NAMES={t['name'] for t in TOOLS}


class ProtocolAuthoring:
    def __init__(self,agent,folder=None,clock=time.monotonic):
        self.agent=agent
        self.folder=Path(folder or Path(__file__).parent/'reports/protocol_authoring')
        self.clock=clock

    @property
    def h(self):return self.agent.backend.instrument

    def path(self,identity):
        if not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{32}',identity):raise TeachingError('Use a saved draft ID.',400)
        return self.folder/identity/'draft.json'

    def read(self,identity):
        path=self.path(identity)
        if not path.is_file():raise TeachingError('Draft not found.',404)
        record=json.loads(path.read_text(encoding='utf-8'))
        if record['draft_id']!=identity or digest(record['spec'])!=record['spec_hash']:
            raise TeachingError('Draft integrity check failed.')
        if compile_spec(record['spec'],{int(k):v for k,v in record['labware'].items()})!=record['compiled']:
            raise TeachingError('Draft compilation changed. Prepare a new draft.')
        return record

    def save(self,record):atomic_write_json(self.path(record['draft_id']),record)

    def run_tool(self,name,args):
        try:
            if name=='get_hamilton_authoring_catalog':result=self.catalog(**args)
            elif name=='reconcile_hamilton_validation':
                from hamilton_validation_recovery import reconcile
                result=reconcile(self.agent,**args)
            elif name=='draft_protocol':result=self.draft(**args)
            elif name=='adopt_hamilton_protocol':result=self.adopt(**args)
            elif name=='get_protocol_draft':result=self.read(args['draft_id'])
            elif name=='plan_protocol_authoring':result=self.propose(**args)
            else:raise TeachingError('Unknown protocol-authoring tool.')
            return json.dumps(result,allow_nan=False),False
        except Exception as error:
            return json.dumps(dict(ok=False,refused=str(error),hardware_started=False)),True

    def catalog(self,labware_ids=None):
        ids=[128,8] if labware_ids is None else labware_ids
        if not isinstance(ids,list) or not 1<=len(ids)<=8 or any(type(x) is not int or x<1 for x in ids):raise TeachingError('Supply 1–8 catalog labware IDs.')
        return dict(ok=True,labware=[self.h.call('GET','labware/'+str(x)) for x in ids],spec_schema=AUTHORING_SCHEMA,
            supported='Independent dilutions or additions into occupied wells; Cellvis P24-1.5H-N at site 4; one cycle; aqueous native liquid class; fresh tips per transfer.',
            execution_paths=dict(composed='draft_protocol then plan_workflow with draft_id and all operations; one approval covers transport, creation if needed, simulation and conditional live execution',
                instrument_only='plan_hamilton_experiment with draft_id and plate_id; plate already at Hamilton; one approval',
                optional_standalone_authoring='plan_protocol_authoring for separately approved create, simulate or commission'))

    def draft(self,spec):
        if not isinstance(spec,dict) or not isinstance(spec.get('deck'),list):raise TeachingError('Supply the complete dilution specification.')
        ids=[]
        for entry in spec['deck']:
            lid=entry.get('labware_id') if isinstance(entry,dict) else None
            if type(lid) is not int or lid<1:raise TeachingError('Use exact native catalog labware IDs.')
            if lid not in ids:ids.append(lid)
        if not 1<=len(ids)<=8:raise TeachingError('Supply bounded deck labware.')
        labware={str(x):self.h.call('GET','labware/'+str(x)) for x in ids}
        identity=uuid4().hex
        spec=deepcopy(spec)
        # The unique suffix allows one post-create lookup, never an ambiguous retry.
        spec['name']=str(spec.get('name',''))[:65]+' '+identity[:8] if spec.get('name') else ''
        compiled=compile_spec(spec,{int(k):v for k,v in labware.items()})
        record=dict(draft_id=identity,at=time.time(),status='draft',spec=spec,spec_hash=digest(spec),
            labware=labware,compiled=compiled,attempts=[],hardware_started=False)
        self.save(record)
        return dict(ok=True,draft_id=identity,status='draft',summary=compiled['summary'],
            tips_required=compiled['tips_required'],pipetting=spec['pipetting'],remaining_volumes=compiled['remaining_volumes'],
            next='Use draft_id in plan_workflow for the complete transport/instrument chain, or plan_hamilton_experiment for an already delivered plate. Both use one approval for simulation and conditional execution. No instrument write has occurred.')

    def available(self):
        run=self.agent.get_runner()
        if run.active or getattr(run,'reserved',False) or self.agent.review or self.agent.lab_api.active:
            raise TeachingError('Another lab operation or inspection is active.')

    def adopt(self,protocol_id,spec):
        self.available()
        if type(protocol_id) is not int or protocol_id<1:raise TeachingError('Choose a native protocol ID.')
        native=self.h.call('GET','protocols/'+str(protocol_id))
        if not isinstance(spec,dict) or not isinstance(spec.get('deck'),list):raise TeachingError('Supply the exact reviewed transfer specification.')
        ids={entry.get('labware_id') for entry in spec['deck'] if isinstance(entry,dict)}
        if not 1<=len(ids)<=8 or any(type(x) is not int or x<1 for x in ids):raise TeachingError('Use native labware IDs.')
        labware={str(x):self.h.call('GET','labware/'+str(x)) for x in ids}
        compiled=compile_spec(spec,{int(k):v for k,v in labware.items()})
        verify_protocol(native,compiled,spec)
        identity=uuid4().hex
        record=dict(draft_id=identity,at=time.time(),status='created',spec=deepcopy(spec),spec_hash=digest(spec),
            labware=labware,compiled=compiled,attempts=[],hardware_started=False,origin='existing_native_protocol',
            protocol_id=protocol_id,protocol=native,protocol_hash=digest(native))
        self.save(record)
        return dict(ok=True,draft_id=identity,status='created',protocol_id=protocol_id,protocol_hash=digest(native),
            message='Existing protocol bound without modifying it. Review and approve native simulation next.')

    def verify_catalog(self,record):
        for identity,definition in record['labware'].items():
            if digest(self.h.call('GET','labware/'+identity))!=digest(definition):
                raise TeachingError('Hamilton labware changed since drafting.')

    def propose(self,draft_id,action,recipe_name=''):
        self.available()
        with self.agent.lock:self.agent.pending=None
        record=self.read(draft_id)
        needed={'create':'draft','simulate':'created','commission':'simulated'}
        if action not in needed or record['status']!=needed[action]:
            raise TeachingError('This action requires status '+needed.get(action,'create/simulate/commission')+'. No retry of a completed or uncertain action.')
        if action=='commission' and (not isinstance(recipe_name,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}',recipe_name)):
            raise TeachingError('Choose a new recipe name using letters, numbers, dots, underscores or hyphens.')
        settings=self.h.settings()
        if action=='commission' and recipe_name in settings.get('recipes',{}):raise TeachingError('Recipe name already exists; no overwrite or inventory reset.')
        self.h.preflight();self.verify_catalog(record)
        if action!='create':
            p=self.h.call('GET','protocols/'+str(record['protocol_id']))
            verify_protocol(p,record['compiled'],record['spec'])
            if digest(p)!=record['protocol_hash']:raise TeachingError('Native protocol changed since creation/simulation.')
        labels={'create':'Save this liquid-transfer protocol on Hamilton (no pipetting)',
                'simulate':'Run Hamilton native simulation only (no physical pipetting)',
                'commission':'Commission the reviewed liquid transfers as a one-cycle recipe (no pipetting)'}
        requirements=['Review every source and destination, initial/final volume, calculated addition or dilution and pipetting/mixing setting below.',
            'This approval covers only '+action+'. Physical execution needs a separate plan and approval.']
        if action=='simulate':requirements.append('Approve simulated loading using the displayed volumes and fresh tip addresses. Keep other Hamilton work stopped.')
        if action=='commission':requirements.extend([
            'Review the successful exact-job simulation report and native protocol hash. Confirm this liquid class and the pipetting/mixing heights and speed are suitable for your samples.',
            'Confirm the exact deck labware, fresh tip addresses, starting liquid volumes and minimum remainders for ONE physical cycle. The transported Cellvis plate is at site 4; locations must match the native geometry.',
            'Simulation is not evidence of cell viability or physical wet-run acceptance. The first liquid run remains supervised.'])
        plan=dict(id=uuid4().hex,at=time.time(),dispatch='protocol_authoring',action=action,draft_id=draft_id,
            draft_hash=digest(record),session_id=self.h.session,settings_hash=digest(settings),recipe_name=recipe_name,
            executable=True,summary=labels[action],labels=[labels[action]],steps=[dict(kind='protocol_authoring',label=labels[action])],
            requirements=requirements,repetitions=1,protocol_review=dict(kind='dilution_authoring',action=action,
                draft_id=draft_id,name=record['spec']['name'],recipe_name=recipe_name,
                dilution_table=record['compiled']['summary'],transfer_kind='addition' if 'additions' in record['spec'] else 'dilution',deck=record['spec']['deck'],tip_site=record['spec']['tip_site'],
                tip_wells=record['spec']['tip_wells'],initial_volumes=record['spec']['initial_volumes'],
                pipetting=record['spec']['pipetting'],protocol_hash=record.get('protocol_hash'),simulation=record.get('simulation_report')))
        with self.agent.lock:self.agent.pending=plan
        self.agent._announce_plan(plan)
        return dict(ok=True,awaiting_confirmation=True,plan=self.agent._plan_view(plan))

    def start(self,plan):
        self.available()
        if plan.get('confirmation_source') not in ('researcher_chat','researcher_button'):
            raise TeachingError('Only the researcher can approve this action.')
        record=self.read(plan['draft_id'])
        if digest(record)!=plan['draft_hash'] or self.h.session!=plan['session_id'] or digest(self.h.settings())!=plan['settings_hash']:
            raise TeachingError('Draft, connection or recipe settings changed; review a fresh plan.')
        if time.time()-plan['at']>600:raise TeachingError('Approval plan expired.')
        with self.agent.lock:
            if not self.agent.pending or self.agent.pending['id']!=plan['id']:raise TeachingError('Approval already consumed or changed.')
            self.agent.pending=None
            self.agent.run_meta=dict(name=plan['summary'],total_steps=1)
            self.agent.run_state=dict(active=True,step=plan['summary'],done=[],ok=None,message='Preparing approved '+plan['action']+'.',error='')
        result=self.agent.get_runner().start('lacry_protocol_authoring',self.execute,plan)
        if not result.get('ok'):
            self.agent.run_state.update(active=False,ok=False,error='Another task owns the runner.')
            raise TeachingError('Another task owns the lab. No authoring command sent.')
        return dict(ok=True,message='Running approved '+plan['action']+' only; no physical pipetting authorized.')

    def execute(self,run,plan):
        record=None
        def check():
            if run.stopped():raise TeachingError('Protocol authoring stopped; no automatic retry.')
        try:
            record=self.read(plan['draft_id'])
            check()
            if digest(record)!=plan['draft_hash']:raise TeachingError('Draft changed before dispatch.')
            self.h.preflight();self.verify_catalog(record)
            if self.h.session!=plan['session_id'] or digest(self.h.settings())!=plan['settings_hash']:
                raise TeachingError('Hamilton connection/settings changed before dispatch.')
            record['attempts'].append(dict(action=plan['action'],plan_id=plan['id'],confirmed_by=plan['confirmation_source'],at=time.time()))
            record['status']='executing_'+plan['action'];self.save(record)
            with self.h.owned('protocol_authoring_'+plan['action']) as ticket:
                if plan['action']=='create':self.create(record,ticket,check)
                elif plan['action']=='simulate':self.simulate(record,ticket,check,run)
                else:self.commission(record,plan,check)
                ticket['status']='completed'
                self.h.journal(ticket,'outcome',dict(status='completed',draft_id=record['draft_id']))
            self.save(record)
            next_step={'create':'Native protocol saved. Review it, then ask to simulate this draft.',
                'simulate':'Simulation verified. Review the report, then ask to commission a named recipe.',
                'commission':'Recipe commissioned for one reviewed inventory cycle. Ask Lacry to plan its execution.'}[plan['action']]
            result=dict(ok=True,active=False,step=None,done=[plan['summary']],error='',message=next_step)
        except Exception as error:
            detail=str(error)
            if record is not None:
                record.update(status='failed_or_uncertain',error=detail)
                try:self.save(record)
                except Exception as log_error:detail+=' Evidence save also failed: '+str(log_error)
            result=dict(ok=False,active=False,step=plan['summary'],done=[],error=detail,message='Protocol authoring stopped: '+detail+' Nothing was retried.')
        with self.agent.lock:self.agent.run_state=deepcopy(result)
        self.agent._say('lacry',result['message'])
        return result

    def create(self,record,ticket,check):
        body=record['compiled']['protocol']
        if any(p['name']==body['name'] for p in self.h.call('GET','protocols')):raise TeachingError('Native name already exists; creation will not be repeated.')
        check();self.h.write(ticket,'POST','protocols',body)
        matches=[p for p in self.h.call('GET','protocols') if p['name']==body['name']]
        if len(matches)!=1:raise TeachingError('Creation identity is uncertain; do not resend.')
        pid=matches[0]['id'];record['protocol_id']=pid;self.save(record)
        p=self.h.call('GET',f'protocols/{pid}')
        tip_group=next(x['labwareGroup']['id'] for x in p['deck']['positions'] if x['position']==record['spec']['tip_site'])
        for step in record['compiled']['steps']:
            check();body=deepcopy(step);body['tipLabwareGroupId']=tip_group
            self.h.write(ticket,'POST',f'protocols/{pid}/step',body)
        check()
        record['validation_phase']=dict(protocol_id=pid,request_id=ticket['request_id'],status='requested',at=time.time())
        self.save(record)
        previous_status=ticket['status']
        try:self.h.write(ticket,'GET',f'protocols/validate/{pid}')
        except Exception as error:
            from hamilton_validation_recovery import is_timeout
            if not is_timeout(error):raise
            # Never resend validation, creation, or a step append. Prove the
            # exact saved method through bounded read-only reconciliation.
            p=self.validated_readback(record,check)
            check()
            self.h.journal(ticket,'validation_reconciled',dict(protocol_id=pid,protocol_hash=digest(p),
                evidence='Exact approved method read back valid; no validation request resent.'))
            ticket['status']=previous_status
            record['validation_phase'].update(status='reconciled',original_error=str(error))
        else:
            check();p=self.h.call('GET',f'protocols/{pid}')
            verify_protocol(p,record['compiled'],record['spec'])
            record['validation_phase']['status']='confirmed'
        record.update(status='created',protocol=p,protocol_hash=digest(p))
        self.save(record)

    def validated_readback(self,record,check,timeout_s=45):
        """Only GET the saved definition/job state; never repeat a mutation."""
        from hamilton_validation_recovery import is_timeout
        pid=record['protocol_id'];deadline=self.clock()+timeout_s
        for attempt in range(30):
            check()
            try:
                p=self.h.call('GET',f'protocols/{pid}')
                if p.get('id')!=pid:raise TeachingError('Validation readback returned a different protocol ID.')
                # Check structure even while native validation is still pending.
                verify_protocol(dict(p,isValid=True,validationErrors=[]),record['compiled'],record['spec'])
                if p.get('validationErrors'):raise TeachingError('Hamilton protocol validation failed: '+str(p['validationErrors']))
                if p.get('isValid') is True:
                    current=self.h.call('GET','protocol-run')
                    if current.get('isRunInProgress') is not False or current.get('protocolId') not in (0,None):
                        raise TeachingError('Hamilton job state changed during validation recovery.')
                    check();self.verify_catalog(record)
                    verify_protocol(p,record['compiled'],record['spec'])
                    return p
            except Exception as error:
                if not is_timeout(error):raise
            if self.clock()>=deadline:break
            self.h.sleep(min(1,max(0,deadline-self.clock())))
        raise TeachingError('Validation readback did not prove the exact method valid within the recovery window; no request was repeated.')

    def simulate(self,record,ticket,check,run):
        pid=record['protocol_id'];p=self.h.call('GET',f'protocols/{pid}')
        verify_protocol(p,record['compiled'],record['spec'])
        if digest(p)!=record['protocol_hash']:raise TeachingError('Protocol hash changed before simulation.')
        previous=self.h.call('GET','protocol-run').get('runDatalId')
        deadline=self.clock()+900;sent=False;job=None
        with self.h.events(self.h) as stream:
            baseline={e['id'] for e in self.h.call('GET','errors?offset=0&limit=30').get('items',[])}
            check();self.h.write(ticket,'POST','protocol-run/create',dict(protocolId=pid,simulate=True,recompile=False))
            while self.clock()<deadline:
                check();self.h.consume(stream,ticket);self.h.guard_errors(ticket,baseline)
                current=self.h.call('GET','protocol-run');state=self.h.call('GET','instruments/global-run-state')
                if sent and job and not current.get('isRunInProgress') and state=='Idle':
                    result=self.h.call('GET','run-data/'+str(job))
                    verify_simulation(result,job,p,record['compiled'])
                    if digest(self.h.call('GET',f'protocols/{pid}'))!=record['protocol_hash']:
                        raise TeachingError('Protocol changed while simulating.')
                    record.update(status='simulated',simulation_result=result,simulation_report=dict(job_id=job,
                        protocol_hash=record['protocol_hash'],status='verified',transfer_count=len(record['compiled']['transfers']),
                        tips_required=record['compiled']['tips_required'],summary=record['compiled']['summary'],physical_run=False))
                    return
                if current.get('protocolId')!=pid:
                    if not sent and current.get('protocolRunState') in (0,10,15,'Idle','Scheduling','Scheduled'):
                        self.h.sleep(.5);continue
                    raise TeachingError('Simulation run identity changed.')
                if current.get('isSimulation') is not True:raise TeachingError('Hamilton did not confirm simulation mode. No load command sent.')
                observed=current.get('runDatalId')
                if observed:
                    if observed==previous or (job and job!=observed):raise TeachingError('Stale or switched simulation job.')
                    job=observed;record['simulation_job_id']=job
                if current.get('protocolRunState') in (20,'Loading') and not sent and job:
                    instructions=self.h.call('GET','protocol-run/load-instructions')
                    tips=[x for x in instructions if x.get('deckPosition')==record['spec']['tip_site']]
                    if sum(x.get('count',0) for x in tips)!=record['compiled']['tips_required']:
                        raise TeachingError('Simulation requests an unexpected tip count.')
                    record['load_instructions']=instructions;record['load_instructions_hash']=digest(instructions);self.save(record)
                    load=deepcopy(record['compiled']['load_complete']);load.update(protocolId=pid,simulate=True,loadCompleteAction='Run')
                    check();sent=True;self.h.write(ticket,'PUT','protocol-run/load-complete',load)
                    run.say('Native dilution simulation running; waiting for its exact job result.')
                self.h.sleep(.5)
        raise TeachingError('Simulation timed out; outcome unknown. No retry or physical execution.')

    def commission(self,record,plan,check):
        p=self.h.call('GET','protocols/'+str(record['protocol_id']))
        if digest(p)!=record['protocol_hash']:raise TeachingError('Protocol changed since simulation.')
        verify_protocol(p,record['compiled'],record['spec'])
        verify_simulation(record['simulation_result'],record['simulation_report']['job_id'],p,record['compiled'])
        if record['simulation_report']['protocol_hash']!=record['protocol_hash']:raise TeachingError('Simulation hash mismatch.')
        settings=self.h.settings()
        if digest(settings)!=plan['settings_hash']:raise TeachingError('Recipe config changed before commissioning.')
        name=plan['recipe_name']
        if name in settings.get('recipes',{}):raise TeachingError('Recipe already exists; no overwrite.')
        recipe=dict(reviewed=True,protocol_id=record['protocol_id'],protocol_hash=record['protocol_hash'],
            plate_profile=record['spec']['plate_profile'],transported_plate_site=4,
            inventory_id='dilution-'+record['draft_id'],cycle_loads=[dict(load_instructions_hash=record['load_instructions_hash'],
                load_complete=record['compiled']['load_complete'])],
            authoring_draft_id=record['draft_id'],simulation_job_id=record['simulation_report']['job_id'],
            review=dict(source=plan['confirmation_source'],plan_id=plan['id'],at=time.time()),
            qualification='human-reviewed native simulation; supervised first wet run required')
        settings.setdefault('recipes',{})[name]=recipe
        check();atomic_write_json(self.h.config,settings)
        record.update(status='commissioned',recipe_name=name,recipe=recipe)
