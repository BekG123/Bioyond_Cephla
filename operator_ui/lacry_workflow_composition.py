"""Human-confirmed workflow composition on the existing shared console runner."""
from copy import deepcopy
import json
from pathlib import Path
import time
from uuid import uuid4

from hotel_squid_composition import HotelSquidAdapter, profile_binding
from researcher_teaching import TeachingError
from run_record_io import write_run_record

RULES = '''
Compose accepted workflows instead of handing executable steps back to the researcher.
For compound requests in general, read get_workflow_catalog and use plan_workflow
with the ordered operations inferred from the request. Choose the operations
yourself; ask only for missing experimental parameters or ambiguous intent.
The workflows index is generated from EVERY installed tool, including maintenance,
recovery, teaching, native APIs and specialized experiment planners. Request
get_workflow_catalog(workflow="<tool name>") for its full current input schema.
Do not treat the small operations enum as the list of all available workflows.
The capability_registry declares each composable workflow's profile, executor,
inputs, preconditions and postconditions. Compose those capabilities by state; complete
orders do not need separate hardcoded cases. Retrieval from Squid/Hamilton
already includes reseating/release in HOME. An explicit return_HOME goal after
retrieval is satisfied by that postcondition, not another movement. For a later
request to retrieve a delivered plate, call plan_workflow without source_slot;
the host resolves its identity/profile and custody from the latest complete
receipt. Do not ask for another barcode scan or a hotel slot. Historical trial
files alone are not executable capabilities; do not import arbitrary code.
Hotel registration, station phases, Hamilton jobs and Squid imaging share these
contracts. Prerequisite registration and accepted transport are expanded and shown
in the complete plan. Final plate location follows the requested operations: a
protocol does not implicitly retrieve a plate. Include return_HOME for that goal.
From a completed registered custody receipt, instrument/handling orders use the
same contracts without source_slot or another barcode scan. Discovery is not a
claim of current readiness or permission to join incompatible payload/profile
boundaries; preserve the whole request and report the precise missing contract.
This tool delegates supported combinations to the existing full executors,
including maintenance batches and Hamilton/Squid experiments. It does not ask
the person to start each successful step. Preserve all requested operations and
repetitions; never silently reduce a chain to its first step. If a combination
is not bound, display the entire proposed chain and its exact missing adapter.
For a plate in hotel slot 1, 2 or 3 going to Squid, Hamilton or HOME, use
plan_plate_transfer with plate_profile, source_slot and destination. For an immediate
handling roundtrip, set roundtrip=true; it starts no instrument job. Plate ID is
optional before registration; never demand that a person invent it. Supply it only
as an expected barcode if already known.
The required plan is hotel retrieval -> HOME -> barcode scanner -> successful
registration -> HOME -> Squid delivery/release
-> empty HOME return under one human Yes, checking every predecessor receipt.
Do not ask the researcher to run hotel retrieval manually or propose unrelated
individual plans. This transfer needs no Hamilton recipe, calibration or imaging
settings. It does not start imaging. A stored ID never replaces the fresh scan.
Use plate memory to resolve known IDs; ask if ambiguous. A no-read or identity
mismatch blocks Squid delivery. Never remove the scan to make a plan executable.
Slot 1 -> HOME retrieval is accepted for both the 48-well plate and Cellvis24,
per the operator's confirmation of the tested fixed workflow. Reuse that exact
executor; do not require new path teaching or another profile validation for it.
An unregistered plate can be retrieved by its physical slot and declared profile;
keep identity pending until scanning. Slots 2/3 retain their separate profile bindings.
If disconnected or not at the required start, report the precise setup blocker
and offer an existing connection/recovery plan; never pretend a transfer started.
The one-operation clean API restriction applies only to plan_lab_operation, not
this composition tool. Never invent approvals, successful receipts or observations.
The Cellvis slot-1 scanner handoff is now integrated: use plan_plate_transfer
for this complete chain. Do not repeat the obsolete 'hotel receipt not bound'
message. The tool checks current setup and reports any actual blocker.
At stationary HOME clearance with empty jaws and the source plate in its hotel
slot, a different holder angle is handled by a preparation step in the same
confirmed plan: open empty jaws to 28 mm, restore 1.77 degrees and verify before
retrieval. Never move the holder during planning or ask for manual rotation when
this preparation is offered. This does not permit rotating a held plate.
After hotel retrieval releases the plate in HOME and the empty arm reaches
clearance, the composed transfer verifies the original holder angle again.
Small seating deflection can be corrected once to 1.77 degrees before scanning;
failed correction stops the run. Never retry a failed run or erase its hold.
Immediately before each barcode presentation, the approved chain re-centers
the released holder to 1.77 degrees at HOME clearance and verifies fresh angle
feedback. This handles drift since the previous receipt, within the existing
0.5-degree contact band. Planning itself does not move the holder.
For hotel requests that include imaging or liquid handling, use plan_workflow,
not the handling-only plan_plate_transfer. Cellvis slot 1 registration now binds
to Hamilton's recipe OR draft simulation/execution tools and Squid's selected settings.
Use draft_protocol first for new fully specified liquid transfers, then pass its
draft_id to plan_workflow together with all requested operations. This binds native
creation if needed, simulation and conditional unchanged live execution after
delivery under ONE approval. No separate commissioning or delivery approval.
Use recipe for a commissioned method, never both recipe and draft_id. No-mix
additions require only aspiration/dispense heights; do not invent unused mix values.
The full chain includes exact-job completion waits and verified Squid loading
return. Either instrument order is supported; retrieval is included when requested
or necessary for a later operation. Supply image_count when a total is requested;
image count is not cycle count. Missing settings/recipe must be resolved before
any movement. One human Yes covers the displayed complete chain; do not ask for
another plan between its steps or repeat an obsolete missing-adapter message.
'''
TOOLS = [dict(name='plan_plate_transfer',
    description='Build the whole hotel -> HOME -> barcode registration -> HOME -> Squid or Hamilton handling plan, with optional immediate roundtrip. Shows profile-specific missing qualifications instead of asking the person to run pieces manually. Optional expected barcode; never reuse another plate identity. No recipe or imaging required. Planning sends no motion.',
    input_schema=dict(type='object', properties=dict(
        plate_id=dict(type='string', minLength=1),
        plate_profile=dict(type='string',enum=['Cellvis P24-1.5H-N','48_well_projected_20261026']),
        source_slot=dict(type='integer', enum=[1,2,3]),
        destination=dict(type='string', enum=['HOME','Squid','Hamilton']),
        roundtrip=dict(type='boolean',description='Retrieve immediately after delivery and finish with plate released HOME; handling only.')),
        required=['plate_profile','source_slot','destination'], additionalProperties=False))]


def composition_outline(profile, slot, destination, roundtrip=False):
    if type(slot) is not int or slot not in (1,2,3) or destination not in ('HOME','Squid','Hamilton'):
        raise TeachingError('Choose an accepted slot 1–3 and HOME, Squid or Hamilton destination.')
    if type(roundtrip) is not bool or (roundtrip and destination=='HOME'):
        raise TeachingError('Roundtrip requires an instrument destination.')
    if profile not in ('Cellvis P24-1.5H-N','48_well_projected_20261026'):
        raise TeachingError('Unknown plate profile; do not substitute another plate.')
    cellvis=profile=='Cellvis P24-1.5H-N'
    accepted=not cellvis or slot==1
    if accepted:profile_binding(profile,slot)
    steps=[dict(id='retrieve_hotel',label=f'Retrieve slot {slot} plate and reseat in HOME',
                skill=f'home-hotel-slot{slot}-handling-v1',
                qualification='accepted' if accepted else 'needs_profile_validation')]
    blockers=[]
    if not accepted:
        blockers.append(f'Cellvis P24-1.5H-N retrieval from slot {slot} needs a supervised profile validation; '
                        'the saved hotel acceptance is for the 48-well plate. The agent must not relabel it as Cellvis acceptance.')
    if destination!='HOME':
        steps += [dict(id='register_barcode',label='HOME → scanner: decode and register barcode → HOME',
                       skill='cellvis24-scan-station-cycle-v1',
                       qualification='accepted' if cellvis and slot==1 else 'needs_profile_validation'),
                  dict(id=('roundtrip_' if roundtrip else 'deliver_')+destination.lower(),
                       label=(f'HOME → {destination}: deliver/release, retrieve and reseat HOME' if roundtrip
                              else f'HOME → {destination}: deliver and release; return empty to HOME'),
                       skill='cellvis24-calibration-station-workflow-v1' if cellvis else 'squid-dropoff-pickup-v1',
                       qualification='accepted' if cellvis and slot==1 else 'needs_profile_validation')]
        if not cellvis:
            blockers.append('The lower scanner registration/return is accepted for Cellvis24; '
                            'the 48-well hotel-to-scanner receipt binding and return need validation.')
    return steps,blockers


class WorkflowComposition:
    def __init__(self, agent, adapter=None, folder=None, clock=time.time):
        self.agent=agent
        self.adapter=adapter or HotelSquidAdapter(agent)
        self.folder=Path(folder or Path(__file__).resolve().parents[1]/'runs'/'composed_transfers')
        self.clock=clock
        self.execution=None

    def adapter_for(self,spec):
        if spec.get('source') and spec.get('instrument_chain'):
            from composed_operations import RegisteredPlateAdapter
            return RegisteredPlateAdapter(self.agent,folder=self.folder)
        return self.adapter

    def public(self):
        run=self.agent.get_runner()
        active=bool(self.execution and run.active and run.name=='lacry_workflow_composition')
        if not active:return dict(active=False)
        return dict(active=True,status='running',run_id=self.execution['run_id'],
                    run_folder=self.execution['run_folder'],execution_mode='autonomous')

    def idle(self):
        run=self.agent.get_runner()
        if run.active or getattr(run,'reserved',False) or self.agent.lab_api.active or self.agent.review:
            raise TeachingError('Another run or inspection is active; finish it first.')
        if (self.folder/'unresolved.json').exists():
            raise TeachingError('A composed transfer has an unresolved outcome; review its record. No automatic retry.')

    def run_tool(self, args):
        try:
            return json.dumps(self.propose(**args),default=str),False
        except Exception as error:
            return json.dumps(dict(ok=False,error=str(error),motion_started=False)),True

    def propose(self, plate_profile, source_slot, destination, plate_id=None, roundtrip=False,instrument_request=None):
        self.idle()
        with self.agent.lock:self.agent.pending=None
        steps,blockers=composition_outline(plate_profile,source_slot,destination,roundtrip)
        spec=dict(plate_id=plate_id,plate_profile=plate_profile,slot=source_slot,destination=destination,roundtrip=roundtrip)
        if not blockers:
            options={'roundtrip':True} if roundtrip else {}
            if instrument_request is not None:options['instrument_request']=instrument_request
            spec=self.adapter.preview(plate_id,source_slot,destination,plate_profile,**options)
            steps=self.adapter.steps(spec)
        steps=[dict(s,kind='workflow') for s in steps]
        plan=dict(id=uuid4().hex,at=self.clock(),dispatch='workflow_composition',executable=not blockers,blockers=blockers,
            location_schema=2,summary=f'Take the {plate_profile} plate from hotel slot {source_slot} to {destination}'+(' via barcode registration' if destination!='HOME' else '')+('; then retrieve and release in HOME.' if roundtrip else '.'),
            labels=[s['label'] for s in steps],steps=steps,composition=spec,
            requirements=[
                f'Confirm the {plate_profile} plate is flat in slot {source_slot} and HOME is empty.',
                'If no barcode ID is supplied, identity stays pending until a successful scan; no existing plate identity will be reused.',
                'Arm starts at HOME clearance with empty jaws, healthy running Auto; no startup or fault reset is included.',
                'If listed, confirm the empty HOME holder rotation and opening empty jaws to 28 mm are clear; the plan restores 1.77 degrees before retrieval.',
                'After hotel release at HOME clearance, allow one correction of small holder deflection to 1.77 degrees before scanning; jaws stay open at 28 mm.',
                'Before each barcode pickup, re-center the released holder once at HOME clearance, then verify; no retry after a failed correction.',
                'Confirm unchanged rack, horizontal entry/withdrawal, 5 mm lift clearance, holder seating and all arm/claw sweeps clear.',
                ('Scan at the accepted lower position: at most five triggers per side. If the first side has no read, '
                 'return/release in HOME, rotate the released holder to 181.77 degrees, and scan the other side. '
                 'Confirm the rotation and both scanner routes are clear. Restore 1.77 degrees after scanning. '
                 'Two no-read sides return to HOME and stop.' if destination!='HOME' else 'No scanning is included; any listed empty-holder preparation happens before retrieval.'),
                ('Confirm Squid is empty, unchanged and at its verified loading position.' if destination=='Squid' else
                 'Confirm Hamilton is idle/parked, access open, site 4 empty, and the accepted opposite3 route clear.' if destination=='Hamilton' else
                 'Destination HOME holder is empty.'),
                'Handling only: no imaging or pipetting. Roundtrip retrieves immediately; do not start an instrument job during this transfer.',
                'Keep the operating area clear. One Yes covers every listed step for up to 15 minutes.',
                'Stop on any fault, timeout or uncertain grip/position; no retries. Controller receipts do not assert visual inspection.'])
        if spec.get('instrument_chain'):
            chain=spec['instrument_chain']
            finish=chain.get('final_location','HOME')
            plan['summary']=f"Retrieve the {plate_profile} plate from slot {source_slot}, register its barcode, complete the displayed operations and "+('return the plate HOME.' if finish=='HOME' else f'leave the plate at {finish}.')
            if chain['request'].get('composition'):
                plan['requested_operations']=chain['request']['operations']
                plan['capability_trace']=chain['request']['composition']['trace']
            plan['requirements']=[r for r in plan['requirements'] if not r.startswith(('Handling only:', 'Keep the operating area clear.'))]
            if spec.get('continuation'):
                plan['requirements']=[r for r in plan['requirements'] if not r.startswith('No scanning is included')]
            plan['requirements'] += [
                'One human Yes covers every displayed handling and instrument step; the approved workflow runs autonomously.',
                f"Approval window: {chain['timeout_s']/60:g} minutes; stop on expiry or uncertain completion, with no retry.",
                'Keep each station empty for delivery and unchanged. Hamilton requires reviewed deck/tip/liquid inventory, parked heads and open robot access for transfers.']
            review={}
            if chain['hamilton']:
                h=chain['hamilton'];review['hamilton']=(h['protocol_review'] if h.get('mode')=='simulate_execute' else dict(recipe=h['protocol'],protocol_id=h['recipe']['protocol_id'],protocol_hash=h['recipe']['protocol_hash']))
            if chain['imaging']:
                p=chain['imaging'];review['squid']=dict(settings=p['profile'].get('selected_settings'),profile_hash=p['profile_hash'],requested_images=chain['request'].get('image_count'),simulation=p.get('simulation'),stage_simulated=p.get('stage_simulated'),selection_source=p['profile'].get('selection_source',{'kind':'current selections'}))
            plan['protocol_review']=review
        with self.agent.lock:self.agent.pending=plan
        self.agent._announce_plan(plan)
        return dict(ok=True,awaiting_confirmation=not blockers,blocked=bool(blockers),
                    plan=self.agent._plan_view(plan),workflow_steps=steps)

    def start(self, plan):
        self.idle()
        if plan.get('executable') is not True or plan.get('blockers'):
            raise TeachingError('The composed route has unresolved qualifications; no movement was started.')
        if plan.get('confirmation_source') not in ('researcher_chat','researcher_button','researcher_terminal'):
            raise TeachingError('A current human Yes is required.')
        with self.agent.lock:
            if self.agent.pending!=plan or not 0<=self.clock()-plan['at']<=600:
                raise TeachingError('Plan changed, expired or already consumed.')
            adapter=self.adapter_for(plan['composition'])
            adapter.verify(plan['composition'])
            if plan['steps']!=[dict(s,kind='workflow') for s in adapter.steps(plan['composition'])]:
                raise TeachingError('Composition steps changed.')
            self.folder.mkdir(parents=True,exist_ok=True)
            path=self.folder/(plan['id']+'.json')
            with path.open('x',encoding='utf-8') as stream:
                json.dump(dict(status='approved',plan=plan),stream)
            if plan['composition'].get('instrument_chain'):
                self.execution=dict(run_id=plan['id'],run_folder=str(self.folder),source=plan['confirmation_source'])
            self.agent.pending=None
            self.agent.run_meta=dict(name=plan['summary'],total_steps=len(plan['steps']),plan_id=plan['id'])
            self.agent.run_state=dict(active=True,step=None,done=[],ok=None,error='',message='Starting composed transfer.')
        result=self.agent.get_runner().start('lacry_workflow_composition',self.execute,deepcopy(plan),path)
        if not result.get('ok'):
            with self.agent.lock:self.agent.run_state.update(active=False,ok=False,error='Runner unavailable.')
            write_run_record(path,dict(status='not_dispatched',plan=plan))
            raise TeachingError('Runner unavailable; no transfer was dispatched.')
        return dict(ok=True,plan_id=plan['id'],record=str(path),message='Running the approved workflow autonomously.')

    def execute(self, run, plan, path):
        spec=plan['composition'];prior=None
        adapter=self.adapter_for(spec)
        record=dict(status='running',plan=plan,steps=[],started_at=self.clock(),
                    operator_observation='pending',automatic_retries=False)
        hold=self.folder/'unresolved.json';attempted=False;owns_hold=False
        try:
            with hold.open('x',encoding='utf-8') as stream:json.dump(dict(record=str(path)),stream)
            owns_hold=True
            outer=run;clock=self.clock;started=record['started_at']
            timeout=spec.get('instrument_chain',{}).get('timeout_s',900)
            class BoundedRun:
                confirmation_source=plan.get('confirmation_source')
                def stopped(self):return outer.stopped() or clock()-started>timeout
                def __getattr__(self,name):return getattr(outer,name)
            checked_run=BoundedRun()
            for step in plan['steps']:
                if checked_run.stopped():
                    raise TeachingError('Transfer stopped or its approved time window elapsed; no retry.')
                item=dict(step=step['id'],status='dispatching');record['steps'].append(item)
                write_run_record(path,record)
                with self.agent.lock:self.agent.run_state.update(step=step['label'],message=step['label'])
                run.say(step['label'])
                attempted=True
                prior=adapter.require(adapter.execute_step(checked_run,spec,step['id'],prior))
                item.update(status='completed',result=prior);write_run_record(path,record)
                with self.agent.lock:self.agent.run_state['done'].append(step['label'])
            record['status']='completed_controller_verified'
            # Preserve the existing registry's conservative reconciliation semantics.
            plate_id=prior.get('plate_id') or spec.get('plate_id')
            if plate_id:
                adapter.registry().record_run(plate_id,plan['id'],'completed',str(path))
            record['plate_id']=plate_id
            record['identity_status']='registered' if plate_id else spec.get('identity_status')
            record['plate_destination']=(spec['instrument_chain'].get('final_location','HOME') if spec.get('instrument_chain') else 'HOME' if spec.get('roundtrip',False) else spec['destination'])
            if prior.get('plate_location') and prior['plate_location']!=record['plate_destination']:
                raise TeachingError('Final receipt does not match the approved plate destination.')
            record['finished_at']=self.clock();write_run_record(path,record)
            hold.unlink()
            jobs=spec.get('instrument_chain',{})
            message=f"Transfer completed: plate at {record['plate_destination']}, arm at HOME. "+('All requested instrument jobs completed and were verified.' if jobs.get('hamilton') or jobs.get('imaging') else 'No imaging or pipetting was started.')
            with self.agent.lock:self.agent.run_state.update(active=False,ok=True,message=message)
            self.agent._say('lacry',message)
            return dict(ok=True,record=str(path))
        except BaseException as error:
            record.update(status='stopped_or_uncertain' if attempted else 'refused_before_dispatch',
                          motion_dispatch_attempted=attempted,error=str(error),finished_at=self.clock())
            uncertain_id=(prior or {}).get('plate_id') or spec.get('plate_id')
            if attempted and uncertain_id:
                try:adapter.registry().record_run(uncertain_id,plan['id'],'unknown',str(path))
                except Exception as registry_error:record['registry_error']=str(registry_error)
            with self.agent.lock:self.agent.run_state.update(active=False,ok=False,error=str(error),message=str(error))
            write_run_record(path,record)
            if owns_hold and not attempted:
                hold.unlink()
            self.agent._say('lacry','Transfer stopped: '+str(error)+
                (' Nothing was retried.' if attempted else ' No hardware step was dispatched.'+
                 (' This transfer lock was released.' if owns_hold else ' The existing transfer lock was preserved.')))
            raise
