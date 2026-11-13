"""Receipt-bound execution of declaratively composed Cellvis handling phases."""
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import time
from uuid import uuid4

from autonomy import TransferError
from cellvis24_workflow import (RUNS, evidence, geometry, validate_steps,
    execute_checked_steps, squid_ready, hamilton_ready, angle_ok)
from composed_cellvis_registration import delivery_steps, sha
from home_hamilton_exchange import native
from hotel_squid_composition import HotelSquidAdapter
from lacry_workflow_composition import WorkflowComposition
from researcher_teaching import TeachingError
from scope_step_trial import preflight, near
from trajectory_queue import LuaTrajectory
import workflow_capabilities as capabilities

FOLDER = Path(__file__).resolve().parents[1] / 'runs/composed_transfers'
PROFILE = 'Cellvis P24-1.5H-N'


def checkpoint(folder=FOLDER, *, ignore=None):
    """Use the latest complete custody checkpoint, never an arbitrary old success."""
    files = [p for p in Path(folder).glob('*.json') if re.fullmatch('[0-9a-f]{32}', p.stem) and p.stem != ignore]
    records = [(p.stat().st_mtime_ns, p, json.loads(p.read_bytes())) for p in files]
    records = [r for r in records if r[2].get('status') not in ('refused_before_dispatch', 'not_dispatched')]
    if records:
        newest = max(r[0] for r in records)
        if sum(r[0] == newest for r in records) != 1:
            raise TeachingError('Latest custody ordering is ambiguous or unresolved; cannot select a historical success.')
    for _, path, data in sorted(records, key=lambda r: r[0], reverse=True):
        reconciled=data.get('status')=='reconciled_before_instrument_run'
        observation=data.get('finished_at',0)
        proof=None
        if reconciled:
            ref=data.get('validation_reconciliation',{});proof_path=Path(ref.get('record','')).resolve()
            if proof_path!= (Path(folder)/'reconciliations'/(path.stem+'.json')).resolve() or sha(proof_path)!=ref.get('sha256'):
                raise TeachingError('Validation reconciliation evidence changed.')
            proof=json.loads(proof_path.read_bytes())
            if (proof.get('kind')!='hamilton_validation_only' or proof.get('run_id')!=path.stem or
                    proof.get('no_instrument_run_dispatched') is not True or proof.get('plate_id')!=data.get('plate_id') or
                    data['steps'][-1]['step']!='instrument_hamilton_run' or data['steps'][-1]['status']!='dispatching' or
                    proof.get('delivery')!=data['steps'][-2].get('result')):
                raise TeachingError('Validation reconciliation does not establish the completed delivery.')
            observation=proof['observed_at']
        if data.get('status') != 'completed_controller_verified' and not reconciled:
            raise TeachingError('The latest transfer is unresolved; a historical success cannot establish current plate custody.')
        spec = data['plan']['composition']
        if spec.get('plate_profile') != PROFILE:
            raise TeachingError('The latest custody checkpoint is not for the accepted Cellvis profile.')
        if not 0 <= time.time() - observation <= 1800:
            raise TeachingError('Latest plate custody receipt is older than 30 minutes; current custody needs to be re-established.')
        last = data['steps'][-2] if reconciled else data['steps'][-1]
        if last.get('status') != 'completed' or not data.get('plate_id'):
            raise TeachingError('Latest checkpoint lacks completed handling and registered identity.')
        result = last['result']
        if result.get('plate_id') != data['plate_id']:
            raise TeachingError('Handling and custody plate identities disagree.')
        motion_path = Path(result['record']).resolve()
        instrument_receipt=None
        if spec.get('instrument_chain'):
            from labfacade.approval import plan_hash
            from composed_instrument_chain import steps as instrument_steps
            instrument_receipt=json.loads(motion_path.read_bytes())
            order=instrument_steps(spec['instrument_chain'])
            if (not order or sha(motion_path)!=result.get('sha256') or
                    instrument_receipt.get('status')!='completed' or instrument_receipt.get('binding')!=plan_hash(spec) or
                    instrument_receipt.get('step')!=('instrument_hamilton_deliver' if reconciled else order[-1]['id']) or
                    instrument_receipt.get('context',{}).get('plate_id')!=data['plate_id'] or
                    instrument_receipt['context'].get('plate_location')!=data.get('plate_destination')):
                raise TeachingError('Instrument receipt does not prove the final custody checkpoint.')
            context=instrument_receipt['context']
            if not context.get('motion_record'):raise TeachingError('Instrument receipt lacks a bound handling checkpoint.')
            motion_path=Path(context['motion_record']).resolve()
            if sha(motion_path)!=context.get('motion_sha256'):raise TeachingError('Instrument handling checkpoint changed.')
        if motion_path.name != 'run.json' or motion_path.parent.parent != RUNS.resolve():
            raise TeachingError('This custody checkpoint needs its own receipt adapter; no route will be substituted.')
        motion = json.loads(motion_path.read_bytes())
        location = data.get('plate_destination')
        expected = ('capability_chain_complete' if spec.get('capability_chain') else
                    'completed' if spec.get('roundtrip') else 'experiment_delivery_complete')
        bound = spec.get('motion_steps') if spec.get('capability_chain') else spec.get('continuation', {}).get('delivery_steps')
        if instrument_receipt:
            bound=instrument_receipt['context']['motion']['steps']
            expected='completed' if location=='HOME' else 'experiment_delivery_complete'
            if instrument_receipt['context']['motion']!=motion['plan']:
                raise TeachingError('Instrument custody and motion plan disagree.')
        if (motion.get('status') != expected or motion.get('payload') != 'empty' or
                motion['plan']['steps'] != bound or not bound or location not in ('HOME', 'Squid', 'Hamilton') or
                result.get('plate_location') != location or motion['plan']['acceptance_sha256'] != evidence() or
                not 0 <= time.time() - (observation if reconciled else motion['finished_at']) <= 1800 or
                len(motion.get('steps', [])) != len(bound) or any(s.get('status') != 'completed' for s in motion['steps'])):
            raise TeachingError('Latest handling receipt does not prove the declared custody checkpoint.')
        if any(p.resolve() != motion_path and p.stat().st_mtime_ns >= motion_path.stat().st_mtime_ns
               for p in RUNS.glob('*/run.json')):
            raise TeachingError('A later Cellvis motion record supersedes this custody checkpoint; reconcile it before reuse.')
        return dict(path=str(path.resolve()), sha256=sha(path), motion_path=str(motion_path), motion_sha256=sha(motion_path),
                    plate_id=data['plate_id'], profile=PROFILE,
                    state=dict(plate_location=location, arm_location='HOME', payload='empty')), motion
    raise TeachingError('No completed plate custody checkpoint is available for these registered handling capabilities.')


def bind_phase(capability):
    """One executor binding per capability type, independent of request order."""
    c = capability
    if c['executor'] != 'cellvis_station_phase' or c['profile'] != PROFILE or c['station'] not in ('Squid', 'Hamilton') or c['phase'] not in ('delivery', 'retrieval'):
        raise TeachingError('Capability has no accepted executor binding.')
    station, phase = c['station'], c['phase']
    before, after = ('HOME', station) if phase == 'delivery' else (station, 'HOME')
    if (c['requires'] != dict(plate_location=before, payload='empty', arm_location='HOME') or
            c['effects'] != dict(plate_location=after, payload='empty', arm_location='HOME')):
        raise TeachingError('Capability contract disagrees with its accepted executor.')
    outbound, full = delivery_steps(station, False), delivery_steps(station, True)
    if full[:len(outbound)] != outbound or full[-1]['label'] != 'Released HOME clearance':
        raise TeachingError('Accepted station phase split changed.')
    return deepcopy(outbound if phase == 'delivery' else full[len(outbound):])


class CapabilityAdapter(HotelSquidAdapter):
    def __init__(self, agent=None, *, backend=None, registry=None, folder=FOLDER, station_check=None):
        super().__init__(agent, backend=backend, registry=registry, station_check=station_check)
        self.folder = Path(folder)

    def preview(self, operations, profile=None, plate_id=None, cycles=1, *, chain_id=None, checkpoint_only=False):
        source, motion = checkpoint(self.folder, ignore=chain_id)
        if (profile is not None and profile != source['profile']) or (plate_id is not None and plate_id != source['plate_id']):
            raise TeachingError('Requested plate/profile differs from the latest verified custody checkpoint.')
        plate = self.registry().get(source['plate_id'])
        if plate.get('metadata', {}).get('plate_type') not in (None, '', PROFILE):
            raise TeachingError('Registry profile conflicts with the accepted Cellvis custody receipt.')
        registry, registry_sha = capabilities.load()
        chain = (dict(capabilities=[],trace=[],final=source['state']) if checkpoint_only else
                 capabilities.compose(operations, source['state'], source['profile'], cycles, registry=registry))
        steps = []
        for choice in chain['capabilities']:
            phase = bind_phase(choice['capability'])
            for step in phase: step['cycle'] = choice['cycle']
            steps.extend(phase)
        s = preflight(self.backend.s); n = native(self.backend.s); g = geometry()
        if self.backend.params() != g['cfg'] or {k:list(v) for k,v in self.backend.s.envelope.items()} != g['envelope']:
            raise TeachingError('Accepted handling geometry/workspace changed.')
        if n['moving'] or any(type(n['external_axes'].get(k)) not in (float, int) or not math.isfinite(n['external_axes'][k]) for k in ('E1','E2')):
            raise TeachingError('Fresh stationary jaw/holder feedback required.')
        near(s['pose_mm'], motion['final']['pose_mm'], .05)
        for key in ('J1','J2','J3','J4'):
            if not math.isfinite(s['joints'][key]) or abs(s['joints'][key]-motion['final']['joints'][key]) > .1:
                raise TeachingError('Arm joint configuration differs from the custody checkpoint.')
        axes = motion['final_native']['external_axes']
        opening = [step['target'] for step in motion['plan']['steps'] if step['kind']=='jaws'][-1]
        if opening not in (7,28) or abs(axes['E1']-opening) > .1:
            raise TeachingError('The custody receipt does not end with released empty jaws.')
        if abs(n['external_axes']['E1']-axes['E1']) > .1 or abs(n['external_axes']['E2']-axes['E2']) > .1:
            raise TeachingError('Jaw/holder state differs from the custody checkpoint.')
        target_angle = motion['plan']['steps'][-1]['holder_angle']
        if not angle_ok(n['external_axes']['E2'], target_angle):
            raise TeachingError('Holder is outside the accepted route orientation.')
        validate_steps(steps, s, self.backend.params(), self.backend.s.envelope)
        for station in dict.fromkeys(c['capability']['station'] for c in chain['capabilities']):
            if self.station_check is not None: self.station_check(station.lower(), g)
            else: hamilton_ready() if station == 'Hamilton' else squid_ready(g)
        return dict(capability_chain=chain, operations=list(operations), cycles=cycles,
            plate_profile=source['profile'], plate_id=source['plate_id'], registry_revision=plate['revision'],
            destination=chain['final']['plate_location'], source=source, chain_id=chain_id,
            capability_registry_sha256=registry_sha, acceptance_sha256=evidence(), motion_steps=steps,
            start=s['pose_mm'], joints=s['joints'], axes=n['external_axes'], initial_e1=opening, geometry=g)

    def verify(self, spec):
        fresh = self.preview(spec['operations'], spec['plate_profile'], spec['plate_id'], spec['cycles'], chain_id=spec['chain_id'])
        near(fresh['start'], spec['start'], .05)
        for key in ('joints', 'axes'):
            if any(type(spec[key].get(k)) not in (float,int) or not math.isfinite(spec[key][k]) or abs(v-spec[key][k]) > .05 for k,v in fresh[key].items()):
                raise TeachingError('Starting state changed after capability planning.')
        if any(fresh[k] != spec[k] for k in fresh if k not in ('start','joints','axes')):
            raise TeachingError('Capability plan, identity, custody or accepted route changed.')
        return fresh

    @staticmethod
    def steps(spec):
        labels = [c['capability']['description'] for c in spec['capability_chain']['capabilities']]
        return [dict(id='execute_capabilities', label=' '.join(labels) or 'Verify the requested HOME postcondition',
                     capabilities=[c['capability']['id'] for c in spec['capability_chain']['capabilities']])]

    def execute_step(self, run, spec, step, prior):
        if step != 'execute_capabilities' or prior is not None:
            raise TeachingError('Unbound capability execution step.')
        fresh = self.verify(spec)
        if run.stopped(): raise TeachingError('Capability plan stopped before dispatch.')
        if not fresh['motion_steps']:
            return dict(ok=True, record=fresh['source']['motion_path'], plate_id=fresh['plate_id'],
                        plate_location=fresh['destination'], postcondition_only=True)
        cap = LuaTrajectory(self.backend.s).capability()
        if not cap.get('available') or cap.get('version') != 220109:
            raise TeachingError('Running mixed-speed Lua220109 required; no controller startup included.')
        if any(s.get('flags', {}).get('transit_blend') for s in fresh['motion_steps']):
            from hamilton_transit_blend import require_capability
            require_capability(self.backend.s, 'opposite3')
        self.verify(spec)
        motion = json.loads(Path(fresh['source']['motion_path']).read_bytes())['plan']
        motion.update(id=uuid4().hex, steps=fresh['motion_steps'], cycles=spec['cycles'], source=None, source_sha256=None,
                      start=fresh['start'], joints=fresh['joints'], e2=fresh['axes']['E2'])
        result = self.require(execute_checked_steps(run, self.backend.s, self.backend.params(), motion, motion,
            getattr(self.backend,'cam',None), initial_e1=fresh['initial_e1'], ends_held=False,
            receipt_status='capability_chain_complete', station_check=self.station_check))
        return dict(result, plate_id=spec['plate_id'], plate_location=spec['destination'])


class CapabilityWorkflow(WorkflowComposition):
    def __init__(self, agent, adapter=None, folder=FOLDER):
        super().__init__(agent, adapter or CapabilityAdapter(agent, folder=folder), folder)

    def propose(self, operations, plate_profile=None, plate_id=None, cycles=1):
        self.idle()
        with self.agent.lock: self.agent.pending = None
        plan_id = uuid4().hex
        spec = self.adapter.preview(operations, plate_profile, plate_id, cycles, chain_id=plan_id)
        if not spec['capability_chain']['capabilities']:
            return dict(ok=True, awaiting_confirmation=False, blocked=False, already_satisfied=True,
                message='The requested HOME postcondition is already verified; no motion is needed.',
                capabilities=spec['capability_chain'], plate_id=spec['plate_id'])
        plan = dict(id=plan_id, at=self.clock(), dispatch='workflow_capabilities', executable=True, blockers=[],
            location_schema=2, summary=' → '.join(operations), labels=list(operations), repetitions=cycles,
            steps=[dict(s, kind='workflow') for s in self.adapter.steps(spec)], composition=spec,
            requirements=[
                f"Confirm the registered {spec['plate_profile']} plate {spec['plate_id']} remains at {spec['source']['state']['plate_location']}; jaws are empty and HOME clearance matches the displayed checkpoint.",
                'Confirm destination holders are empty before delivery, the unchanged routes and jaw/holder sweeps are clear, hands clear and E-stop supervised.',
                'Squid must be at its verified loading position and idle. Hamilton requires idle/parked heads and open access when included.',
                'One confirmation covers the entire displayed chain within 15 minutes. No imaging, pipetting, calibration, startup, fault reset or uncertain-motion retry.'],
            capability_trace=spec['capability_chain']['trace'])
        with self.agent.lock: self.agent.pending = plan
        self.agent._announce_plan(plan)
        return dict(ok=True, awaiting_confirmation=True, blocked=False, plan=self.agent._plan_view(plan),
                    capabilities=spec['capability_chain'], plate_id=spec['plate_id'])
