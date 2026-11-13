"""The same ordered contracts/instrument phases from a registered custody receipt."""
from copy import deepcopy
from uuid import uuid4

from capability_workflow import CapabilityAdapter
from composed_instrument_chain import prepare, steps, execute, verify
from researcher_teaching import TeachingError
from workflow_capabilities import compose_ordered


class RegisteredPlateAdapter(CapabilityAdapter):
    def preview_operations(self,operations,profile=None,plate_id=None,*,chain_id=None,**inputs):
        base=super().preview([],profile,plate_id,chain_id=chain_id,checkpoint_only=True)
        state=dict(base['source']['state'],registered=True)
        composition=compose_ordered(operations,state,base['plate_profile'])
        caps=[x['capability'] for x in composition['capabilities']]
        stations=list(dict.fromkeys(c['station'] for c in caps if 'station' in c))
        request=dict(inputs,operations=list(operations),source_state=state,composition=composition,stations=stations)
        chain=prepare(self.backend,request,self.agent)
        base.update(operations=list(operations),instrument_chain=chain,continuation=dict(acceptance=base['acceptance_sha256']),
                    destination=composition['final']['plate_location'],inputs=deepcopy(inputs))
        return base

    def verify(self,spec):
        fresh=self.preview_operations(spec['operations'],spec['plate_profile'],spec['plate_id'],
            chain_id=spec['chain_id'],**spec['inputs'])
        for key in ('start','joints','axes'):
            if any(abs(fresh[key][k]-v)>.05 for k,v in spec[key].items()):
                raise TeachingError('Starting state changed after workflow planning.')
            fresh[key]=spec[key]
        if fresh!=spec:raise TeachingError('Workflow contracts, inputs or custody changed after planning.')
        verify(self.backend,spec['instrument_chain'],agent=self.agent)
        return fresh

    @staticmethod
    def steps(spec):return steps(spec['instrument_chain'])

    def execute_step(self,run,spec,step,prior):return execute(self,run,spec,step,prior)


def propose(agent,operations,profile=None,plate_id=None,**inputs):
    owner=agent.workflow_composition
    owner.idle()
    plan_id=uuid4().hex
    adapter=RegisteredPlateAdapter(agent,folder=owner.folder)
    spec=adapter.preview_operations(operations,profile,plate_id,chain_id=plan_id,**inputs)
    chain=spec['instrument_chain']
    review={}
    h=chain['hamilton'];s=chain['imaging']
    if h:review['hamilton']=(h['protocol_review'] if h.get('mode')=='simulate_execute' else
        dict(recipe=h['protocol'],protocol_id=h['recipe']['protocol_id'],protocol_hash=h['recipe']['protocol_hash']))
    if s:review['squid']=dict(settings=s['profile'].get('selected_settings'),profile_hash=s['profile_hash'],
        simulation=s.get('simulation'),stage_simulated=s.get('stage_simulated'),requested_images=inputs.get('image_count'))
    bound_steps=[dict(s,kind='workflow') for s in adapter.steps(spec)]
    plan=dict(id=plan_id,at=owner.clock(),dispatch='workflow_composition',executable=True,blockers=[],location_schema=2,
        summary='Complete the requested operations on plate '+spec['plate_id']+'; finish with the plate at '+spec['destination']+'.',
        labels=[s['label'] for s in bound_steps],steps=bound_steps,composition=spec,protocol_review=review,
        requested_operations=list(operations),capability_trace=chain['request']['composition']['trace'],requirements=[
            'One human confirmation covers every displayed handling and instrument operation, including conditional live execution after exact successful simulation when shown.',
            'Confirm the displayed plate custody, empty jaws, unchanged routes, clear holders/access, and the exact source liquids, destination contents and unused tip inventory.',
            'The approved workflow runs autonomously; keep the operating area clear. Stop remains available.',
            f"Approval window: {chain['timeout_s']/60:g} minutes. Failure, changed inputs or uncertain completion stops without retry."])
    with agent.lock:agent.pending=plan
    agent._announce_plan(plan)
    return dict(ok=True,awaiting_confirmation=True,blocked=False,plan=agent._plan_view(plan))
