"""Bounded native acquisition control for a single confirmed lab workflow.

No arbitrary Python, model-selected motion, guessed completion or start retries.
Saved real protocols must specify the reviewed loading pose and, when needed,
the reviewed microscope-only return waypoints. The robot waits at Home.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time
from uuid import uuid4

from researcher_teaching import TeachingError
from squid_adapter import native_command

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'squid_protocols.json'
AXES = ('x_mm', 'y_mm', 'z_mm')
MISSING_SITES = 'Select the wells or imaging locations in Squid first.'


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()


def position(value):
    if not isinstance(value, dict) or any(type(value.get(k)) not in (int, float)
            or not math.isfinite(value[k]) for k in AXES):
        raise TeachingError('Squid stage position is unavailable.')
    return {k: value[k] for k in AXES}


def at_position(actual, expected):
    a, b = position(actual), position(expected)
    if any(abs(a[k]-b[k]) > .02 for k in AXES):
        raise TeachingError('Squid holder is not at the confirmed loading position.')


class SquidExecution:
    def __init__(self, adapter, config=CONFIG, command=None, clock=time.time):
        self.adapter, self.config, self.clock = adapter, Path(config), clock
        self.command = command or (lambda name, params: native_command(name, params, adapter.port))
        self.selection_path=self.config.with_suffix('.selection.json')
        self.locations_path=self.config.with_suffix('.locations.jsonl')

    def saved_selection(self, profile, configured_hash, state, current):
        """Recover settings only, never a prior workflow's motion authorization."""
        from squid_bridge.selection_snapshot import layout_key
        records=[]
        if self.locations_path.exists():
            try:
                for line in self.locations_path.read_text(encoding='utf-8').splitlines():
                    row=json.loads(line)
                    if row.get('event')=='capture':
                        if digest(row['record'])!=row['record_sha256']:
                            raise ValueError('Location record checksum changed.')
                        records.append(row['record'])
            except (ValueError,KeyError,OSError):
                raise TeachingError('The saved imaging-location archive is unreadable or changed. Review it before reuse.') from None
        if self.selection_path.exists():
            try:records.append(json.loads(self.selection_path.read_text(encoding='utf-8')))
            except (ValueError,OSError):
                raise TeachingError('The saved Squid imaging setup is unreadable. Select a new imaging site.') from None
        else:
            # Migration for selections confirmed before persistent settings were
            # introduced. Never borrow a different installation's run history.
            for path in (self.config.parent/'reports/autonomous_squid').glob('*/workflow.json'):
                try:
                    record=json.loads(path.read_text(encoding='utf-8'))
                    if record.get('confirmed_at') and record.get('plan',{}).get('imaging'):
                        records.append(dict(captured_at=record['confirmed_at'],plan=record['plan']['imaging']))
                except (ValueError,OSError):continue
        if not records:
            raise TeachingError('Squid is at loading with no imaging site selected, and no saved setup is available. Select an imaging site once in Squid, then request the experiment again.')
        # Keep separate layouts: opening Wellplate must not overwrite Flexible.
        # Within a layout, never skip the latest record for an older binding.
        try:
            wanted=layout_key(current['yaml'])
            for r in records:
                previous=r['plan']['profile']
                if (digest(previous)!=r['plan']['profile_hash'] or
                        hashlib.sha256(previous['captured_yaml'].encode()).hexdigest()!=previous['params']['settings_sha256']):
                    raise ValueError('Saved selection checksum changed.')
            records=[r for r in records if layout_key(r['plan']['profile']['captured_yaml'])==wanted]
        except (ValueError,KeyError,TypeError):
            raise TeachingError('The saved imaging-location data or checksum changed. Review the saved selection before reuse.') from None
        if not records:
            raise TeachingError('No saved imaging locations match the current tab, objective and XY layout. Select locations once for this setup.')
        saved=max(enumerate(records),key=lambda pair:(pair[1].get('captured_at',0),pair[0]))[1]
        plan=saved.get('plan',{});previous=plan.get('profile',{})
        if (plan.get('configured_hash')!=configured_hash
                or previous.get('id')!=profile['id']
                or not profile.get('stage_controller_serial')
                or previous.get('stage_controller_serial')!=profile['stage_controller_serial']
                or not profile.get('loading_reference_hash')
                or previous.get('loading_reference_hash')!=profile.get('loading_reference_hash')
                or digest(previous)!=plan.get('profile_hash')
                or not isinstance(previous.get('captured_yaml'),str)
                or hashlib.sha256(previous['captured_yaml'].encode()).hexdigest()!=previous.get('params',{}).get('settings_sha256')):
            raise TeachingError('Saved imaging locations do not match the controller, loading reference or configuration, or their checksum changed. Select new imaging sites after reviewing the setup.')
        return saved

    def location_event(self, event, **fields):
        self.locations_path.parent.mkdir(parents=True,exist_ok=True)
        row=dict(version=1,event=event,at=self.clock(),motion_authorized=False,**fields)
        # Append-only evidence: captures and reuse are not successful experiments.
        with self.locations_path.open('a',encoding='utf-8') as out:
            out.write(json.dumps(row,allow_nan=False)+'\n')

    def remember_selection(self, plan, source='live_gui'):
        data=dict(captured_at=self.clock(),source=source,plan=deepcopy(plan))
        self.location_event('capture',record=data,record_sha256=digest(data))
        self.selection_path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.selection_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data,indent=2,allow_nan=False),encoding='utf-8')
        temporary.replace(self.selection_path)

    def current_controls(self):
        try:
            current = self.command('get_current_acquisition_controls', {})
        except Exception as error:
            raise TeachingError('Cannot read current Squid acquisition controls. Load the updated settings add-on or restore a valid imaging site. No saved acquisition settings were substituted. '+str(error)) from None
        if hashlib.sha256(current['yaml'].encode()).hexdigest()!=current.get('sha256'):
            raise TeachingError('Squid live controls checksum did not match.')
        return current

    def current_with_saved_xy(self, previous_yaml, current=None):
        from squid_bridge.selection_snapshot import recover_xy
        current=self.current_controls() if current is None else current
        try:
            return recover_xy(current, previous_yaml)
        except (ValueError, KeyError, TypeError) as error:
            raise TeachingError(str(error)) from None

    def profiles(self):
        data = json.loads(self.config.read_text(encoding='utf-8-sig'))
        return dict(default=data['default'], profiles=[
            dict(id=k, label=v['label'], simulation=v['simulation'])
            for k,v in data['profiles'].items()])

    def profile(self, name=None):
        data = json.loads(self.config.read_text(encoding='utf-8-sig'))
        name = name or data['default']
        if name not in data['profiles']:
            raise TeachingError('Choose a configured Squid imaging protocol.')
        profile = deepcopy(data['profiles'][name])
        if profile.get('motion_hold'):
            raise TeachingError(profile['motion_hold'])
        if type(profile.get('simulation')) is not bool or profile.get('command') not in (
                'run_acquisition', 'run_acquisition_from_yaml', 'current_settings'):
            raise TeachingError('Squid imaging protocol is invalid.')
        if not profile['simulation'] and profile['command'] not in ('run_acquisition_from_yaml','current_settings'):
            raise TeachingError('Real imaging requires a saved, configured Squid acquisition YAML.')
        if type(profile.get('timeout_s')) not in (int,float) or not 1 <= profile['timeout_s'] <= 86400:
            raise TeachingError('Set a finite imaging timeout between 1 second and 24 hours.')
        params = profile.get('params', {})
        if not isinstance(params, dict) or {'experiment_id','base_path'} & set(params):
            raise TeachingError('The workflow must own the Squid experiment ID and output directory.')
        if profile['command'] == 'run_acquisition_from_yaml':
            path = Path(params['yaml_path']).resolve()
            profile['yaml_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            profile['params']['yaml_path'] = str(path)
        if not profile['simulation']:
            position(profile.get('loading_position'))
        waypoints = profile.get('return_waypoints', [])
        if not isinstance(waypoints,list) or len(waypoints) > 20:
            raise TeachingError('Invalid Squid holder return route.')
        for point in waypoints:
            position(point)
        profile['id'] = name
        return profile

    def ready(self, plan=None, idle=False):
        state = self.adapter.poll()
        if state.get('status')=='cleanup_unverified':
            raise TeachingError('Squid stage-cleanup verification is unavailable. Load the updated Squid add-on before another automatic experiment.')
        if not state.get('connected') or state.get('status') in ('unknown','disconnected','failed','aborted'):
            raise TeachingError('Squid imaging state is unavailable or needs review: '+state.get('message',''))
        if plan and (state['session'] != plan['session'] or state['simulation'] != plan['profile']['simulation']):
            raise TeachingError('Squid session or simulation mode changed. Request a new experiment.')
        if idle and state['status'] not in ('idle','historical','completed'):
            raise TeachingError('Squid is already imaging. Wait for that run to finish.')
        return state

    def preserve_current_locations(self):
        """Read and archive locations before a stage-only return can clear them."""
        try:
            plan=self.prepare(allow_loading_return=True,recover_locations=False)
            return dict(saved=True,settings=plan['profile'].get('selected_settings'))
        except TeachingError as error:
            if MISSING_SITES in str(error):
                return dict(saved=False,reason='No current imaging locations; previous records retained.')
            raise

    def prepare(self, name=None, *, allow_loading_return=False, recover_locations=True):
        profile = self.profile(name)
        configured_hash = digest(profile)
        state = self.ready(idle=True)
        if state['simulation'] != profile['simulation']:
            raise TeachingError('This Squid protocol does not match the connected real/simulation session.')
        if 'stage_simulated' in profile and state.get('stage_simulated') is not profile['stage_simulated']:
            raise TeachingError('This protocol requires the configured physical/simulated stage mode.')
        if state.get('stage_simulated') is False and profile.get('loading_position') is None:
            raise TeachingError('Record the reviewed physical Squid loading position before robot delivery.')
        if profile.get('loading_command'):
            if profile['loading_command'] != 'return_to_recorded_dropoff':
                raise TeachingError('Unknown Squid loading command.')
            bridge = self.command('get_stage_reference',{})
            if bridge.get('imaging_lifecycle_version')!=1:
                raise TeachingError('Load the updated Squid add-on for scan entry and stage-cleanup verification before starting this experiment.')
            if bridge.get('controller_serial') != profile.get('stage_controller_serial') or bridge.get('stage_simulated') is not False:
                raise TeachingError('Squid controller does not match this loading reference.')
            at_position(bridge['dropoff'],profile['loading_position'])
            profile['loading_reference_hash'] = bridge['reference_hash']
        actual = position(self.command('get_position', {}))
        loading = profile.get('loading_position') or actual
        # Acquisition selection can move the stage. Only workflows that include
        # an explicit, reviewed return before delivery may plan from there.
        if not (allow_loading_return and profile.get('loading_command')):
            at_position(actual, loading)
        if profile.get('return_waypoints'):
            at_position(profile['return_waypoints'][-1], loading)
        if profile['command'] == 'current_settings':
            saved=None
            try:
                snapshot = self.command('get_current_acquisition_settings', {})
            except Exception as error:
                if str(error).strip()!=MISSING_SITES or not (recover_locations and allow_loading_return and profile.get('loading_command')):
                    raise TeachingError('Cannot read the selected Squid settings. '+str(error)) from None
                # Missing sites at loading are an expected GUI state. Elsewhere
                # ask for an explicit site rather than guessing from history.
                at_position(actual,loading)
                current=self.current_controls()
                saved=self.saved_selection(profile,configured_hash,state,current)
                prior=saved['plan']['profile']
                snapshot=self.current_with_saved_xy(prior['captured_yaml'],current)
            if not isinstance(snapshot.get('yaml'), str) or not snapshot['yaml'].strip():
                raise TeachingError('Squid returned no acquisition settings.')
            expected = hashlib.sha256(snapshot['yaml'].encode()).hexdigest()
            if snapshot.get('sha256') != expected:
                raise TeachingError('Squid settings checksum did not match.')
            profile.update(command='run_current_acquisition', captured_yaml=snapshot['yaml'],
                           params={'settings_sha256': expected},
                           selected_settings=snapshot['summary'])
            if profile.get('loading_command'):
                # Current Position and implicit focus follow the physical stage.
                # Execute the confirmed native YAML, never recapture at loading.
                profile.update(command='run_acquisition_from_yaml',
                               settings_capture_position=actual if saved is None else prior['settings_capture_position'])
            if saved:
                profile['selection_source']=dict(kind='saved_coordinates',captured_at=saved['captured_at'],
                    original_session=saved['plan'].get('session'),
                    across_restart=saved['plan'].get('session')!=state['session'],
                    record_sha256=digest(saved),
                    reason='Saved XY locations with current live acquisition controls.')
                profile['coordinate_reference_yaml']=prior['captured_yaml']
        if profile.get('loading_command'):
            from squid_bridge.imaging_lifecycle import imaging_target
            if not profile.get('captured_yaml'):
                raise TeachingError('Physical automatic imaging requires a captured acquisition snapshot.')
            profile['scan_entry']=imaging_target(profile['captured_yaml'],bridge['scan_limits'])
            profile['imaging_lifecycle_version']=1
        plan=dict(profile=profile, profile_hash=digest(profile), configured_hash=configured_hash,
                    session=state['session'],
                    loading_position=loading, simulation=state['simulation'],
                    stage_simulated=state.get('stage_simulated'))
        if profile.get('captured_yaml') and not profile.get('selection_source'):
            self.remember_selection(plan)
        elif profile.get('selection_source'):
            self.location_event('reuse_proposed',source=profile['selection_source'],session=state['session'],
                snapshot_sha256=profile['params']['settings_sha256'],selected_settings=profile['selected_settings'])
        return plan

    def prepare_loading(self, plan, stopped, arm_at_home):
        """Confirmed stage-only positioning before robot delivery; no imaging."""
        self.verify(plan, check_position=False, check_selection=False)
        arm_at_home()
        if stopped():
            raise TeachingError('Stopped before preparing Squid for delivery.')
        actual = position(self.command('get_position', {}))
        loading = position(plan['loading_position'])
        if any(abs(actual[k]-loading[k]) > .02 for k in AXES):
            if plan['profile'].get('loading_command') != 'return_to_recorded_dropoff':
                raise TeachingError('No reviewed Squid loading return is configured.')
            self.command('return_to_recorded_dropoff',
                         {'reference_hash':plan['profile']['loading_reference_hash']})
        if stopped():
            raise TeachingError('Stopped while preparing Squid for delivery.')
        arm_at_home()
        # Current Position can be empty outside the scanning area. The confirmed
        # snapshot owns imaging sites; never regenerate them at loading.
        self.verify(plan, check_selection=False)
        return dict(ok=True, loading_position=loading)

    def verify(self, plan, check_position=True, check_selection=True):
        if digest(self.profile(plan['profile']['id'])) != plan.get('configured_hash',plan['profile_hash']):
            raise TeachingError('Squid protocol changed after confirmation.')
        if digest(plan['profile']) != plan['profile_hash']:
            raise TeachingError('The confirmed Squid settings snapshot changed.')
        state = self.ready(plan, idle=True)
        if plan['profile'].get('loading_reference_hash'):
            bridge = self.command('get_stage_reference',{})
            if bridge.get('reference_hash') != plan['profile']['loading_reference_hash']:
                raise TeachingError('Squid loading reference changed after confirmation.')
            if plan['profile'].get('imaging_lifecycle_version') and bridge.get('imaging_lifecycle_version')!=1:
                raise TeachingError('Squid stage-cleanup add-on is unavailable.')
        if 'captured_yaml' in plan['profile']:
            profile=plan['profile']
            if hashlib.sha256(profile['captured_yaml'].encode()).hexdigest()!=profile['params']['settings_sha256']:
                raise TeachingError('The confirmed Squid settings checksum changed.')
            # Check live GUI at Yes. Native YAML execution thereafter uses the
            # immutable snapshot, not the GUI's transient Current Position.
            if check_selection or profile['command']!='run_acquisition_from_yaml':
                try:current = self.command('get_current_acquisition_settings', {})
                except Exception as error:
                    if (str(error).strip()!=MISSING_SITES
                            or profile.get('selection_source',{}).get('kind')!='saved_coordinates'):
                        raise
                    at_position(self.command('get_position',{}),plan['loading_position'])
                    current=self.current_with_saved_xy(profile['coordinate_reference_yaml'])
                if current is not None and current.get('sha256') != profile['params']['settings_sha256']:
                    raise TeachingError('Squid settings changed before confirmation. Request a new experiment.')
        if check_position:
            at_position(self.command('get_position', {}), plan['loading_position'])
        return state

    def prepare_imaging(self,plan,stopped,arm_at_home):
        self.verify(plan,check_selection=False)
        arm_at_home()
        if stopped():raise TeachingError('Stopped before Squid scan entry.')
        profile=plan['profile']
        if profile.get('scan_entry'):
            self.command('prepare_confirmed_imaging',dict(settings_yaml=profile['captured_yaml'],
                settings_sha256=profile['params']['settings_sha256'],
                reference_hash=profile['loading_reference_hash']))
            at_position(self.command('get_position',{}),profile['scan_entry'])
        arm_at_home()
        if stopped():raise TeachingError('Stopped after Squid scan entry.')
        return dict(ok=True,position=profile.get('scan_entry',plan['loading_position']))

    def start(self, plan, folder, save, stopped):
        scan_entry=plan['profile'].get('scan_entry')
        self.verify(plan, check_position=not bool(scan_entry),check_selection=False)
        if scan_entry:at_position(self.command('get_position',{}),scan_entry)
        if stopped():
            raise TeachingError('Stopped before imaging.')
        ticket = dict(request_id='Lacry_'+uuid4().hex, requested_at=self.clock(),
                      session=plan['session'], simulation=plan['simulation'], status='start_requested')
        # Persist BEFORE sending. An uncertain response must never be retried.
        save(ticket)
        params = {**plan['profile']['params'], 'experiment_id':ticket['request_id'],
                  'base_path':str(Path(folder).resolve()/'images')}
        if 'captured_yaml' in plan['profile']:
            snapshot_path = Path(folder)/'confirmed_acquisition.yaml'
            with snapshot_path.open('x', encoding='utf-8') as stream:
                stream.write(plan['profile']['captured_yaml'])
            if plan['profile']['command']=='run_acquisition_from_yaml':
                params.pop('settings_sha256',None)
                params['yaml_path']=str(snapshot_path.resolve())
        try:
            result = self.command(plan['profile']['command'], params)
            if result.get('started') is not True or not str(result.get('experiment_id','')).startswith(ticket['request_id']):
                raise TeachingError('Squid did not acknowledge this exact imaging request.')
            ticket.update(status='started', experiment_id=result['experiment_id'], response=result)
            save(ticket)
            return ticket
        except Exception as error:
            ticket.update(status='start_uncertain', error=str(error))
            save(ticket)
            raise TeachingError('Imaging start is uncertain. No retry or retrieval: '+str(error)) from None

    def observe(self, plan, ticket, save):
        state = self.ready(plan)
        job = state.get('job') or {}
        if (job.get('experiment_id') != ticket['experiment_id']
                or type(job.get('started_at')) not in (int,float)
                or job['started_at'] < ticket['requested_at']):
            raise TeachingError('Squid reported a different or stale imaging job. Retrieval stopped.')
        if ticket.get('run_id') and ticket['run_id'] != job.get('run_id'):
            raise TeachingError('Squid imaging job changed. Retrieval stopped.')
        if not job.get('run_id'):
            raise TeachingError('Squid did not report an imaging run ID.')
        ticket.update(run_id=job['run_id'], last_observation=state)
        save(ticket)
        return state

    def wait(self, plan, ticket, save, stopped, progress):
        deadline = ticket['requested_at'] + plan['profile']['timeout_s']
        while True:
            state = self.observe(plan, ticket, save)
            if stopped():
                # Stop targets only this session/job, never another acquisition.
                self.abort_owned(plan, ticket, save)
                raise TeachingError('Experiment stopped. No retrieval will run.')
            if state.get('completion_confirmed') and state['status'] == 'completed':
                ticket.update(status='completed', completion=state)
                save(ticket)
                return dict(ok=True, run_id=ticket['run_id'], simulation=state['simulation'])
            if self.clock() > deadline:
                raise TeachingError('Imaging exceeded the configured wait. No automatic retrieval or retry.')
            progress(state)
            time.sleep(.25)

    def abort_owned(self, plan, ticket, save):
        if ticket.get('abort_requested'):
            return
        state = self.observe(plan, ticket, save)
        if state['status'] in ('running','finishing'):
            ticket['abort_requested'] = True
            save(ticket)
            if 'captured_yaml' in plan['profile']:
                self.command('abort_current_acquisition', {'experiment_id':ticket['experiment_id']})
            else:
                self.command('abort_acquisition', {})

    def restore_loading(self, plan, ticket, save, stopped, arm_at_home):
        state = self.observe(plan,ticket,save)
        if state.get('completion_confirmed') is not True or ticket.get('status') != 'completed':
            raise TeachingError('This imaging job has not completed successfully.')
        arm_at_home()
        if plan['profile'].get('loading_command'):
            if stopped():
                raise TeachingError('Stopped before returning the Squid holder.')
            self.verify(plan,check_position=False,check_selection=False)
            self.command('return_to_recorded_dropoff',{'reference_hash':plan['profile']['loading_reference_hash']})
            self.verify(plan,check_selection=False)
            return dict(ok=True,loading_position=plan['loading_position'])
        for point in plan['profile'].get('return_waypoints', []):
            if stopped():
                raise TeachingError('Stopped before returning the Squid holder.')
            self.ready(plan, idle=True)
            arm_at_home()
            self.command('move_to', {**point, 'blocking':True})
            at_position(self.command('get_position', {}), point)
        self.verify(plan,check_selection=False)
        return dict(ok=True, loading_position=plan['loading_position'])
