"""Researcher-facing single-plate plans. Model tools cannot approve or start."""
from copy import deepcopy
import json
from pathlib import Path
import time
from uuid import uuid4

from labfacade import HumanConsole, Signer
from labfacade.events import RunFolder
from labfacade.supervised import SupervisedRun, timeline, timing_samples
from researcher_teaching import TeachingError
from supervised_experiment import CellvisExperiment

ROOT = Path(__file__).resolve().parents[1]
RULES = '''
Autonomous execution of approved experiments (HOME-holder workflow): use propose_experiment_plan
for one registered Cellvis P24-1.5H-N plate, a commissioned Hamilton recipe,
and Squid imaging with current selections. It accepts a cycle count and waits
for exact instrument jobs before retrieval. This replaces the old preview-only
plan_experiment and old IDLE-based lab roundtrip for this plate profile.
Calibration and barcode registration must already have established a fresh HOME
release receipt; do not reuse expired evidence. Ask for missing plate ID or recipe.
The plan is shown to the person; only their Yes starts it. Never approve, attest,
heartbeat, resume, retry, or clear a fault. A blocked plan remains blocked. There
is no overnight/multi-plate execution in this first version. For a new Hamilton
dilution recipe, use the separate draft_protocol and plan_protocol_authoring
review/create/simulate/commission flow before proposing this experiment.
'''
TOOLS = [dict(name='propose_experiment_plan',
    description='Preview a Cellvis HOME → Hamilton protocol → HOME → Squid imaging → HOME experiment, repeated for one registered plate. Uses commissioned recipe only. Nothing starts; human approval required.',
    input_schema=dict(type='object',properties=dict(
        plate_id=dict(type='string'),recipe=dict(type='string'),cycles=dict(type='integer',minimum=1,maximum=20),
        imaging_profile=dict(type='string'),purpose=dict(type='string')),
        required=['plate_id','recipe'],additionalProperties=False)),
    dict(name='experiment_status',description='Read the current approved experiment and its evidence. No motion or approvals.',
         input_schema=dict(type='object',properties={},additionalProperties=False)),
    dict(name='find_experiments',description='List recent single-plate experiment records, outcomes and receipt folders.',
         input_schema=dict(type='object',properties={},additionalProperties=False))]
NAMES = {t['name'] for t in TOOLS}


class ExperimentApi:
    def __init__(self,agent,*,folder=None,adapter=None,signer=None):
        self.agent=agent
        self.folder=Path(folder or ROOT/'runs'/'experiments')
        self.adapter=adapter
        self.signer=signer
        self.scheduler=None
        self.person=None

    def implementation(self):
        if self.adapter is None:
            registry=getattr(self.agent.memory,'plates',None)
            if registry is None:raise TeachingError('Registered plate memory is unavailable.')
            self.adapter=CellvisExperiment(self.agent.backend,registry)
        return self.adapter

    def run_tool(self,name,args):
        try:
            if name=='propose_experiment_plan':result=self.propose(**args)
            elif name=='experiment_status':result=self.public()
            elif name=='find_experiments':result=dict(experiments=self.find())
            else:raise TeachingError('Unknown experiment tool.')
            return json.dumps(result,default=str),False
        except Exception as error:
            return json.dumps(dict(ok=False,refused=str(error),error=str(error),motion_started=False)),True

    def find(self):
        result=[]
        for path in sorted(self.folder.glob('*/run.json'),reverse=True)[:30]:
            try:
                d=json.loads(path.read_text(encoding='utf-8'))
                state=json.loads((path.parent/'experiment_status.json').read_text(encoding='utf-8'))
                result.append(dict(id=d['run_id'],title=d['plan']['title'],plate_id=d['plan']['plate_id'],
                                   status=state['status'],record=str(path)))
            except (OSError,ValueError,KeyError):continue
        return result

    def propose(self,plate_id,recipe,cycles=1,imaging_profile=None,purpose=''):
        runner=self.agent.get_runner()
        if runner.active or getattr(runner,'reserved',False):raise TeachingError('Another lab task is running.')
        if self.agent.review:raise TeachingError('Finish the current inspection first.')
        if (self.folder/'.supervised-lab-lease.json').exists():
            raise TeachingError('An experiment has an unresolved outcome. Review its saved record before another run; no retry.')
        # Drop an obsolete pending plan even when this proposal is blocked.
        with self.agent.lock:self.agent.pending=None
        spec=self.implementation().preview(plate_id,recipe,cycles,imaging_profile=imaging_profile,purpose=purpose)
        spec=dict(spec,execution_mode='autonomous')
        preview=timeline(spec['steps'],timing_samples(p.parent for p in self.folder.glob('*/run.json')))
        for step,row in zip(spec['steps'],preview['rows']):
            step['estimate']=deepcopy(row['estimate'])
        plan=dict(id=uuid4().hex,at=time.time(),dispatch='supervised_experiment',executable=True,location_schema=2,
            summary=spec['title'],labels=[spec['title']],steps=spec['steps'],repetitions=cycles,
            experiment_plan=spec,timeline=preview,requirements=[
                'Confirm the named registered Cellvis plate is seated in HOME, jaws empty, and the calibrated setup is unchanged.',
                'Confirm Hamilton site 4 and Squid are empty, their fixtures unchanged, and all taught routes and jaw sweeps clear.',
                'Confirm Hamilton access and the reviewed recipe deck, tips and liquid inventory cover every cycle.',
                'Confirm the displayed Squid imaging selections and any simulated-camera mode.',
                'One Yes covers exactly this plan and cycle count for up to four hours. Any uncertain step stops; nothing is retried.'],
            protocol_review=dict(recipe=spec['hamilton']['protocol'],
                protocol_id=spec['hamilton']['recipe']['protocol_id'],
                protocol_hash=spec['hamilton']['recipe']['protocol_hash'],
                imaging_hash=spec['imaging']['profile_hash'],
                imaging_simulation=spec['imaging'].get('simulation'),
                imaging_selection_source=spec['imaging']['profile'].get('selection_source',{'kind':'current selections'}),
                selected_settings=spec['imaging']['profile'].get('selected_settings')))
        if spec['imaging']['profile'].get('selection_source',{}).get('kind')=='saved_coordinates':
            plan['requirements'].append('This plan uses saved imaging locations with the current acquisition controls; confirm the displayed locations.')
        with self.agent.lock:self.agent.pending=plan
        self.agent._announce_plan(plan)
        return dict(ok=True,awaiting_confirmation=True,plan=self.agent._plan_view(plan))

    def start(self,plan):
        """Called exclusively by the console's existing human confirmation path."""
        if not plan.get('confirmation_source'):
            raise TeachingError('A current human confirmation is required.')
        runner=self.agent.get_runner()
        if runner.active or getattr(runner,'reserved',False):raise TeachingError('Another lab task is running.')
        spec=deepcopy(plan['experiment_plan'])
        self.folder.mkdir(parents=True,exist_ok=True)
        self.signer=self.signer or Signer.from_file(self.folder/'.human-signing-key',create=True)
        run=RunFolder.create(self.folder,'experiment-'+uuid4().hex[:10],spec,{})
        self.person='researcher via '+plan['confirmation_source']
        console=HumanConsole(run,self.signer)
        console.approve_plan(self.person,ttl_s=max(1,spec['window']['expires_at']-time.time()))
        adapter=self.implementation()
        self.scheduler=SupervisedRun(run,self.signer,adapter.operations(),notify=self._update,custody=adapter.publish_custody)
        self.scheduler.validate()
        with self.agent.lock:
            self.agent.pending=None
            self.agent.run_meta=dict(name=spec['title'],total_steps=len(spec['steps']),timeline=plan['timeline'])
            self.agent.run_state=dict(active=True,step=None,done=[],ok=None,error='',message='Starting approved autonomous experiment.')
        result=runner.start('lacry_supervised_experiment',self._run,adapter,spec)
        if not result.get('ok'):
            self._update(dict(status='paused',error='Console runner was busy; no commands were sent.'))
            raise TeachingError('Console runner was busy; no commands were sent.')
        return dict(ok=True,run_folder=str(run.path),message='Running the approved experiment autonomously.')

    def _run(self,runner,adapter,spec):
        adapter.actual_run=runner
        adapter.motion=None
        adapter.ticket={}
        adapter.registry_revision=spec['plate_record']['revision']
        result=self.scheduler.execute()
        try:
            adapter.record_experiment_result(self.scheduler.run,result)
        except Exception as error:
            self.scheduler.run.events.emit('anomaly',status='registry_update_failed',data=dict(error=str(error)))
        self.agent._say('lacry','Experiment completed; plate returned to HOME.' if result['ok'] else
            'Experiment stopped: '+result.get('error','Unknown result')+' Nothing was retried.')
        return result

    def _update(self,event):
        labels={s['id']:s['label'] for s in self.scheduler.run.plan['steps']} if self.scheduler else {}
        with self.agent.lock:
            self.agent.run_state=dict(active=event['status']=='running',step=event.get('label',event.get('step')),
                done=[labels.get(s,s) for s in event.get('completed',[])],ok=True if event['status']=='completed' else None,
                error=event.get('error',''),message=event.get('label') or event.get('error') or event['status'])

    def public(self):
        if not self.scheduler:return dict(available=True,active=False)
        state=self.scheduler.run.read_json('experiment_status.json') or dict(status='approved')
        return dict(state,run_id=self.scheduler.run.run_id,run_folder=str(self.scheduler.run.path),
                    plates=(self.scheduler.run.read_json('ledger.json') or {}).get('plates',{}),
                    execution_mode='autonomous',
                    active=bool(self.agent.get_runner().active and self.agent.get_runner().name=='lacry_supervised_experiment'))
