"""Contract-ordered handling and exact instrument jobs with explicit final custody.

Runs only inside WorkflowComposition's human-approved, single-use runner.
Reuses accepted routes and existing job/authoring engines; no new SDK owner or retry.
"""
from copy import deepcopy
import json
from pathlib import Path
import time
from uuid import uuid4

from autonomy import TransferError
from labfacade.approval import plan_hash
from run_record_io import write_run_record

PROFILE = 'Cellvis P24-1.5H-N'


def imaging(backend):
    from squid_execution import SquidExecution
    return SquidExecution(backend.squid)


def prepare(backend, request, agent=None):
    from composed_cellvis_registration import delivery_steps
    stations = request.get('stations')
    composition=request.get('composition')
    if composition is not None:
        from workflow_capabilities import compose_hotel, compose_ordered
        fresh=(compose_ordered(request['operations'],request['source_state'],PROFILE) if request.get('source_state') else
               compose_hotel(request['operations'],PROFILE,1))
        if fresh!=composition:raise TransferError('Workflow contracts changed; request a new plan.')
        jobs=[x['capability']['station'] for x in composition['capabilities'] if x['capability']['executor'] in ('hamilton_job','squid_job')]
        if len(jobs)!=len(set(jobs)):raise TransferError('Repeated instrument jobs require separately bound cycle inventory/settings; this binding supports one job per instrument.')
        if stations!=list(dict.fromkeys(x['capability']['station'] for x in composition['capabilities'] if 'station' in x['capability'])):
            raise TransferError('Station bindings do not match the composed operations.')
    else:
        if stations not in (['Squid'], ['Hamilton'], ['Hamilton', 'Squid']):
            raise TransferError('Invalid legacy instrument stations.')
        jobs=stations
    count = request.get('image_count')
    if count is not None and (type(count) is not int or not 1 <= count <= 10000 or 'Squid' not in stations):
        raise TransferError('Image count must be 1 to 10000 and requires Squid imaging.')
    chain = dict(request=deepcopy(request), groups=[], hamilton=None, imaging=None,
                 final_location=composition['final']['plate_location'] if composition else 'HOME')
    if 'Hamilton' in jobs:
        if request.get('draft_id'):
            if request.get('recipe'):raise TransferError('Choose draft_id or recipe, not both.')
            if agent is None:raise TransferError('The Hamilton draft requires the installed protocol-authoring executor.')
            h=agent.hamilton_experiment.prepare_bound(request['draft_id'])
            backend.instrument.verify(h,robot_access=True)
        else:
            if not request.get('recipe'):
                raise TransferError('hamilton_protocol requires draft_id (create/simulate/execute) or recipe (commissioned). Use draft_protocol to bind the specified liquid transfers; no settings are guessed.')
            h = backend.instrument.prepare(request['recipe'], repetitions=1)
            recipe = h['recipe']
            if recipe.get('plate_profile') != PROFILE or type(recipe.get('transported_plate_site')) is not int or recipe['transported_plate_site'] != 4:
                raise TransferError('The Hamilton recipe must be commissioned for Cellvis P24-1.5H-N at site 4.')
        chain['hamilton'] = h
    if 'Squid' in jobs:
        p = imaging(backend).prepare(request.get('imaging_profile'), allow_loading_return=True)
        selected = p['profile'].get('selected_settings', {})
        if count is not None and selected.get('total_images') != count:
            raise TransferError(f"Requested {count} images, but the selected Squid setup reports {selected.get('total_images', 'an unreadable image count')}. Select the intended fields/timepoints/channels in Squid, or choose a matching reviewed imaging profile; no movement started.")
        chain['imaging'] = p
    for station in stations:
        outbound = delivery_steps(station, False)
        full = delivery_steps(station, True)
        if full[:len(outbound)] != outbound or full[-1]['label'] != 'Released HOME clearance':
            raise TransferError('Accepted station delivery/retrieval split changed.')
        chain['groups'].append(dict(station=station, delivery=outbound, retrieval=full[len(outbound):]))
    if composition:
        from capability_workflow import bind_phase
        for item in composition['capabilities']:
            if item['capability']['executor']=='cellvis_station_phase':bind_phase(item['capability'])
    configured_wait = 900 + sum(float(p['timeout_s']) for p in (
        chain['hamilton'] or {}, (chain['imaging'] or {}).get('profile', {})) if p)
    if not 0 < configured_wait < float('inf'):
        raise TransferError('Invalid instrument timeout.')
    chain['timeout_s'] = min(configured_wait, 4*3600)
    return chain


def verify(backend, chain, selection=True, agent=None):
    from composed_cellvis_registration import delivery_steps
    for group in chain['groups']:
        outbound = delivery_steps(group['station'], False)
        if group['delivery'] != outbound or group['delivery']+group['retrieval'] != delivery_steps(group['station'], True):
            raise TransferError('Accepted instrument handling routes changed after approval.')
    if chain['hamilton']:
        if chain['hamilton'].get('mode')=='simulate_execute':
            if agent is None:raise TransferError('Hamilton draft executor unavailable.')
            agent.hamilton_experiment.verify_bound(chain['hamilton'])
        backend.instrument.verify(chain['hamilton'], robot_access=True)
    if chain['imaging']:
        imaging(backend).verify(chain['imaging'], check_position=False, check_selection=selection)


def steps(chain):
    composition=chain['request'].get('composition')
    if composition is not None:
        result=[];counts={}
        def add(station,action,label):
            base=f'instrument_{station.lower()}_{action}'
            counts[base]=counts.get(base,0)+1
            result.append(dict(id=base if counts[base]==1 else base+'_'+str(counts[base]),station=station,action=action,label=label))
        for item in composition['capabilities']:
            cap=item['capability'];executor=cap['executor']
            if executor in ('hotel_retrieval','cellvis_registration'):continue
            station=cap['station']
            if executor=='cellvis_station_phase':
                action='deliver' if cap['phase']=='delivery' else 'retrieve'
                if station=='Squid' and action=='deliver' and chain['imaging']:
                    add(station,'loading','Prepare Squid loading position with the arm at HOME')
                add(station,action,cap['description'])
            elif executor in ('hamilton_job','squid_job'):
                label=('Create if needed, simulate the exact Hamilton draft, then execute once only if simulation succeeds'
                       if station=='Hamilton' and chain['hamilton'].get('mode')=='simulate_execute' else
                       f'Run the approved {station} protocol; wait for this exact job')
                add(station,'run',label)
            else:raise TransferError('No phase executor for '+executor)
        return result
    result = []
    for group in chain['groups']:
        name = group['station']; key = name.lower()
        if name == 'Squid':
            result.append(dict(id='instrument_squid_loading', label='Prepare Squid loading position with the arm at HOME'))
        result.extend([
            dict(id=f'instrument_{key}_deliver', label=f'Deliver and release at {name}; return empty to HOME'),
            dict(id=f'instrument_{key}_run', label=(
                'Run the commissioned Hamilton recipe; wait for this exact job' if name == 'Hamilton' else
                'Acquire the confirmed Squid images; wait for this exact acquisition and restore loading position')),
            dict(id=f'instrument_{key}_retrieve', label=f'Verify {name} completion; retrieve and release the plate in HOME')])
    return result


def at_home(backend, context):
    from scope_step_trial import preflight, near
    from home_hamilton_exchange import native
    from cellvis24_workflow import angle_ok
    state = preflight(backend.s); axes = native(backend.s)
    near(state['pose_mm'], context['home_pose'], .05)
    if (axes['moving'] or abs(axes['external_axes']['E1']-context['home_e1']) > .1 or
            not angle_ok(axes['external_axes']['E2'], context['home_e2'])):
        raise TransferError('Verified empty-arm HOME checkpoint changed; no next instrument step.')


def registration_context(prior):
    """Read-only validation; deliver() subsequently consumes the HOME receipt."""
    from composed_cellvis_registration import sha
    from cellvis24_workflow import source_record
    p = Path(prior['record']); record = json.loads(p.read_bytes())
    if (record.get('status') != 'registered_HOME_released' or record.get('plate_id') != prior.get('plate_id') or
            record.get('home_receipt') != prior.get('home_receipt') or
            not 0 <= time.time()-record['finished_at'] <= 1800 or
            sha(record['home_receipt']) != record['home_sha256'] or sha(record['scan_receipt']) != record['scan_sha256']):
        raise TransferError('Fresh registration and matching HOME release are required before instrument work.')
    scan = json.loads(Path(record['scan_receipt']).read_bytes())
    if (scan.get('result') != 'decoded' or scan.get('plate_registry', {}).get('saved') is not True or
            scan['plate_registry'].get('plate_id') != record['plate_id']):
        raise TransferError('Decoded barcode identity does not match registration.')
    _, release = source_record(record['home_receipt'])
    axes = release['final_native']['external_axes']
    return dict(registration=deepcopy(prior), plate_id=prior['plate_id'], plate_location='HOME',
                home_pose=release['final']['pose_mm'], home_e1=axes['E1'], home_e2=axes['E2'],
                motion=None, tickets={})


def handling(run, backend, spec, context, group, action):
    from cellvis24_workflow import evidence, execute_checked_steps, validate_steps
    from composed_cellvis_registration import deliver, delivery_steps, sha
    from scope_step_trial import preflight
    if evidence() != spec['continuation']['acceptance']:
        raise TransferError('Accepted motion evidence changed.')
    station = group['station']
    if (group['delivery'] != delivery_steps(station, False) or
            group['delivery']+group['retrieval'] != delivery_steps(station, True)):
        raise TransferError('Accepted station phases changed; no movement.')
    if context['motion'] is None:
        if action != 'delivery':raise TransferError('Retrieval has no delivery receipt.')
        result = deliver(run, backend, context['registration'], group['delivery'], station, False)
    else:
        # Continue the same approved route from its actual completed checkpoint.
        # The source was consumed by the first delivery; never reuse it as permission.
        if backend.params() != spec['geometry']['cfg'] or {k:list(v) for k,v in backend.s.envelope.items()} != spec['geometry']['envelope']:
            raise TransferError('Robot configuration or workspace changed.')
        current = preflight(backend.s)
        validate_steps(group[action], current, backend.params(), backend.s.envelope)
        phase = deepcopy(context['motion'])
        phase.update(id=uuid4().hex, source=None, source_sha256=None, steps=group[action],
                     start=current['pose_mm'], joints=current['joints'], e2=context['home_e2'])
        result = execute_checked_steps(run, backend.s, backend.params(), phase, phase, getattr(backend, 'cam', None),
            initial_e1=context['home_e1'], ends_held=False,
            receipt_status='completed' if action == 'retrieval' else 'experiment_delivery_complete')
    if result.get('ok') is not True or result.get('recovered') or result.get('gripper_warning'):
        raise TransferError('Handling failed or uncertain; no retry.')
    receipt = json.loads(Path(result['record']).read_bytes())
    expected = 'completed' if action == 'retrieval' else 'experiment_delivery_complete'
    if receipt.get('status') != expected or receipt.get('payload') != 'empty':
        raise TransferError('Missing completed empty-arm checkpoint.')
    context.update(motion=receipt['plan'], motion_record=result['record'],motion_sha256=sha(result['record']),home_pose=receipt['final']['pose_mm'],
                   home_e1=receipt['final_native']['external_axes']['E1'],
                   home_e2=90.71661229181757 if station == 'Hamilton' else 1.77,
                   plate_location='HOME' if action == 'retrieval' else station)
    return result


def execute(adapter, run, spec, step, prior):
    """Every phase claims its predecessor before any hardware dispatch."""
    from composed_cellvis_registration import sha
    backend = adapter.backend; chain = spec['instrument_chain']
    order = [s['id'] for s in steps(chain)]
    if step not in order or (prior is None and not (spec.get('source') and order[0]==step)):
        raise TransferError('Unbound instrument step.')
    index = order.index(step); binding = plan_hash(spec)
    if index == 0:
        if spec.get('source'):
            adapter.verify(spec)
            source=spec['source'];motion=json.loads(Path(source['motion_path']).read_bytes())
            context=dict(plate_id=spec['plate_id'],plate_location=source['state']['plate_location'],
                motion=motion['plan'],motion_record=source['motion_path'],motion_sha256=source['motion_sha256'],tickets={},
                home_pose=spec['start'],home_e1=spec['initial_e1'],home_e2=spec['axes']['E2'])
            folder=adapter.folder/'phase_receipts'/run.run_id
            folder.mkdir(parents=True,exist_ok=False)
        else:
            context = registration_context(prior)
            folder = Path(prior['record']).parent/'instrument_chain'
            folder.mkdir(exist_ok=False)
        context['registry_revision'] = adapter.registry().get(context['plate_id'])['revision']
    else:
        path = Path(prior['record'])
        if sha(path) != prior.get('sha256'):
            raise TransferError('Instrument predecessor receipt changed.')
        receipt = json.loads(path.read_bytes())
        if (receipt.get('status') != 'completed' or receipt.get('binding') != binding or
                receipt.get('run_id') != run.run_id or receipt.get('step') != order[index-1] or
                receipt.get('context', {}).get('plate_id') != prior.get('plate_id')):
            raise TransferError('Instrument predecessor does not match this approved chain.')
        context = deepcopy(receipt['context']); folder = path.parent
    path = folder/f'{index:02}_{step}.json'
    record = dict(status='dispatching', binding=binding, run_id=run.run_id, step=step, context=context)
    # Exclusive claim plus unresolved outer hold makes a timeout non-replayable.
    with path.open('x', encoding='utf-8') as stream:json.dump(record, stream)
    def save_ticket(ticket):
        context['tickets'][station] = deepcopy(ticket)
        write_run_record(path, record)
    try:
        if run.stopped():raise TransferError('Stopped before instrument chain step.')
        if adapter.registry().get(context['plate_id'])['revision'] != context['registry_revision']:
            raise TransferError('Plate registry changed during the approved chain.')
        at_home(backend, context)
        phase=next(s for s in steps(chain) if s['id']==step)
        if 'station' in phase:station,action=phase['station'],phase['action']
        else:
            _, key, action = step.split('_'); station = key.title()
        group = next(g for g in chain['groups'] if g['station'] == station)
        api = backend.instrument if station == 'Hamilton' else imaging(backend)
        prepared = chain['hamilton'] if station == 'Hamilton' else chain['imaging']
        home = lambda: at_home(backend, context)
        if action == 'loading':
            if context['plate_location'] != 'HOME':raise TransferError('Plate must be HOME before preparing Squid loading.')
            result = api.prepare_loading(prepared, run.stopped, home)
        elif action == 'deliver':
            if context['plate_location'] != 'HOME':raise TransferError('Plate custody must be HOME before delivery.')
            if prepared is None:
                from cellvis24_workflow import geometry,hamilton_ready,squid_ready
                hamilton_ready() if station=='Hamilton' else squid_ready(geometry())
            elif station == 'Hamilton':
                if prepared.get('mode')=='simulate_execute':adapter.agent.hamilton_experiment.verify_bound(prepared)
                api.verify(prepared, robot_access=True)
            else:api.verify(prepared, check_selection=False)
            result = handling(run, backend, spec, context, group, 'delivery')
        elif action == 'run':
            if context['plate_location'] != station:raise TransferError('Plate delivery receipt is missing.')
            def progress(state):
                home()
                if state.get('status') in ('failed','aborted','cancelled','error','unknown'):
                    raise TransferError(f'{station} job failed or became uncertain; no retrieval or retry.')
            if station == 'Hamilton':
                if prepared.get('mode')=='simulate_execute':
                    bound=dict(prepared,id=run.run_id,plate_id=context['plate_id'],confirmation_source=run.confirmation_source)
                    result=adapter.agent.hamilton_experiment.execute(run,bound,checkpoint=home,composed=True)
                    ticket=result['physical_ticket']
                    context['hamilton_execution_binding']=result['execution_binding']
                    api.completed_for_pickup(result['execution_binding'],ticket)
                else:
                    ticket = api.start(prepared, context['plate_id'], save_ticket)
                    result = api.wait(prepared, ticket, save_ticket, run.stopped, progress)
                    api.completed_for_pickup(prepared, ticket)
            else:
                api.prepare_imaging(prepared, run.stopped, home)
                output = folder/'imaging'; output.mkdir(exist_ok=False)
                ticket = api.start(prepared, output, save_ticket, run.stopped)
                result = api.wait(prepared, ticket, save_ticket, run.stopped, progress)
                result = dict(result, loading=api.restore_loading(prepared, ticket, save_ticket, run.stopped, home), outputs=str(output))
            save_ticket(ticket)
        elif action == 'retrieve':
            ticket = context['tickets'].get(station, {})
            if context['plate_location'] != station or (ticket and ticket.get('status') != 'completed'):
                raise TransferError('No completed exact instrument job; retrieval blocked.')
            if not ticket:
                from cellvis24_workflow import geometry,hamilton_ready,squid_ready
                hamilton_ready() if station=='Hamilton' else squid_ready(geometry())
            elif station == 'Hamilton':api.completed_for_pickup(context.get('hamilton_execution_binding',prepared), ticket)
            else:
                state = api.observe(prepared, ticket, save_ticket)
                if state.get('completion_confirmed') is not True:raise TransferError('Squid completion changed; retrieval blocked.')
                api.verify(prepared, check_selection=False)
            result = handling(run, backend, spec, context, group, 'retrieval')
        else:raise TransferError('Unknown instrument phase.')
        adapter.require(result)
        record.update(status='completed', result=result, finished_at=time.time())
        write_run_record(path, record)
        return dict(ok=True, record=str(path), sha256=sha(path), plate_id=context['plate_id'], plate_location=context['plate_location'])
    except BaseException as error:
        record.update(status='stopped_or_uncertain', error=str(error), finished_at=time.time())
        write_run_record(path, record)
        raise
