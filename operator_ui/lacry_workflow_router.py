"""Model-selected goals, capability composition and legacy compound adapters.

No tools here approve, execute, connect, or substitute a partial plan. Registered
capabilities compose by state; unsupported legacy boundaries remain explicit.
"""
import json
import time
from uuid import uuid4
from researcher_teaching import TeachingError
from autonomy import TransferError
from workflow_capabilities import operations as registered_operations

MAINTENANCE = ('hamilton_initialize','hamilton_self_calibration',
               'hamilton_channel_calibration','hamilton_full_calibration','arm_full_calibration')
OPERATIONS = MAINTENANCE + ('retrieve_hotel','register_plate','hamilton_protocol',
    'deliver_hamilton','retrieve_hamilton','deliver_squid','squid_image','retrieve_squid','return_HOME')
OPERATIONS = tuple(dict.fromkeys(OPERATIONS + tuple(sorted(registered_operations()))))

TOOLS = [dict(name='get_workflow_catalog',
    description='Read available workflow building blocks, compound executors and profile/receipt limits. No hardware commands.',
    input_schema=dict(type='object',properties=dict(workflow=dict(type='string',description='Optional installed workflow/tool name: return its complete input schema. Omit for the discoverable index and composition contracts.')),additionalProperties=False)),
    dict(name='plan_workflow',
    description='Infer the ordered operations from a compound researcher request and submit them here as one plan. Delegates supported chains to existing executors, retains all goals on blockers, never starts hardware. Hotel-to-Squid always includes fresh registration. No model approval fields.',
    input_schema=dict(type='object',properties=dict(
        operations=dict(type='array',minItems=1,maxItems=20,items=dict(type='string'),description='Ordered operation names from the current get_workflow_catalog contracts; validated against the live registry.'),
        plate_profile=dict(type='string',enum=['Cellvis P24-1.5H-N','48_well_projected_20261026']),
        plate_id=dict(type='string',minLength=1),source_slot=dict(type='integer',enum=[1,2,3]),
        cycles=dict(type='integer',minimum=1,maximum=20),recipe=dict(type='string'),
        draft_id=dict(type='string',description='Saved Hamilton draft: one approval includes creation if needed, exact native simulation, then conditional live execution. Alternative to recipe.'),
        imaging_profile=dict(type='string'),image_count=dict(type='integer',minimum=1,maximum=10000,
            description='Requested total images, checked against the selected Squid snapshot; never use cycles for image count.'),purpose=dict(type='string')),
        required=['operations'],additionalProperties=False))]
NAMES={t['name'] for t in TOOLS}


def catalog(agent=None,workflow=None):
    from workflow_discovery import discover
    if workflow is not None:return discover(agent,workflow)
    from workflow_capabilities import catalog as capability_catalog
    return dict(operations=sorted(set(MAINTENANCE)|registered_operations()),confirmation='One human confirmation per complete supported plan; no per-step Yes.',
        capability_registry=capability_catalog(),workflows=discover(agent),
        bindings=[
            dict(operations=list(MAINTENANCE),executor='CommandBatch',
                 rule='Ordered Hamilton maintenance plus at most one arm calibration; Hamilton deck prompts still require human answers.'),
            dict(operations=['hamilton_protocol','squid_image'],executor='ExperimentApi',
                 rule='Registered Cellvis plate at HOME, commissioned recipe, selected imaging. Existing scheduler inserts delivery, exact-job waits and retrieval via HOME; repeats cycles.'),
            dict(operations=['arm_full_calibration','deliver_squid','squid_image','retrieve_squid'],executor='AutonomousSquid',
                 rule='Existing automatic pickup/imaging planner checks its exact supported profile and starting state. Not a hotel adapter.'),
            dict(operations=sorted(registered_operations()),executor='WorkflowComposition',
                 rule='Compose declared plate operations by preconditions and effects. Hotel chains require fresh registration. Hamilton accepts a commissioned recipe OR draft_id for create/simulate/conditional execution. Retrieval is included only when requested or needed by a later operation; final custody is displayed.')],
        registration='A fresh decode saved to registry is required for hotel-to-instrument transfer. An expected ID is optional; mismatch/no-read stops. Never infer contents from a barcode.',
        unknown_combinations='Registered handling orders are composed by state. A missing precondition, receipt or executor contract is reported against the full request; never execute a prefix or silently drop an operation.')


class WorkflowRouter:
    def __init__(self,agent):self.agent=agent

    def run_tool(self,name,args):
        try:
            result=catalog(self.agent,**args) if name=='get_workflow_catalog' else self.propose(**args)
            return json.dumps(result,default=str),False
        except Exception as error:
            return json.dumps(dict(ok=False,error=str(error),motion_started=False)),True

    def blocked(self,operations,reason,cycles):
        plan=dict(id=uuid4().hex,at=time.time(),dispatch='workflow_unbound',executable=False,
                  location_schema=2,summary=' → '.join(operations),repetitions=cycles,
                  steps=[dict(kind='workflow',label=op) for op in operations],
                  labels=list(operations),requirements=[],blockers=[reason])
        with self.agent.lock:self.agent.pending=plan
        self.agent._announce_plan(plan)
        return dict(ok=True,blocked=True,awaiting_confirmation=False,plan=self.agent._plan_view(plan))

    def propose(self,operations,plate_profile=None,plate_id=None,source_slot=None,cycles=1,
                recipe=None,imaging_profile=None,purpose='',image_count=None,draft_id=None):
        self.agent.workflow_composition.idle()
        with self.agent.lock:self.agent.pending=None
        if (not isinstance(operations,list) or not 1<=len(operations)<=20 or
                any(not isinstance(op,str) or op not in set(MAINTENANCE)|registered_operations() for op in operations)):
            raise TeachingError('Choose ordered operations from get_workflow_catalog.')
        if type(cycles) is not int or not 1<=cycles<=20:raise TeachingError('Cycles must be 1–20.')
        if image_count is not None and (type(image_count) is not int or not 1<=image_count<=10000 or 'squid_image' not in operations):
            raise TeachingError('Image count must be 1 to 10000 and requires Squid imaging.')
        if recipe and draft_id:raise TeachingError('Choose a commissioned recipe OR a saved draft, not both.')
        if source_slot is not None:
            from workflow_capabilities import compose_hotel
            try:
                if cycles!=1:raise TeachingError('Repeated hotel retrieval needs an explicit return-to-slot executor and custody binding between cycles.')
                if not plate_profile:raise TeachingError('Supply the physical plate profile in the source slot.')
                compiled=compose_hotel(operations,plate_profile,source_slot)
                caps=[x['capability'] for x in compiled['capabilities']]
                stations=list(dict.fromkeys(c['station'] for c in caps if 'station' in c))
                jobs={c['executor'] for c in caps}
                if (recipe or draft_id) and 'hamilton_job' not in jobs:raise TeachingError('Hamilton inputs require a hamilton_protocol operation.')
                if imaging_profile and 'squid_job' not in jobs:raise TeachingError('Imaging settings require a squid_image operation.')
                request=dict(operations=operations,composition=compiled,stations=stations,recipe=recipe,draft_id=draft_id,
                    imaging_profile=imaging_profile,image_count=image_count,purpose=purpose)
                # Every registered hotel order uses the same contract-driven adapter.
                return self.agent.workflow_composition.propose(plate_profile,source_slot,stations[0] if stations else 'HOME',plate_id,
                    instrument_request=request if len(caps)>1 else None)
            except (TeachingError,TransferError,ValueError) as error:
                return self.blocked(operations,str(error),cycles)
        if (set(operations)<=registered_operations() and any(op in ('hamilton_protocol','squid_image') for op in operations)
                and plate_profile in (None,'Cellvis P24-1.5H-N') and cycles==1):
            try:
                if (recipe or draft_id) and 'hamilton_protocol' not in operations:raise TeachingError('Hamilton inputs require hamilton_protocol.')
                if imaging_profile and 'squid_image' not in operations:raise TeachingError('Imaging settings require squid_image.')
                from composed_operations import propose
                return propose(self.agent,operations,plate_profile,plate_id,recipe=recipe,draft_id=draft_id,
                    imaging_profile=imaging_profile,image_count=image_count,purpose=purpose)
            except (TeachingError,TransferError,ValueError) as error:
                return self.blocked(operations,str(error),cycles)
        if draft_id:
            return self.blocked(operations,'A draft binding supports one Hamilton job in a composed plate workflow; repeated liquid work needs separately bound inventory.',cycles)
        if image_count is not None:
            return self.blocked(operations,'An explicit image count requires the composable Cellvis instrument planner; this requested profile/repetition needs its own count binding.',cycles)
        from workflow_capabilities import operations as capability_operations
        if set(operations) <= capability_operations('cellvis_station_phase'):
            from capability_workflow import CapabilityWorkflow
            try:
                if recipe or draft_id or imaging_profile:
                    raise TeachingError('This requested chain contains handling only; include the instrument operation to use its recipe or imaging profile.')
                return CapabilityWorkflow(self.agent).propose(operations,plate_profile,plate_id,cycles)
            except (TeachingError, TransferError, ValueError) as error:
                return self.blocked(operations,str(error),cycles)
        if all(op in MAINTENANCE for op in operations) and any(op.startswith('hamilton_') for op in operations):
            if cycles!=1:return self.blocked(operations,'Repeated calibration requires renewed deck/empty-gripper setup; choose one maintenance batch.',cycles)
            plan=self.agent.command_batch_workflow().propose(operations)
        elif operations==['arm_full_calibration']:
            if cycles!=1:return self.blocked(operations,'Repeated pickup calibration needs a plate-return adapter; no implicit reset.',cycles)
            plan=self.agent.propose(['full_calibration'])
        elif operations in (['hamilton_protocol','squid_image'],
                ['hamilton_protocol','deliver_squid','squid_image','retrieve_squid','return_HOME']):
            if plate_profile!='Cellvis P24-1.5H-N' or not plate_id or not recipe:
                raise TeachingError('This experiment needs the registered Cellvis plate ID and a commissioned Hamilton recipe. Ask for missing values; do not substitute a dry mock.')
            return self.agent.experiment_api.propose(plate_id,recipe,cycles,imaging_profile,purpose)
        elif operations in (['deliver_squid','squid_image','retrieve_squid'],
                            ['arm_full_calibration','deliver_squid','squid_image','retrieve_squid']):
            if plate_profile!='48_well_projected_20261026':
                return self.blocked(operations,'This automatic pickup/imaging adapter uses the 48-well workflow. '
                    'A Cellvis imaging-only chain needs its own profile-bound adapter; do not substitute calibration or gripper settings.',cycles)
            plan=self.agent.automatic_workflow().propose(protocol=imaging_profile,retrieve=True,
                pickup_from_calibration=operations[0]=='arm_full_calibration',repetitions=cycles)
        else:
            missing=[op for op in operations if op not in capability_operations()]
            return self.blocked(operations,'This request crosses executor contracts that are not composable yet. '
                'Operations outside the state-based handling registry: '+', '.join(dict.fromkeys(missing))+
                '. Their existing compound adapters are listed in get_workflow_catalog. '
                'The full requested plan is retained; no prefix will run.',cycles)
        return dict(ok=True,awaiting_confirmation=plan.get('executable',True),plan=self.agent._plan_view(plan))


def hotel_instrument_stations(operations):
    """Compatibility query over contracts, with no complete-order whitelist."""
    from workflow_capabilities import compose_hotel
    try:
        chain=compose_hotel(operations,'Cellvis P24-1.5H-N',1)
        jobs=[c['capability']['station'] for c in chain['capabilities']
              if c['capability']['executor'] in ('hamilton_job','squid_job')]
        return list(dict.fromkeys(jobs)) or None
    except TeachingError:return None
