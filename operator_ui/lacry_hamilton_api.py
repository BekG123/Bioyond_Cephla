"""Full API discovery; reviewed single requests through the console-owned adapter."""
from copy import deepcopy
import json
import time
from uuid import uuid4

from dilution_protocol import obj
from hamilton_api_catalog import HamiltonCatalog
from hamilton_prep import digest
from researcher_teaching import TeachingError

RULES='''
Hamilton has a full native API catalog, not just a local recipe list. Use
get_hamilton_api_catalog to search capabilities and get_hamilton_api_operation
for exact endpoint inputs. read_hamilton_api performs classified read-only
requests. plan_hamilton_api_request proposes one schema-checked native request
for the HUMAN to approve using the existing Yes/No controls; never claim that
an acknowledgment proves a physical task finished. Never invent parameters or
send credentials, passwords or human signatures through model tools.
For pipetting, use draft_protocol followed by plan_hamilton_experiment for one
approval covering simulation and conditional execution (no commissioning gate),
or existing commissioned recipes with plan_hamilton/composed experiments.
Do not bypass exact-job tracking and reviewed
inventory with raw protocol-run requests. Native methods are visible even when
no local recipes are commissioned. Explain what remains to review rather than
saying Hamilton has no tools. Multipart imports require a file-upload adapter;
authentication and signatures remain human-operated. Full discovery does not
imply that all endpoints are suitable for automatic experimental scheduling.
'''
PARAMETERS=dict(operation=dict(type='string'),path_parameters=dict(type='object'),
    query=dict(type='object'),body={})
TOOLS=[
    dict(name='get_hamilton_api_catalog',description='Search all documented Hamilton API operations, including native protocols, labware, cameras, settings, calibration and diagnostics. No network writes.',
        input_schema=obj(dict(query=dict(type='string'),offset=dict(type='integer',minimum=0),limit=dict(type='integer',minimum=1,maximum=50)),[])),
    dict(name='get_hamilton_api_operation',description='Get exact native parameter/body/response schemas and execution classification for an operation.',input_schema=obj(dict(operation=dict(type='string')))),
    dict(name='read_hamilton_api',description='Perform a schema-checked, classified read through the existing Hamilton connection. No mutating GET or arbitrary URL allowed.',input_schema=obj(PARAMETERS,['operation'])),
    dict(name='plan_hamilton_api_request',description='Prepare ONE exact native API request for human confirmation. Does not execute it or authorize a physical continuation. Protocol starts use the reviewed protocol workflow.',
        input_schema=obj(dict(PARAMETERS,purpose=dict(type='string',minLength=1,maxLength=400)),['operation','purpose']))]
NAMES={t['name'] for t in TOOLS}


class HamiltonAPI:
    def __init__(self,agent):
        self.agent=agent
        self.catalog=HamiltonCatalog()

    @property
    def h(self):return self.agent.backend.instrument

    def run_tool(self,name,args):
        try:
            if name=='get_hamilton_api_catalog':result=self.catalog.search(**args)
            elif name=='get_hamilton_api_operation':result=self.catalog.detail(args['operation'])
            elif name=='read_hamilton_api':result=self.read(**args)
            elif name=='plan_hamilton_api_request':result=self.propose(**args)
            else:raise TeachingError('Unknown Hamilton API tool.')
            return json.dumps(result,allow_nan=False),False
        except Exception as error:return json.dumps(dict(ok=False,refused=str(error),no_write_dispatched=True)),True

    def read(self,operation,**kwargs):
        if self.catalog.policy(operation)!='read':raise TeachingError('This operation is not a classified read. Inspect its catalog access and use its human-reviewed workflow.')
        request=self.catalog.request(operation,**kwargs)
        path,method,op=self.catalog.operation(operation)
        binary=any('image/' in k or 'octet-stream' in k or 'application/pdf' in k or 'application/zip' in k
            for response in op.get('responses',{}).values() for k in response.get('content',{}))
        if binary:raise TeachingError('Binary response: use the existing camera/report viewer. This text API does not send binary files to the model.')
        result=self.h.call(**request)
        # Keep large definitions available without silently truncating JSON.
        if len(json.dumps(result,default=str))>100000:raise TeachingError('Response exceeds the model tool limit; narrow the query or select a specific item.')
        return dict(ok=True,operation=operation,result=result,read_only=True)

    def available(self):
        runner=self.agent.get_runner()
        if runner.active or getattr(runner,'reserved',False) or self.agent.review or self.agent.lab_api.active:
            raise TeachingError('Another operation owns the lab.')

    def propose(self,operation,purpose,**kwargs):
        self.available()
        # A refused new proposal must not leave a different old action waiting
        # behind the researcher's next Yes.
        with self.agent.lock:self.agent.pending=None
        if not isinstance(purpose,str) or not 1<=len(purpose.strip())<=400:raise TeachingError('Describe the intended operation.')
        policy=self.catalog.policy(operation)
        if policy!='human_confirmed_request':
            raise TeachingError('Operation access is '+policy+'. Use the indicated read, reviewed protocol, or operator workflow.')
        request=self.catalog.request(operation,**kwargs)
        self.h.preflight()
        # Conservative existing arm-clear check; no new motion route is created.
        if self.catalog.needs_completion_review(operation):self.agent.hamilton_workflow().arm_clear()
        plan=dict(id=uuid4().hex,at=time.time(),dispatch='hamilton_api',operation=operation,
            arguments=deepcopy(kwargs),request=request,request_hash=digest(request),schema_hash=self.catalog.hash,
            session_id=self.h.session,settings_hash=digest(self.h.settings()),summary=purpose,
            executable=True,repetitions=1,labels=[purpose],steps=[dict(kind='hamilton_api',label=purpose)],
            requirements=['Approve exactly the displayed Hamilton API request and parameters.',
                'For hardware operations: instrument area and all motion clear, hands clear, E-stop supervised.',
                'No automatic retry. An API acknowledgment alone does not authorize plate handling or prove physical completion.'],
            protocol_review=dict(kind='hamilton_api',operation=operation,request=request,
                schema_hash=self.catalog.hash,completion='Physical completion needs separate verification.' if self.catalog.needs_completion_review(operation) else 'Synchronous API response; not a physical-run receipt.'))
        with self.agent.lock:self.agent.pending=plan
        self.agent._announce_plan(plan)
        return dict(ok=True,awaiting_confirmation=True,plan=self.agent._plan_view(plan))

    def verify(self,plan):
        if plan.get('confirmation_source') not in ('researcher_chat','researcher_button'):raise TeachingError('Only a person can approve an API request.')
        if not 0<=time.time()-plan['at']<=600:raise TeachingError('API approval expired.')
        current=HamiltonCatalog()
        request=current.request(plan['operation'],**plan['arguments'])
        if (current.policy(plan['operation'])!='human_confirmed_request' or current.hash!=plan['schema_hash']
                or digest(request)!=plan['request_hash'] or request!=plan['request']
                or self.h.session!=plan['session_id'] or digest(self.h.settings())!=plan['settings_hash']):
            raise TeachingError('API request, schema or connection changed. Prepare a fresh plan.')

    def start(self,plan):
        self.available();self.verify(plan)
        with self.agent.lock:
            if not self.agent.pending or self.agent.pending['id']!=plan['id']:raise TeachingError('Approval changed or was already consumed.')
            self.agent.pending=None
            self.agent.run_meta=dict(name=plan['summary'],total_steps=1)
            self.agent.run_state=dict(active=True,step=plan['summary'],done=[],ok=None,message='Sending approved Hamilton request.',error='')
        result=self.agent.get_runner().start('lacry_hamilton_api',self.execute,plan)
        if not result.get('ok'):
            with self.agent.lock:self.agent.run_state.update(active=False,ok=False,error='Lab runner unavailable.')
            raise TeachingError('Lab runner unavailable; no request sent.')
        return dict(ok=True,message='Executing the approved Hamilton API request once.')

    def execute(self,run,plan):
        attempted=False
        try:
            self.verify(plan);self.h.preflight()
            review=self.catalog.needs_completion_review(plan['operation'])
            if review:self.agent.hamilton_workflow().arm_clear()
            with self.h.owned('native_api') as ticket:
                if run.stopped():raise TeachingError('Stopped before API dispatch.')
                self.h.journal(ticket,'approval',dict(plan_id=plan['id'],source=plan['confirmation_source'],request_hash=plan['request_hash']))
                attempted=True
                response=self.h.write(ticket,**plan['request'])
                if isinstance(response,dict) and (response.get('ok') is False or response.get('isValid') is False or response.get('validationErrors')):
                    raise TeachingError('Hamilton rejected the request; inspect the journal. Nothing was retried.')
                if review:
                    # owned() persists this marker on exception: no other plan can
                    # treat an asynchronous ACK as completed instrument work.
                    ticket['status']='finished_unverified'
                    raise TeachingError('Hamilton acknowledged the request. Physical completion is unverified; inspect status and the operation journal before further work.')
                ticket['status']='completed'
                self.h.journal(ticket,'outcome',dict(status='api_request_completed',physical_completion=False))
            result=dict(ok=True,active=False,step=None,done=[plan['summary']],error='',message='Hamilton API request completed. No physical completion is inferred.')
        except Exception as error:
            result=dict(ok=False,active=False,step=plan['summary'],done=[],error=str(error),
                message='Hamilton API stopped: '+str(error)+' No automatic retry.',request_attempted=attempted)
        with self.agent.lock:self.agent.run_state=deepcopy(result)
        self.agent._say('lacry',result['message'])
        return result
