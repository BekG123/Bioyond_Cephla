"""Cellvis single-plate experiment adapter; uses the console's existing owners.

No SDK connection, new coordinates, startup, calibration or protocol creation.
Calibration/registration establish the fresh HOME receipt before this plan.
Delivery and retrieval are slices of the accepted compiled handling sequence.
"""
from copy import deepcopy
import json
from pathlib import Path
import time
from uuid import uuid4

from labfacade.approval import plan_hash
from labfacade.supervised import Operation
from researcher_teaching import TeachingError

ROOT = Path(__file__).resolve().parents[1]
SKILL = 'Codex SKILLS/cellvis24-scan-station-cycle-v1/SKILL.md'
PROFILE = 'Cellvis P24-1.5H-N'


def split_handling(steps, cycles):
    """Split ONLY at the existing empty-HOME checkpoint; fail on changed layout."""
    groups = []
    for cycle in range(1, cycles+1):
        for station in ('hamilton', 'squid'):
            rows = [deepcopy(s) for s in steps if s['cycle'] == cycle and s['station'] == station]
            cuts = [i for i, s in enumerate(rows) if s['kind'] == 'instrument' and
                    s['label'] == 'Check destination before retrieval']
            if len(cuts) != 1 or cuts[0] == 0:
                raise TeachingError('Accepted delivery/retrieval checkpoint changed.')
            cut = cuts[0]
            if rows[cut-1]['label'] != 'Empty HOME clearance' or rows[-1]['label'] != 'Released HOME clearance':
                raise TeachingError('Accepted empty-HOME checkpoint is missing.')
            groups.append(dict(cycle=cycle, station=station, delivery=rows[:cut], retrieval=rows[cut:]))
    if sum(len(g['delivery'])+len(g['retrieval']) for g in groups) != len(steps):
        raise TeachingError('Unexpected handling phases; no steps may be discarded.')
    return groups


def build_steps(groups, plate_id, hamilton, imaging):
    steps = []
    def add(machine, operation, label, cycle, **params):
        item = dict(id=f's{len(steps)+1:03}', machine=machine, operation=operation,
                    kind='experiment', label=f'Cycle {cycle}: {label}', cycle=cycle, params=params,
                    resources=['arm', 'HOME', 'Hamilton site 4', 'Squid stage'],
                    timing_key=machine+':'+operation)
        if operation in ('deliver', 'retrieve'):
            location = 'hamilton' if params['station'] == 'hamilton' else 'squid stage'
            item['transfer'] = dict(plate=plate_id,
                **({'from':'bioyond deck', 'to':location} if operation == 'deliver'
                   else {'from':location, 'to':'bioyond deck'}))
            item['timing_key'] += ':'+params['station']
            item['timing_key'] += ':'+plan_hash([{k:v for k,v in s.items() if k != 'cycle'}
                                                for s in params['motion_steps']])
        if machine == 'hamilton_prep':
            item['timing_key'] += ':'+hamilton['recipe']['protocol_hash']
        if machine == 'squid' and operation == 'image':
            item['timing_key'] += ':'+imaging['profile_hash']
        steps.append(item)
    for group in groups:
        station, cycle = group['station'], group['cycle']
        if station == 'squid':
            add('squid', 'prepare_loading', 'Prepare Squid loading position', cycle)
        add('bioyond_s4', 'deliver', f'Deliver to {station.title()} and return empty to HOME', cycle,
            station=station, motion_steps=group['delivery'])
        add('hamilton_prep' if station == 'hamilton' else 'squid',
            'protocol' if station == 'hamilton' else 'image',
            'Run Hamilton and wait for its exact job' if station == 'hamilton' else
            'Image, wait for this acquisition, and restore loading position', cycle)
        add('bioyond_s4', 'retrieve', f'Retrieve from {station.title()} and release in HOME', cycle,
            station=station, motion_steps=group['retrieval'])
    return steps


class CellvisExperiment:
    def __init__(self, backend, registry, imaging=None):
        from squid_execution import SquidExecution
        self.backend, self.registry = backend, registry
        self.imaging = imaging or SquidExecution(backend.squid)
        self.hamilton = backend.instrument
        self.motion = None
        self.ticket = {}
        self.actual_run = None
        self.registry_revision = None

    def publish_custody(self,run):
        """Publish verified ledger evidence, never an operator attestation."""
        plate_id=run.plan['plate_id']
        entry=run.read_json('ledger.json')['plates'][plate_id]
        location={'bioyond deck':'HOME','hamilton':'Hamilton','squid stage':'Squid','unknown':'unknown'}[entry['location']]
        events=run.events.read()
        if entry['location']!='unknown' and not any(e.get('step')==entry['step'] and e['kind']=='result' and e.get('status')=='completed' for e in events):
            raise TeachingError('No completed transfer receipt for this custody update.')
        expected=self.registry_revision if self.registry_revision is not None else run.plan['plate_record']['revision']
        with self.registry.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.registry._checked(db,plate_id,expected)
            basis='verified_workflow_receipt' if location!='unknown' else 'uncertain_workflow_receipt'
            db.execute('UPDATE plates SET location=?,location_basis=?,revision=revision+1 WHERE plate_id=?',
                       (location,basis,plate_id))
            self.registry._event(db,plate_id,'experiment_custody',str(run.path),
                dict(run_id=run.run_id,step=entry['step'],location=location,basis=basis,
                     ledger=str(run.path/'ledger.json'),operator_acceptance=False))
        self.registry_revision=expected+1

    def record_experiment_result(self,run,result):
        # Keep the last verified custody (or explicit unknown), rather than the
        # legacy compound-run method which invalidates every known location.
        with self.registry.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.registry._event(db,run.plan['plate_id'],'instrument_run',str(run.path),
                dict(run_id=run.run_id,outcome=result['status'],operator_acceptance=False))

    def verify_registry(self,plan):
        expected=self.registry_revision if self.registry_revision is not None else plan['plate_record']['revision']
        if self.registry.get(plan['plate_id'])['revision'] != expected:
            raise TeachingError('Plate record changed during the experiment; no next step.')

    def preview(self, plate_id, recipe, cycles=1, source=None, imaging_profile=None, purpose=''):
        if type(cycles) is not int or not 1 <= cycles <= 20:
            raise TeachingError('Choose 1 to 20 supervised cycles for one plate.')
        plate = self.registry.get(plate_id)
        if plate.get('scan_count', 0) < 1:
            raise TeachingError('Plate registration requires a decoded scanner receipt.')
        if str(plate.get('metadata',{}).get('plate_type','')).strip().lower() not in (
                'cellvis p24-1.5h-n','cellvis 24-well p24-1.5h-n','p24-1.5h-n'):
            raise TeachingError('This first experiment supports the registered Cellvis P24-1.5H-N profile only.')
        # prepare() reads the commissioned recipe, native definition and inventory;
        # it does not create or run a protocol. Fail BEFORE any handling if absent.
        hamilton = self.hamilton.prepare(recipe, repetitions=cycles)
        definition = hamilton['recipe']
        if definition.get('plate_profile') != PROFILE or type(definition.get('transported_plate_site')) is not int or definition['transported_plate_site'] != 4:
            raise TeachingError('Commission this recipe for Cellvis P24-1.5H-N at Hamilton site 4; a 48-well recipe cannot be substituted.')
        imaging = self.imaging.prepare(imaging_profile, allow_loading_return=True)
        from cellvis24_workflow import plan
        motion = plan(self.backend.s, self.backend.params(), ['hamilton','squid'], cycles, source,
                      recorded_hamilton_variant='opposite3', probe=False, check_stations=False)
        groups = split_handling(motion['steps'], cycles)
        now = time.time()
        return dict(title=f'{purpose or "Supervised experiment"}: {plate_id}, {cycles} cycle(s)',
            plate_id=plate_id, plate_record=plate, profile=PROFILE, purpose=purpose,
            plates={plate_id:'bioyond deck'}, cycles=cycles, motion=motion,
            robot_cfg=deepcopy(self.backend.params()),
            envelope={k:list(v) for k,v in self.backend.s.envelope.items()},
            hamilton=hamilton, imaging=imaging,
            window=dict(not_before=now, expires_at=now+4*3600),
            steps=build_steps(groups,plate_id,hamilton,imaging))

    def operations(self):
        resources = ('arm','HOME','Hamilton site 4','Squid stage')
        return [Operation(m,n,resources,SKILL,self.dispatch) for m,n in (
            ('bioyond_s4','deliver'),('bioyond_s4','retrieve'),
            ('hamilton_prep','protocol'),('squid','prepare_loading'),('squid','image'))]

    def bind(self, plan, actual_run):
        """Called after the human approval, inside the existing console runner."""
        from cellvis24_workflow import plan as motion_plan
        self.verify_registry(plan)
        self.actual_run = actual_run
        approved = plan['motion']
        fresh = motion_plan(self.backend.s, self.backend.params(), approved['stations'], approved['cycles'],
                            approved['source'], recorded_hamilton_variant='opposite3', check_stations=False)
        ignored = {'id','start','joints','e2'}
        if {k:v for k,v in fresh.items() if k not in ignored} != {k:v for k,v in approved.items() if k not in ignored}:
            raise TeachingError('Accepted handling setup changed after review; no motion started.')
        from scope_step_trial import near
        near(fresh['start'],approved['start'],.05)
        if abs(fresh['e2']-approved['e2'])>.05 or any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in ('J1','J2','J3','J4')):
            raise TeachingError('Starting configuration changed after review.')
        self.hamilton.verify(plan['hamilton'], robot_access=True)
        self.imaging.verify(plan['imaging'], check_position=False)
        # Consume the source once, before any movement. Normal source_record()
        # detects this file; a failed experiment cannot reuse the original receipt.
        from cellvis24_workflow import RUNS
        from run_record_io import write_run_record
        folder = RUNS/approved['id']
        folder.mkdir(parents=True,exist_ok=False)
        write_run_record(folder/'run.json', dict(status='experiment_owned', plan=approved, at=time.time()))
        self.motion = deepcopy(fresh)
        self.motion['id'] = approved['id']
        from calibration_e2 import accepted
        self.motion['e2'] = 1.77 if accepted(fresh['e2']) else 90.71661229181757

    def at_home(self):
        from scope_step_trial import near,preflight
        from home_hamilton_exchange import native
        if not self.motion:
            raise TeachingError('No bound handling plan.')
        state = preflight(self.backend.s)
        near(state['pose_mm'], self.motion['start'], .05)
        axes = native(self.backend.s)['external_axes']
        if not any(abs(axes['E1']-v) <= .1 for v in (7,28)):
            raise TeachingError('Arm must be empty and at verified HOME clearance before instrument work.')
        from cellvis24_workflow import angle_ok
        if not angle_ok(axes['E2'],self.motion['e2']):
            raise TeachingError('HOME holder changed between experiment phases; no new motion.')

    def _ticket_save(self, scheduler, name, ticket):
        self.ticket[name] = deepcopy(ticket)
        scheduler.run.write_json(name+'_ticket.json', ticket)

    def dispatch(self, step, scheduler):
        scheduler.check()
        plan = scheduler.run.plan
        self.verify_registry(plan)
        if self.motion is None:
            self.bind(plan,self.actual_run)
        stopped = lambda: self.actual_run.stopped() or self._presence_stopped(scheduler)
        if step['machine'] == 'bioyond_s4':
            return self._handling(step,scheduler,stopped)
        self.at_home()
        if step['operation'] == 'prepare_loading':
            return self.imaging.prepare_loading(plan['imaging'],stopped,self.at_home)
        name = step['id']
        save = lambda ticket: self._ticket_save(scheduler,name,ticket)
        progress = lambda state: scheduler.run.events.emit('status',step=name,status='instrument_wait',data=state)
        if step['operation'] == 'protocol':
            ticket = self.hamilton.start(plan['hamilton'],plan['plate_id'],save)
            result = self.hamilton.wait(plan['hamilton'],ticket,save,stopped,progress)
            self.hamilton.completed_for_pickup(plan['hamilton'],ticket)
            self.ticket['hamilton_completed'] = ticket
            return dict(result,ticket=ticket)
        if step['operation'] == 'image':
            self.imaging.prepare_imaging(plan['imaging'],stopped,self.at_home)
            folder = scheduler.run.path/('imaging_'+name)
            folder.mkdir(exist_ok=False)
            ticket = self.imaging.start(plan['imaging'],folder,save,stopped)
            result = self.imaging.wait(plan['imaging'],ticket,save,stopped,progress)
            loading = self.imaging.restore_loading(plan['imaging'],ticket,save,stopped,self.at_home)
            self.ticket['squid_completed'] = ticket
            return dict(result,ticket=ticket,loading=loading,outputs=str(folder))
        raise TeachingError('Unknown experiment operation.')

    @staticmethod
    def _presence_stopped(scheduler):
        try:
            scheduler.check()
            return False
        except RuntimeError:
            return True

    def _handling(self,step,scheduler,stopped):
        from cellvis24_workflow import compile_steps,execute_checked_steps,validate_steps,evidence
        from scope_step_trial import preflight
        from home_hamilton_exchange import native
        scheduler.check()
        plan = scheduler.run.plan
        accepted = plan['motion']
        if (compile_steps(['hamilton','squid'],plan['cycles'],recorded_hamilton_variant='opposite3') != accepted['steps']
                or evidence() != accepted['acceptance_sha256']):
            raise TeachingError('Accepted handling routes changed during the experiment.')
        station = step['params']['station']
        if step['operation'] == 'retrieve':
            ticket = self.ticket.get(station+'_completed')
            if not ticket:
                raise TeachingError('No exact-job completion; retrieval blocked.')
            if station == 'hamilton':
                self.hamilton.completed_for_pickup(plan['hamilton'],ticket)
            else:
                state = self.imaging.observe(plan['imaging'],ticket,lambda t:None)
                if state.get('completion_confirmed') is not True or ticket.get('status') != 'completed':
                    raise TeachingError('Squid completion changed; retrieval blocked.')
                self.imaging.verify(plan['imaging'],check_selection=False)
        self.at_home()
        if (self.backend.params()!=plan['robot_cfg'] or
                {k:list(v) for k,v in self.backend.s.envelope.items()}!=plan['envelope']):
            raise TeachingError('Robot configuration or workspace changed after approval.')
        current = preflight(self.backend.s)
        # Validate this phase from actual joints without changing any waypoint.
        validate_steps(step['params']['motion_steps'],current,self.backend.params(),self.backend.s.envelope)
        fresh = deepcopy(accepted)
        fresh.update(id=uuid4().hex,source=None,source_sha256=None,steps=step['params']['motion_steps'],
                     e2=self.motion['e2'])
        outer = self.actual_run
        class CheckedRunner:
            def stopped(self):return stopped()
            def say(self,text):scheduler.check();outer.say(text)
            def audit(self,*a,**kw):return outer.audit(*a,**kw)
        opening = 28 if station == 'hamilton' or step['operation']=='deliver' else 7
        result = execute_checked_steps(CheckedRunner(),self.backend.s,self.backend.params(),fresh,fresh,
            self.backend.cam,initial_e1=opening,ends_held=False,
            receipt_status='completed' if step['operation']=='retrieve' else 'experiment_delivery_complete')
        # The next instrument waits at this actual empty HOME checkpoint.
        self.motion['start'] = result['pose_mm']
        self.motion['e2'] = 90.71661229181757 if station=='hamilton' else 1.77
        return result
