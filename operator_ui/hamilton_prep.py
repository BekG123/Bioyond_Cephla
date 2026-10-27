"""Hamilton Prep transport. No starts on import, status, planning or reconnect.

Only named operations are exposed to Lacry. Writes are never retried. An owned
run must have its own Completed run-data record before robot access is granted.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import queue
import re
import threading
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, ProxyHandler, build_opener
from uuid import uuid4

from researcher_teaching import TeachingError

class CalibrationRackNotReady(TeachingError):
    """Physical channel-calibration setup is not loaded yet."""

ROOT = Path(__file__).resolve().parent
CALIBRATION_ACTIONS = ('self_calibration', 'channel_calibration', 'full_calibration')
FULL_CALIBRATION_STEPS = ('self_calibration', 'channel_calibration')
ACTION_LABELS = {'initialize': 'Initialize Hamilton',
    'park': 'Park Hamilton',
    'self_calibration': 'Hamilton self-calibration',
    'channel_calibration': 'Hamilton channel height/squeeze calibration',
    'full_calibration': 'Hamilton full calibration'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def error_summary(errors):
    """Keep the concrete native faults instead of selecting an arbitrary wrapper."""
    messages=[]
    def visit(value):
        if not isinstance(value,dict):return
        for child in value.get('errorData',[]) or []:visit(child)
        message=str(value.get('message') or '').strip()
        if message and message not in messages:messages.append(message)
    for error in errors:visit(error)
    specific=[m for m in messages if not any(s in m.lower() for s in
        ('genericbusy','one or more errors','see innerexceptions','select a recovery action'))]
    return ' | '.join(specific or messages) or 'Unspecified Hamilton error.'


def decoded(value):
    for _ in range(4):
        if not isinstance(value, str): break
        try: value = json.loads(value)
        except ValueError: break
    return value


class PrepEvents:
    """Subscribe before a write. A lost event stream makes the outcome uncertain."""
    def __init__(self, adapter):
        self.adapter = adapter
        self.messages = queue.Queue()
        self.sockets = []
        self.closing = False

    def __enter__(self):
        from websockets.sync.client import connect
        base = self.adapter.settings()['base_url'].rsplit('/api/v1', 1)[0].replace('http://', 'ws://')
        try:
            for channel in ('instinctevents', 'instincterrors'):
                socket = connect(base+'/'+channel, proxy=None, open_timeout=8, close_timeout=2)
                self.sockets.append(socket)
                threading.Thread(target=self.listen, args=(socket,channel), daemon=True).start()
        except Exception:
            self.__exit__(None,None,None)
            raise
        return self

    def listen(self, socket, channel):
        try:
            for message in socket:
                self.messages.put((channel, decoded(message)))
        except Exception as error:
            if not self.closing: self.messages.put(('connection_lost', str(error)))
        finally:
            if not self.closing: self.messages.put(('connection_lost', channel+' closed'))

    def drain(self):
        rows = []
        while True:
            try: rows.append(self.messages.get_nowait())
            except queue.Empty: return rows

    def __exit__(self, *args):
        self.closing = True
        for socket in self.sockets: socket.close()


class HamiltonPrep:
    def __init__(self, config=None, request=None, events=None, folder=None, sleep=time.sleep):
        self.config = Path(config or ROOT/'hamilton_prep.json')
        self.request = request
        self.events = events or PrepEvents
        self.folder = Path(folder or ROOT/'reports/hamilton_api')
        self.sleep = sleep
        self.session = uuid4().hex
        self.lock = threading.RLock()
        self.operation_lock = threading.Lock()
        self.response_lock = threading.Lock()
        self.active = None
        self.prompt = None
        self.recent_events = []
        self.cache = None
        self.cache_at = 0
        self.opener = build_opener(ProxyHandler({}))
        self.touchscreen_root=None
        self.touchscreen_recorder=None
        self.touchscreen_lock=threading.Lock()
        self.polling_trial=None
        self.http_condition=threading.Condition()
        self.http_active=0
        self.monitored_errors={'items':[]}
        marker=self.folder/'active.json'
        if marker.exists():
            try:
                saved=json.loads(marker.read_text(encoding='utf-8'))
                if saved.get('status') in ('finished_unverified','failed_or_uncertain','uncertain'):self.active=saved
            except (OSError,ValueError):pass  # The existing marker still blocks all new starts.

    def settings(self):
        value = json.loads(self.config.read_text(encoding='utf-8-sig'))
        url = urlparse(value['base_url'])
        if url.scheme != 'http' or url.hostname != '192.168.100.101' or url.path != '/NimbusLite/api/v1' or url.username or url.password or url.query or url.fragment:
            raise TeachingError('Hamilton address does not match the configured Prep controller PC.')
        return value

    def call(self, method, path, body=None, binary=False):
        with self.http_condition:
            trial=self.polling_trial
            self.http_active+=1
        request_id=uuid4().hex
        started=time.monotonic()
        try:
            if trial:
                self.trial_log(trial,'request',dict(id=request_id,method=method,path=path,body=body,
                    thread=threading.current_thread().name))
                nonessential=(path in ('protocols','maintenance',
                    'service-software-api/is-parked') or path.startswith(('camera/','traces?','protocols/')))
                # Channel results are essential to the calibration worker, but
                # UI/background readers must use its published snapshot.
                if path=='calibration/channel-results' and threading.get_ident()!=trial['owner']:
                    nonessential=True
                if (path=='service-software-api/is-parked' and threading.get_ident()==trial['owner']
                        and ((self.active or {}).get('calibration_cleanup') or {}).get('phase')=='waiting_for_parking'):
                    nonessential=False  # Worker readiness checks are essential while parking finishes.
                if trial['mode']=='reduced' and nonessential:
                    self.trial_log(trial,'suppressed',dict(id=request_id,path=path))
                    raise TeachingError('This background query is paused while Hamilton calibrates.',503)
            if trial:self.trial_log(trial,'send',dict(id=request_id))
            result=self._http_call(method,path,body,binary)
            if trial:self.trial_log(trial,'response',dict(id=request_id,elapsed_s=time.monotonic()-started,
                result=dict(binary_bytes=len(result)) if isinstance(result,bytes) else result))
            return result
        except Exception as error:
            if trial:self.trial_log(trial,'request_error',dict(id=request_id,elapsed_s=time.monotonic()-started,error=str(error)))
            raise
        finally:
            with self.http_condition:
                self.http_active-=1
                self.http_condition.notify_all()

    def _http_call(self, method, path, body=None, binary=False):
        if self.request: return self.request(method,path,body)
        req = Request(self.settings()['base_url']+'/'+path,
                      data=None if body is None else json.dumps(body,allow_nan=False).encode(),
                      headers={'Content-Type':'application/json'}, method=method)
        try:
            with self.opener.open(req, timeout=30 if method!='GET' else 5) as response:
                raw = response.read(16000000)
        except HTTPError as error:
            detail=error.read(16000).decode('utf-8',errors='replace')
            raise TeachingError(f'Hamilton HTTP {error.code}: {detail or error.reason}') from error
        return raw if binary else decoded(raw.decode('utf-8')) if raw else None

    def trial_log(self,trial,kind,data):
        with trial['lock']:
            with (trial['folder']/'requests.jsonl').open('a',encoding='utf-8') as out:
                out.write(json.dumps(dict(at=time.time(),kind=kind,data=data),default=str,allow_nan=False)+'\n')

    @contextmanager
    def polling_comparison(self,mode,purpose='comparison'):
        """Scope request recording and polling policy to one owned workflow."""
        if mode not in ('normal','reduced'):raise TeachingError('Unknown polling comparison mode.')
        trial=dict(mode=mode,purpose=purpose,owner=threading.get_ident(),lock=threading.Lock(),
            folder=self.folder/('polling_'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_'+uuid4().hex[:8]))
        trial['folder'].mkdir(parents=True,exist_ok=False)
        with self.http_condition:
            if self.polling_trial:raise TeachingError('A polling comparison is already active.')
            if not self.http_condition.wait_for(lambda:self.http_active==0,timeout=10):
                raise TeachingError('Existing Hamilton requests did not finish; comparison not started.')
            self.trial_log(trial,'begin',dict(mode=mode,purpose=purpose,coverage='All Hamilton HTTP calls through this Lacry adapter; other clients are not captured.',
                baseline_status=deepcopy(self.cache)))
            self.polling_trial=trial
        try:
            yield trial
        except Exception as error:
            self.trial_log(trial,'failure',dict(error=str(error)))
            raise
        finally:
            with self.http_condition:self.polling_trial=None
            self.trial_log(trial,'end',dict(operation=deepcopy(self.active),normal_polling_restored=True))
            self.cache_at=0

    def polling_status(self):
        trial=self.polling_trial
        return dict(mode=trial['mode'] if trial else 'normal',
                    purpose=trial['purpose'] if trial else None,
                    calibration_default='reduced',
                    camera_paused=bool(trial and trial['mode']=='reduced'))

    def journal(self, ticket, kind, data):
        self.folder.mkdir(parents=True,exist_ok=True)
        row = dict(at=time.time(),kind=kind,data=data)
        with self.lock:
            with (self.folder/(ticket['request_id']+'.jsonl')).open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(row,allow_nan=False,default=str)+'\n')
            if kind == 'event':
                self.recent_events.append(row)
                self.recent_events = self.recent_events[-30:]

    def status(self, fresh=False):
        trial=self.polling_trial
        reduced=bool(trial and trial['mode']=='reduced')
        with self.lock:
            if reduced and threading.get_ident()!=trial['owner']:
                return dict(deepcopy(self.cache or {}),operation=deepcopy(self.active),prompt=deepcopy(self.prompt),
                    polling=self.polling_status(),status_from_worker=True,ready_for_robot=False,
                    status_age_s=max(0,time.monotonic()-self.cache_at))
            if not fresh and self.cache and time.monotonic()-self.cache_at < 2:
                return dict(deepcopy(self.cache),operation=deepcopy(self.active),prompt=deepcopy(self.prompt),polling=self.polling_status())
        try:
            info = self.call('GET','instruments/connection-info')
            fields = dict(line.split(': ',1) for line in info if ': ' in line)
            state = self.call('GET','instruments/global-run-state')
            run = self.call('GET','protocol-run')
            pending = self.call('GET','errors/check-for-pending-errors')
            protocols = deepcopy((self.cache or {}).get('protocol_catalog',[])) if reduced else self.call('GET','protocols')
            parked = None if reduced else self.call('GET','service-software-api/is-parked')
            connected = fields.get('Connected')=='True' and fields.get('Serial Number')==self.settings()['serial_number']
            initialized = fields.get('Initialization Status')=='Initialized'
            result = dict(available=connected,connected=connected,simulation=False,
                serial=fields.get('Serial Number'),initialized=initialized,global_state=state,
                state='idle' if state=='Idle' else 'running',run=run,pending_errors=pending,
                protocol_catalog=protocols,protocols=[p['name'] for p in protocols],
                recipes=list(self.settings().get('recipes',{})),session_id=self.session,
                parked=parked is True,door_automation_ready=self.door_automation_ready(),
                ready_for_robot=False, message=f'Hamilton {state}; '+('initialized.' if initialized else 'not initialized.'))
            if not connected: result['message']='Hamilton identity or connection does not match.'
        except Exception as error:
            result=dict(available=False,connected=False,ready_for_robot=False,state='unknown',message=str(error))
        with self.lock:
            # A UI refresh can begin just before the worker takes ownership.
            # Do not let that old reader overwrite the worker's current snapshot.
            current=self.polling_trial
            if current and current['mode']=='reduced' and threading.get_ident()!=current['owner']:
                return dict(deepcopy(self.cache or {}),operation=deepcopy(self.active),prompt=deepcopy(self.prompt),
                    polling=self.polling_status(),status_from_worker=True,ready_for_robot=False,
                    status_age_s=max(0,time.monotonic()-self.cache_at))
            self.cache,self.cache_at=deepcopy(result),time.monotonic()
            return dict(result,operation=deepcopy(self.active),prompt=deepcopy(self.prompt),polling=self.polling_status())

    def detail(self):
        state=self.status(fresh=True)
        if self.polling_trial and self.polling_trial['mode']=='reduced':
            state.update(events=deepcopy(self.recent_events[-12:]),touchscreen=self.touchscreen_status(),
                errors=deepcopy(self.monitored_errors),calibration_defaults=self.settings().get('calibration',{}),
                polling=self.polling_status(),background_polling_suspended=True)
            return state
        from hamilton_handling import travel_status,handling_history
        state['arm_travel']=travel_status()
        state['arm_handling_history']=handling_history()
        if state['connected']:
            state['errors']=self.call('GET','errors?offset=0&limit=20')
            state['maintenance']=self.call('GET','maintenance')
            state['calibration']=self.calibration_status()
            state['calibration_defaults']=self.settings().get('calibration',{})
        state['events']=deepcopy(self.recent_events[-12:])
        state['touchscreen']=self.touchscreen_status()
        return state

    def touchscreen_status(self):
        from hamilton_touchscreen import ROOT,read_snapshot
        if self.request and self.touchscreen_root is None:return dict(fresh=False,prompt=None)
        return read_snapshot(self.touchscreen_root or ROOT)

    def observe_touchscreen(self):
        from hamilton_touchscreen import ROOT,TouchscreenRecorder
        with self.touchscreen_lock:
            if self.touchscreen_status().get('fresh'):
                return dict(ok=True,message='Touchscreen recording is already active.')
            if self.touchscreen_recorder and self.touchscreen_recorder.state.get('recording'):
                return dict(ok=True,message='Connecting the read-only touchscreen recorder.')
            self.touchscreen_recorder=TouchscreenRecorder(self,self.touchscreen_root or ROOT)
            threading.Thread(target=self.touchscreen_recorder.run,daemon=True).start()
        return dict(ok=True,message='Recording Hamilton for up to one hour. Start calibration on its touchscreen; live instructions will appear here.')

    def respond_touchscreen(self,prompt_id,response,session,token,tip_site=None):
        """Forward one human answer to a freshly observed native dialog only."""
        from hamilton_touchscreen import ROOT
        if not self.response_lock.acquire(False):raise TeachingError('A Hamilton response is already in progress.')
        try:
            if not self.operation_lock.acquire(False):raise TeachingError('Lacry currently owns Hamilton; use its active instruction.')
            try:
                snapshot=self.touchscreen_status();prompt=snapshot.get('prompt')
                if (not snapshot.get('fresh') or snapshot.get('session')!=session or not prompt
                        or prompt.get('token')!=token or prompt.get('id')!=prompt_id or prompt.get('owner_request')):
                    raise TeachingError('That touchscreen instruction is no longer current. Check the touchscreen.')
                if response!='Ok':raise TeachingError('Use the touchscreen to cancel its procedure.')
                state=self.status(fresh=True)
                if not state.get('connected') or state.get('pending_errors'):
                    raise TeachingError('Hamilton is disconnected or has a fault. Inspect its touchscreen.')
                if state.get('global_state') not in ('Idle','CalibrationAssayRunning'):
                    raise TeachingError('Hamilton is no longer in a calibration dialog state.')
                data=prompt.get('data',{});kind=data.get('inputType')
                if kind not in (None,'','tiprack'):
                    raise TeachingError('This selection must be answered on the touchscreen.')
                path='calibration/close-view'
                body=dict(viewId=prompt_id,viewResult='Ok',viewInput=None)
                if kind=='tiprack':
                    if tip_site is None:raise TeachingError('Select the site containing the calibration tip rack.')
                    setup=self.calibration_setup(tip_site=tip_site)
                    self.verify_calibration_setup(setup,scan=True)
                    path='calibration/close-labware-view'
                    body=dict(viewId=prompt_id,viewResult='Ok',labwareId=str(setup['tip_labware_id']),labwarePosition=setup['tip_site'])
                # Re-read after validation: the touchscreen may have answered meanwhile.
                current=self.touchscreen_status().get('prompt')
                if not current or current.get('token')!=token:raise TeachingError('The touchscreen instruction changed. Nothing was sent.')
                folder=Path(self.touchscreen_root or ROOT)/'answers';folder.mkdir(parents=True,exist_ok=True)
                receipt=dict(at=time.time(),session=session,token=token,path=path,body=body,status='attempted')
                try:
                    with (folder/(token+'.json')).open('x',encoding='utf-8') as out:json.dump(receipt,out)
                except FileExistsError:raise TeachingError('This instruction was already answered; no retry was sent.')
                ticket=dict(request_id='touchscreen_'+token,source='touchscreen',session=session)
                self.write(ticket,'POST',path,body)
                receipt['status']='acknowledged'
                (folder/(token+'.json')).write_text(json.dumps(receipt),encoding='utf-8')
                return dict(ok=True,message='Answer sent to Hamilton. Its touchscreen procedure remains in control.')
            finally:self.operation_lock.release()
        finally:self.response_lock.release()

    @staticmethod
    def channel_result_passed(row):
        offsets=(row.get('channelOffset') or {}).get('yzAxisOffsets') or []
        return (row.get('status')=='Pass' and row.get('hasError') is False
                and not row.get('channelWarnings') and {x.get('index') for x in offsets}=={0,1}
                and all(x.get('offsetZValid') is True for x in offsets))

    def calibration_status(self):
        rows=self.call('GET','calibration/channel-results') or []
        latest=max(rows,key=lambda x:(x.get('calibrationDate',''),x.get('id',0))) if rows else None
        return dict(ready=bool(latest and self.channel_result_passed(latest)),latest=latest,
                    message=('Channel calibration passed.' if latest and self.channel_result_passed(latest)
                             else 'Complete Hamilton full calibration before liquid handling.'))

    def require_calibration(self):
        result=self.calibration_status()
        if not result['ready']: raise TeachingError(result['message'])
        return result

    def calibration_setup(self,tip_site=None,tip_labware_id=None):
        defaults=self.settings().get('calibration',{})
        site=tip_site if tip_site is not None else defaults.get('tip_site',7)
        configured_id=defaults.get('tip_labware_id',273)
        labware_id=tip_labware_id if tip_labware_id is not None else configured_id
        if type(site) is not int or not 1<=site<=8 or type(labware_id) is not int or labware_id<=0:
            raise TeachingError('Select a tip rack and a Hamilton site from 1 to 8.')
        if labware_id!=configured_id:
            raise TeachingError('Use the configured calibration tip rack (labware ID '+str(configured_id)+
                                '). Do not substitute a rack ID; change the rack configuration in Developer view first.')
        labware=self.call('GET','labware/'+str(labware_id))
        if labware.get('id')!=labware_id or str(labware.get('classification','')).lower()!='tiprack' or not labware.get('name'):
            raise TeachingError('Calibration requires a tip-rack definition from Hamilton.')
        return dict(tip_site=site,tip_labware_id=labware_id,reference_id=labware['name'],
                    label=labware.get('displayName',labware['name']),labware_hash=digest(labware))

    def verify_calibration_setup(self,setup,scan=False):
        current=self.calibration_setup(setup['tip_site'],setup['tip_labware_id'])
        if current!=setup: raise TeachingError('Calibration rack definition changed. Review a new plan.')
        if scan:
            rows=self.call('GET','deck/scan/3')
            site=next((x for x in rows if x.get('positionId')==setup['tip_site']),{})
            matches=site.get('matches') or [site]
            if not site.get('isOccupied') or not any(x.get('detectedLabwareId')==setup['tip_labware_id']
                    and x.get('confidence',0)>=.85 for x in matches):
                raise CalibrationRackNotReady('The camera does not confirm the selected tip rack at site '+str(setup['tip_site'])+'. Check the deck.')

    def door_automation_ready(self):
        """Watchdog drives the door actuator; interlocks stay switchable in config."""
        if self.polling_trial:return False  # Both test arms require the original closed-door sensor.
        return self.settings().get('door_automation_ready', True) is True

    def calibration_motion_ready(self):
        if not self.door_automation_ready():
            sensors=self.call('GET','service-software-api/sensor-status')
            if sensors.get('isDoorClosed') is not True or sensors.get('isEnclosurePresent') is not True:
                raise TeachingError('Close the Hamilton door before calibration.')
        if self.call('GET','service-software-api/has-tips') is not False:
            raise TeachingError('Hamilton channels must be empty before calibration.')
        workflow=self.call('GET','verification/status')
        if any(workflow.get(k) for k in ('isWorkflowInProgress','isRunInProgress','isServiceRoutineInProgress')):
            raise TeachingError('Another Hamilton workflow is active.')

    def preflight(self, initialized=False):
        if (self.folder/'active.json').exists() and not self.operation_lock.locked():
            raise TeachingError('An earlier Hamilton operation has an unresolved outcome. Inspect the instrument and its journal before recovery.')
        state=self.status(fresh=True)
        if not state.get('connected'): raise TeachingError(state['message'])
        if state['global_state']!='Idle' or state['run'].get('isRunInProgress') or state['pending_errors']:
            raise TeachingError('Hamilton has active work or a pending error. Inspect the Hamilton panel.')
        if initialized and not state['initialized']: raise TeachingError('Hamilton needs initialization before this operation.')
        return state

    @contextmanager
    def owned(self, action):
        if not self.operation_lock.acquire(False): raise TeachingError('Another operation owns Hamilton.')
        ticket=dict(request_id=uuid4().hex,action=action,session_id=self.session,status='starting')
        try:
            # An interrupted process never silently authorizes another write.
            self.folder.mkdir(parents=True,exist_ok=True)
            marker=self.folder/'active.json'
            if marker.exists(): raise TeachingError('An earlier Hamilton operation has an unresolved outcome. Inspect active.json and the instrument before recovery.')
            marker.write_text(json.dumps(ticket),encoding='utf-8')
            with self.lock: self.active=ticket;self.prompt=None
            self.journal(ticket,'begin',ticket)
            yield ticket
        except Exception as error:
            if self.active is ticket:
                ticket.update(status=('not_started' if not ticket.get('write_attempted') else ticket['status'] if ticket.get('status') in ('aborted','finished_unverified') else 'failed_or_uncertain'),error=str(error))
                self.journal(ticket,'outcome',ticket)
                if ticket['status'] in ('finished_unverified','failed_or_uncertain'):
                    marker.write_text(json.dumps(ticket),encoding='utf-8')
            raise
        finally:
            if self.active is ticket:
                # Only a verified terminal state permits another operation.
                if ticket.get('status') in ('completed','aborted','not_started'):
                    marker.unlink(missing_ok=True)
                    with self.lock:self.prompt=None
                with self.lock: self.active=deepcopy(ticket)
            self.operation_lock.release()

    def write(self,ticket,method,path,body=None):
        ticket['write_attempted']=True
        self.journal(ticket,'request',dict(method=method,path=path,body=body))
        try: result=self.call(method,path,body)
        except Exception as error:
            ticket['status']='uncertain'
            self.journal(ticket,'write_uncertain',str(error))
            raise TeachingError('Hamilton request outcome is uncertain; no retry was sent. '+str(error)) from error
        self.journal(ticket,'response',result)
        return result

    def consume(self,stream,ticket):
        for channel,event in stream.drain():
            self.journal(ticket,'event',dict(channel=channel,event=event))
            if channel=='connection_lost': raise TeachingError('Hamilton event connection lost; outcome uncertain.')
            if not isinstance(event,dict): continue
            data=decoded(event.get('data'))
            code=str(event.get('code','')).lower()
            if code in ('preparinginstrument','protocolstarted','initializing','finished'):
                ticket['observed_activity']=True
            if code=='finished':
                ticket['native_finished']=True
                if ((ticket.get('calibration_cleanup') or {}).get('phase')=='complete'
                        and (ticket.get('channel_activity') or {}).get('ended')):
                    ticket['channel_finished_after_cleanup']=True
            if channel=='instincterrors' and event.get('handled') is not True and (event.get('id') or event.get('message')):
                ticket['runtime_error']=event
                raise TeachingError('Hamilton reported: '+error_summary([event]))
            if code in ('aborted','error','failed'):
                ticket['terminal_event']=code
                raise TeachingError('Hamilton '+code+': '+str(event.get('description','')))
            # Dialog identity is supplied by Hamilton, never guessed by the agent.
            if isinstance(data,dict) and data.get('viewId'):
                with self.lock:
                    self.prompt=dict(id=data['viewId'],kind='view',action=ticket['action'],data=data)
            if code=='calibrationdata' and isinstance(data,dict):
                ticket['calibration_display']=data
                text=' '.join(str(x or '') for row in data.get('textSections',[]) for x in row).lower()
                # Prep's observed native completion dialog says "Calibration is
                # complete." It does not contain the word "successful".
                native_complete=(' '.join(text.split())=='calibration is complete.'
                    and data.get('buttonText')=='Finish' and bool(data.get('id')))
                if (data.get('spinnerShown') is False and (native_complete or re.search(r'\b(success|successful|successfully)\b',text))
                        and not re.search(r'\b(not|unsuccessful|failed|failure|error|aborted)\b',text)):
                    ticket['stage_success_display']=True
                if data.get('id') and not data.get('spinnerShown',True):
                    with self.lock:
                        self.prompt=dict(id=data['id'],kind='view',action=ticket['action'],data=data,
                                         text=' '.join(str(x or '') for row in data.get('textSections',[]) for x in row))
                        if data.get('inputType')=='tiprack':
                            self.prompt['selection']=deepcopy(ticket.get('calibration_setup'))
            if code=='generic' and isinstance(data,dict) and data.get('Name')=='ShowCustomDialog':
                prompt_id=decoded(data.get('Payload'))
                if isinstance(prompt_id,str) and prompt_id:
                    notes=self.call('GET','maintenance/errors') or []
                    with self.lock:
                        self.prompt=dict(id=prompt_id,kind='view',action=ticket['action'],data=data,
                                         text=' '.join(x.get('message','') for x in notes) or 'Check the Hamilton display for the requested instruction.')
            if code=='generic' and isinstance(data,dict) and data.get('Source')=='Loads':
                self.consume_calibration_loading(ticket,data)
            if code=='generic' and isinstance(data,dict) and data.get('Source')=='Unloads':
                self.consume_calibration_cleanup(ticket,data)
            if code=='generic' and isinstance(data,dict):
                self.track_channel_activity(ticket,data)
        self.poll_calibration_cleanup(ticket)

    @staticmethod
    def track_channel_activity(ticket,data):
        """Bind native Calibrate start/end to this owned channel stage."""
        if (ticket.get('status')!='running' or ticket.get('step')!='channel_calibration'
                or data.get('Source')!='Xsl'):return
        payload=decoded(data.get('Payload'))
        if not isinstance(payload,dict):return
        if data.get('Name')=='ActivityStarted' and payload.get('ActivityViewName')=='Calibrate' and payload.get('ActivityID'):
            ticket['channel_activity']=dict(id=payload['ActivityID'],ended=False)
        elif (data.get('Name')=='ActivityEnded' and ticket.get('channel_activity')
                and payload.get('ActivityID')==ticket['channel_activity']['id']):
            ticket['channel_activity']['ended']=True

    @staticmethod
    def channel_lifecycle_completed(ticket,state,prompt):
        """Procedure completion evidence, not a synthesized numerical Pass."""
        return bool(ticket.get('status')=='running' and ticket.get('step')=='channel_calibration'
            and ticket.get('rack_confirmed')
            and (ticket.get('calibration_loading') or {}).get('phase')=='complete'
            and (ticket.get('channel_activity') or {}).get('ended')
            and (ticket.get('calibration_cleanup') or {}).get('phase')=='complete'
            and ticket.get('channel_finished_after_cleanup')
            and not ticket.get('terminal_event') and not ticket.get('runtime_error')
            and state.get('connected') and state.get('initialized') and state.get('global_state')=='Idle'
            and state.get('run',{}).get('isRunInProgress') is False
            and state.get('pending_errors')==[] and not prompt)

    def consume_calibration_cleanup(self,ticket,data):
        if ticket.get('step')!='channel_calibration' or ticket.get('status')!='running':return
        name=data.get('Name');payload=decoded(data.get('Payload'))
        if name=='ShowDialog' and isinstance(payload,str) and payload:
            previous=ticket.get('calibration_cleanup')
            if previous:
                if previous['id']==payload:return
                raise TeachingError('Unexpected additional calibration unloading dialog; inspect Hamilton.')
            ticket['calibration_cleanup']=dict(id=payload,phase='preparing')
            self.write(ticket,'POST','calibration/begin-cleanup')
        elif name=='Status' and payload=='UnloadStarted':
            cleanup=ticket.get('calibration_cleanup')
            if not cleanup or cleanup['phase']!='preparing':return
            cleanup['phase']='waiting_for_parking'
            self.journal(ticket,'cleanup_waiting','Waiting for Hamilton to park with no tips attached.')
        elif name=='Status' and payload=='CleanupFinished':
            # UnloadFinished precedes the operator's end-cleanup response on
            # Prep. Only CleanupFinished acknowledges that final handshake.
            cleanup=ticket.get('calibration_cleanup')
            if cleanup and cleanup['phase']=='completing':
                cleanup['phase']='complete'
                self.journal(ticket,'cleanup_completed',dict(id=cleanup['id'],event=payload))

    def poll_calibration_cleanup(self,ticket):
        """UnloadStarted announces preparation, not proof that parking is done.

        Poll once per monitor iteration so stop requests and native errors remain
        responsive. The existing operation deadline bounds this wait.
        """
        cleanup=ticket.get('calibration_cleanup') or {}
        if ticket.get('status')!='running' or cleanup.get('phase')!='waiting_for_parking':return
        if self.call('GET','service-software-api/is-parked') is not True:return
        if self.call('GET','service-software-api/has-tips') is not False:return
        cleanup['phase']='awaiting_operator'
        with self.lock:
            self.prompt=dict(id=cleanup['id'],kind='calibration_cleanup',action=ticket['action'],
                data=dict(buttonText='Finish unloading'),
                text=f"Hamilton is parked with no tips attached. Remove the tip rack from site {ticket['calibration_setup']['tip_site']}, close the door, and confirm your hands are clear.")

    def consume_calibration_loading(self,ticket,data):
        """Native channel calibration uses a loading handshake separate from protocols."""
        if ticket.get('step')!='channel_calibration' or ticket.get('status')!='running':return
        name=data.get('Name');payload=decoded(data.get('Payload'))
        if name=='ShowDialog' and isinstance(payload,str) and payload:
            previous=ticket.get('calibration_loading')
            if previous:
                if previous['id']==payload:return  # Duplicate native notification, never replay a write.
                raise TeachingError('Unexpected additional calibration loading dialog; inspect Hamilton.')
            if not ticket.get('rack_confirmed'):
                raise TeachingError('Calibration loading requires the confirmed tip-rack instruction first.')
            ticket['calibration_loading']=dict(id=payload,phase='preparing')
            self.write(ticket,'POST','calibration/begin-load')
        elif name=='Status' and payload=='PrepareLoadingFinished':
            loading=ticket.get('calibration_loading')
            if not loading or loading['phase']!='preparing':return
            # The already answered full-rack instruction authorizes this same
            # loading step. Recheck placement and the original door sensors.
            self.verify_calibration_setup(ticket['calibration_setup'],scan=True)
            sensors=self.call('GET','service-software-api/sensor-status')
            if sensors.get('isDoorClosed') is not True or sensors.get('isEnclosurePresent') is not True:
                raise TeachingError('Close the Hamilton door before completing calibration loading.')
            loading['phase']='completing'
            self.write(ticket,'POST','calibration/end-load')
        elif name=='Status' and payload=='LoadingFinished':
            loading=ticket.get('calibration_loading')
            if loading and loading['phase']=='completing':loading['phase']='complete'

    def guard_errors(self,ticket,baseline):
        errors=self.call('GET','errors?offset=0&limit=30')
        with self.lock:self.monitored_errors=deepcopy(errors)
        fresh=[x for x in errors.get('items',[]) if x.get('id') not in baseline]
        if fresh:
            ticket['reported_errors']=deepcopy(fresh)
            self.journal(ticket,'native_errors',fresh)
            raise TeachingError('Hamilton: '+error_summary(fresh))

    def abort_owned(self):
        with self.lock: ticket=self.active
        if ticket and ticket.get('action')=='park' and ticket.get('status')=='running':
            ticket['park_stop_requested']=True
            return dict(ok=True,message='Hamilton parking stop requested; waiting for native stop feedback.')
        if not ticket or ticket.get('status') in ('completed','aborted','finished_unverified'):
            return dict(ok=True,message='No Lacry-owned Hamilton operation to abort.')
        if ticket['action']=='protocol':
            current=self.call('GET','protocol-run')
            if not ticket.get('job_id') or current.get('runDatalId')!=ticket['job_id']:
                raise TeachingError('Cannot bind abort to the owned Hamilton run. Use instrument controls and inspect its state.')
        with self.lock:
            if ticket.get('abort_sent'): return dict(ok=True,message='Abort already requested; checking completion.')
            ticket['abort_sent']=True
        action=ticket['action']
        if ticket.get('runtime_error'):
            error=deepcopy(ticket['runtime_error']);error['selectedResponse']='Abort'
            for item in error.get('errorData',[]):item['selectedResponse']='Abort'
            self.write(ticket,'PUT','errors/runtime',error)
        else:
            method,path=('POST','calibration/abort') if action in CALIBRATION_ACTIONS and ticket.get('step')!='initialize' else ('PUT','protocol-run/abort')
            self.write(ticket,method,path)
        return dict(ok=True,message='Hamilton abort requested; completion is not yet confirmed.')

    def finish_abort(self,stream,ticket):
        """Preserve the original failure even when abort itself cannot be verified."""
        try:
            if not ticket.get('write_attempted'): return
            if (ticket.get('native_finished') and self.call('GET','instruments/global-run-state')=='Idle'
                    and not self.call('GET','protocol-run').get('isRunInProgress')):
                ticket['status']='finished_unverified'
                self.journal(ticket,'finished_unverified','Native finished and Idle; required result evidence missing. No redundant abort sent. Ownership marker retained for review.')
                return
            if ticket.get('terminal_event')=='aborted' and self.call('GET','instruments/global-run-state')=='Idle':
                ticket['status']='aborted';self.journal(ticket,'abort_confirmed','Already aborted and idle.');return
            self.abort_owned()
            deadline=time.monotonic()+15
            aborted=False
            while time.monotonic()<deadline:
                for channel,event in stream.drain():
                    self.journal(ticket,'event',dict(channel=channel,event=event))
                    if isinstance(event,dict) and str(event.get('code','')).lower()=='aborted':aborted=True
                state=self.status(fresh=True)
                if aborted and state.get('global_state')=='Idle' and not state.get('run',{}).get('isRunInProgress'):
                    ticket['status']='aborted';self.journal(ticket,'abort_confirmed',state);return
                self.sleep(.5)
            self.journal(ticket,'abort_unverified','Abort completion was not confirmed; inspect the instrument.')
        except Exception as error:self.journal(ticket,'abort_unverified',str(error))

    def run_action(self,action,stopped=lambda:False,progress=lambda x:None,calibration_setup=None):
        if action=='park':
            from hamilton_park import run
            return run(self,stopped,progress)
        # Apply here, not only in the GUI: agent batches and lab round trips use
        # this same adapter. An explicit diagnostic comparison can override it.
        if self.polling_trial and threading.get_ident()!=self.polling_trial['owner']:
            raise TeachingError('Another operation owns Hamilton monitoring.')
        if action in CALIBRATION_ACTIONS and self.polling_trial is None:
            with self.polling_comparison('reduced',purpose='calibration'):
                return self._run_action(action,stopped,progress,calibration_setup)
        return self._run_action(action,stopped,progress,calibration_setup)

    def _run_action(self,action,stopped=lambda:False,progress=lambda x:None,calibration_setup=None):
        if action not in ACTION_LABELS:
            raise TeachingError('Unknown Hamilton maintenance action.')
        self.preflight()
        setup=None
        if action in ('channel_calibration','full_calibration'):
            setup=deepcopy(calibration_setup) if calibration_setup else self.calibration_setup()
            # Bind the definition now; validate physical rack placement when the
            # operator accepts Hamilton's native tip-loading instruction.
            self.verify_calibration_setup(setup)
        with self.owned(action) as ticket:
            self.preflight()
            ticket.update(calibration_setup=setup,completed_steps=[])
            with self.events(self) as stream:
                baseline={x['id'] for x in self.call('GET','errors?offset=0&limit=30').get('items',[])}
                # The vendor self-calibration routine owns its internal preparation.
                # Initialization is a separate, explicitly requested operation only.
                steps=FULL_CALIBRATION_STEPS if action=='full_calibration' else [action]
                try:
                    for step in steps:
                        self.preflight(initialized=step!='initialize')
                        self.calibration_motion_ready()
                        if stopped():raise TeachingError('Hamilton sequence stopped before the next action.')
                        # Drain the preceding stage before resetting its evidence.
                        self.consume(stream,ticket)
                        for key in ('calibration_display','stage_success_display','terminal_event',
                                    'channel_activity','channel_finished_after_cleanup','channel_completion'):
                            ticket.pop(key,None)
                        ticket['observed_activity']=False
                        with self.lock: self.prompt=None
                        before={x['id'] for x in self.call('GET','calibration/channel-results')} if step=='channel_calibration' else set()
                        if step=='channel_calibration':
                            self.verify_calibration_setup(setup)
                            self.calibration_motion_ready()
                        path={'initialize':'instruments/initialize','self_calibration':'calibration/self-calibration',
                              'channel_calibration':'calibration/channel-height-squeeze'}[step]
                        body=dict(tipLabwareId=setup['tip_labware_id'],tipLabwareSite=setup['tip_site']) if step=='channel_calibration' else None
                        ticket.update(status='running',step=step)
                        ticket.pop('native_finished',None)
                        # The same confirmed plan authorizes every stage; starts are never retried.
                        if stopped():raise TeachingError('Hamilton sequence stopped before the next action.')
                        self.write(ticket,'POST',path,body)
                        deadline=time.monotonic()+self.settings().get('timeout_s',3600)
                        observed=False;calibrated=False;finished_without_result_at=None
                        while time.monotonic()<deadline:
                            if stopped(): raise TeachingError('Hamilton operation stopped.')
                            self.consume(stream,ticket)
                            self.guard_errors(ticket,baseline)
                            if step=='channel_calibration':
                                fresh=[x for x in self.call('GET','calibration/channel-results') if x['id'] not in before]
                                if fresh:
                                    if len(fresh)!=1 or not self.channel_result_passed(fresh[0]):
                                        raise TeachingError('Channel calibration did not pass: '+str(fresh))
                                    calibrated=True;ticket['channel_result']=fresh[0]
                            else:calibrated=ticket.get('stage_success_display',False)
                            state=self.status(fresh=True)
                            state.update(message=ACTION_LABELS[step]+(' — waiting for the displayed instruction.' if self.prompt else ' in progress.'),
                                         completed_steps=list(ticket['completed_steps']),step=step)
                            cleanup_phase=(ticket.get('calibration_cleanup') or {}).get('phase')
                            cleanup_pending=cleanup_phase is not None and cleanup_phase!='complete'
                            if cleanup_phase=='waiting_for_parking':
                                state['message']='Waiting for Hamilton to park with no tips attached before unloading.'
                            progress(state)
                            if not state['connected']: raise TeachingError(state['message'])
                            observed |= state['global_state']!='Idle' or ticket.get('observed_activity',False) or calibrated
                            if observed and state['global_state']=='Idle' and state['initialized'] and not self.prompt and not cleanup_pending and (step=='initialize' or calibrated):
                                break
                            if ticket.get('native_finished') and state['global_state']=='Idle' and not self.prompt and not cleanup_pending and not calibrated:
                                if finished_without_result_at is None:finished_without_result_at=time.monotonic()
                                elif time.monotonic()-finished_without_result_at>=10:
                                    if step=='channel_calibration' and self.channel_lifecycle_completed(ticket,state,self.prompt):
                                        ticket['channel_completion']=dict(source='native_lifecycle',
                                            procedure_completed=True,new_history_result_available=False,
                                            numerical_result_verified=False,
                                            activity=deepcopy(ticket['channel_activity']),
                                            cleanup_id=ticket['calibration_cleanup']['id'])
                                        self.journal(ticket,'channel_procedure_completed',ticket['channel_completion'])
                                        break
                                    raise TeachingError('Hamilton finished and is Idle, but did not publish the required new calibration result. Completion remains unverified; inspect the native results before another run.')
                            self.sleep(.5)
                        else: raise TeachingError('Hamilton completion timed out; outcome uncertain.')
                        ticket['completed_steps'].append(step)
                        self.journal(ticket,'step_completed',dict(step=step,result=(ticket.get('channel_result') or ticket.get('channel_completion')) if step=='channel_calibration' else 'verified'))
                        with self.lock:self.prompt=None
                    ticket['status']='completed';self.journal(ticket,'outcome',ticket)
                    return dict(ok=True,message=ACTION_LABELS[action]+' completed.',completed_steps=ticket['completed_steps'],
                                channel_result=ticket.get('channel_result'),channel_completion=ticket.get('channel_completion'))
                except Exception:
                    self.finish_abort(stream,ticket)
                    raise

    def calibration_prompt(self,ticket):
        """Native dialogs are answered only by the operator through respond()."""
        return

    def respond(self,prompt_id,response):
        if not self.response_lock.acquire(False):raise TeachingError('Hamilton prompt response is already in progress.')
        try:return self._respond(prompt_id,response)
        finally:self.response_lock.release()

    def _respond(self,prompt_id,response):
        with self.lock: prompt=deepcopy(self.prompt);ticket=self.active
        if not prompt or prompt['id']!=prompt_id or not ticket or ticket.get('status')!='running':
            raise TeachingError('That Hamilton prompt is no longer active.')
        if response not in ('Ok','Cancel'): raise TeachingError('Unsupported Hamilton response.')
        if prompt['action'] not in CALIBRATION_ACTIONS:
            raise TeachingError('This prompt requires Hamilton operator controls.')
        data=prompt.get('data',{})
        if prompt.get('kind')=='calibration_cleanup':
            cleanup=ticket.get('calibration_cleanup') or {}
            if cleanup.get('id')!=prompt_id or cleanup.get('phase')!='awaiting_operator':
                raise TeachingError('That calibration cleanup instruction is no longer active.')
            if response=='Cancel':return self.abort_owned()
            sensors=self.call('GET','service-software-api/sensor-status')
            if sensors.get('isDoorClosed') is not True or sensors.get('isEnclosurePresent') is not True:
                raise TeachingError('Close the Hamilton door after unloading.')
            cleanup['phase']='completing'
            self.write(ticket,'POST','calibration/end-cleanup')
        elif data.get('inputType')=='tiprack':
            setup=ticket.get('calibration_setup')
            if not setup:raise TeachingError('This plan has no confirmed calibration tip rack.')
            if response=='Ok':self.verify_calibration_setup(setup,scan=True)
            self.write(ticket,'POST','calibration/close-labware-view',dict(viewId=prompt_id,viewResult=response,
                labwareId=str(setup['tip_labware_id']),labwarePosition=setup['tip_site']))
            if response=='Ok':ticket['rack_confirmed']=True
        else:
            if response=='Ok' and 'door' in prompt.get('text','').lower() and not self.door_automation_ready():
                sensors=self.call('GET','service-software-api/sensor-status')
                if sensors.get('isDoorClosed') is not True or sensors.get('isEnclosurePresent') is not True:
                    raise TeachingError('The original Hamilton door sensor must report closed.')
            self.write(ticket,'POST','calibration/close-view',dict(viewId=prompt_id,viewResult=response,viewInput=None))
        with self.lock:
            if self.prompt and self.prompt['id']==prompt_id:self.prompt=None
        return dict(ok=True)

    def prepare(self,protocol,repetitions=1,allow_uninitialized=False):
        state=self.preflight(initialized=not allow_uninitialized)
        if not allow_uninitialized:self.require_calibration()
        recipe=self.settings().get('recipes',{}).get(protocol)
        if not recipe or recipe.get('reviewed') is not True:
            raise TeachingError('Select a commissioned Hamilton liquid-handling recipe. No liquid-handling recipe has been approved for this deck yet.')
        remaining=len(recipe.get('cycle_loads',[]))-self.inventory_used(recipe)
        if type(repetitions) is not int or not 1<=repetitions<=remaining:
            raise TeachingError('Hamilton tip/liquid capacity does not cover the requested cycles.')
        protocol_id=recipe['protocol_id']
        if not any(x['id']==protocol_id for x in state['protocol_catalog']): raise TeachingError('Hamilton protocol is missing.')
        definition=self.call('GET','protocols/'+str(protocol_id))
        if digest(definition)!=recipe['protocol_hash']: raise TeachingError('Hamilton protocol changed since recipe review.')
        return dict(protocol=protocol,recipe=deepcopy(recipe),settings_hash=digest(self.settings()),
                    session_id=self.session,timeout_s=self.settings().get('timeout_s',3600))

    def inventory_path(self,recipe):
        identity=recipe.get('inventory_id')
        if not isinstance(identity,str) or not identity:raise TeachingError('Hamilton recipe requires a reviewed inventory batch.')
        return self.folder/('inventory_'+digest(identity)+'.json')

    def inventory_used(self,recipe):
        path=self.inventory_path(recipe)
        used=json.loads(path.read_text())['consumed_cycles'] if path.exists() else 0
        if type(used) is not int or used<0:raise TeachingError('Hamilton inventory ledger is invalid.')
        return used

    def reserve_inventory(self,recipe,ticket):
        index=self.inventory_used(recipe)
        loads=recipe.get('cycle_loads',[])
        if index>=len(loads):raise TeachingError('Hamilton recipe inventory is exhausted.')
        self.folder.mkdir(parents=True,exist_ok=True)
        path=self.inventory_path(recipe);temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(dict(consumed_cycles=index+1,request_id=ticket['request_id'])),encoding='utf-8');temp.replace(path)
        # Reserve BEFORE any start; uncertain runs consume a slot too. Never reset
        # tip or liquid inventory on restart, error, or subsequent experiment.
        return deepcopy(loads[index])

    def verify(self,plan,robot_access=False,allow_uninitialized=False):
        if plan['session_id']!=self.session or plan['settings_hash']!=digest(self.settings()):
            raise TeachingError('Hamilton connection or recipe changed. Request a new plan.')
        state=self.status(fresh=True)
        if not state['connected']: raise TeachingError(state['message'])
        if robot_access and (state['global_state']!='Idle' or state['run'].get('isRunInProgress') or state['pending_errors'] or (not state['initialized'] and not allow_uninitialized)):
            raise TeachingError('Hamilton has not verified readiness for robot access.')
        if robot_access and not allow_uninitialized and not state.get('parked'):
            raise TeachingError('Hamilton heads are not confirmed parked. Robot access blocked.')
        return state

    def start(self,plan,plate_id,save):
        self.verify(plan,robot_access=True)
        self.require_calibration()
        # The context remains open through wait(), so no operation may intervene.
        context=self.owned('protocol');ticket=context.__enter__()
        ticket.update(protocol=plan['protocol'],plate_id=plate_id,job_id=None)
        self._context=context
        try:
            self._stream=self.events(self).__enter__()
            ticket['baseline']=[x['id'] for x in self.call('GET','errors?offset=0&limit=30').get('items',[])]
            previous=self.call('GET','protocol-run')
            ticket['previous_run_id']=previous.get('runDatalId')
            recipe=plan['recipe']
            if digest(self.call('GET','protocols/'+str(recipe['protocol_id'])))!=recipe['protocol_hash']:
                raise TeachingError('Hamilton protocol changed before start.')
            ticket['cycle_load']=self.reserve_inventory(recipe,ticket)
            save(deepcopy(ticket))
            self.write(ticket,'POST','protocol-run/create',dict(protocolId=recipe['protocol_id'],simulate=False,recompile=False))
            created=self.call('GET','protocol-run')
            if (created.get('protocolId')==recipe['protocol_id'] and created.get('isSimulation') is False
                    and created.get('runDatalId') and created['runDatalId']!=ticket['previous_run_id']):
                ticket['job_id']=created['runDatalId']
            ticket['status']='preparing';save(deepcopy(ticket))
            return deepcopy(ticket)
        except Exception as error:
            ticket['status']='uncertain';save(deepcopy(ticket))
            if hasattr(self,'_stream'): self._stream.__exit__(None,None,None)
            context.__exit__(type(error),error,error.__traceback__)
            raise

    def wait(self,plan,ticket,save,stopped,progress):
        owned=self.active;sent=False
        deadline=time.monotonic()+plan['timeout_s']
        try:
            while time.monotonic()<deadline:
                if stopped(): raise TeachingError('Hamilton experiment stopped.')
                self.consume(self._stream,owned)
                self.guard_errors(owned,set(owned['baseline']))
                state=self.verify(plan);run=state['run'];progress(state)
                if not sent and run.get('protocolRunState') in (0,1,2,'Idle','Scheduling','Scheduled'):
                    self.sleep(.5);continue
                if run.get('protocolId')!=plan['recipe']['protocol_id'] or run.get('isSimulation') is not False:
                    raise TeachingError('Hamilton run identity or simulation state changed.')
                run_id=run.get('runDatalId')
                if run_id:
                    if run_id==owned['previous_run_id'] or (owned.get('job_id') and owned['job_id']!=run_id):
                        raise TeachingError('Hamilton reported a stale or different run.')
                    owned['job_id']=run_id
                if run.get('protocolRunState') in (3,'Loading') and not sent:
                    instructions=self.call('GET','protocol-run/load-instructions')
                    if digest(instructions)!=owned['cycle_load']['load_instructions_hash']:
                        raise TeachingError('Hamilton loading instructions changed. Inspect the deck before continuing.')
                    body=deepcopy(owned['cycle_load']['load_complete'])
                    body.update(protocolId=plan['recipe']['protocol_id'],simulate=False,loadCompleteAction='Run')
                    sent=True;owned['status']='running';save(deepcopy(owned))
                    self.write(owned,'PUT','protocol-run/load-complete',body)
                if sent and run.get('isRunInProgress') is False and state['global_state']=='Idle':
                    self.completed_for_pickup(plan,owned)
                    owned['status']='completed';save(deepcopy(owned));ticket.update(deepcopy(owned))
                    self.journal(owned,'outcome',owned)
                    return dict(ok=True,job_id=owned['job_id'])
                self.sleep(.5)
            raise TeachingError('Hamilton run timed out. Pickup blocked.')
        except Exception:
            owned['status']='failed_or_uncertain';save(deepcopy(owned));self.finish_abort(self._stream,owned)
            raise
        finally:
            self._stream.__exit__(None,None,None)
            self._context.__exit__(None,None,None)

    def completed_for_pickup(self,plan,ticket):
        state=self.verify(plan,robot_access=True)
        run_id=ticket.get('job_id')
        if not run_id or state['run'].get('runDatalId')!=run_id:
            raise TeachingError('Hamilton completion is not bound to this run. Pickup blocked.')
        result=self.call('GET','run-data/'+quote(run_id,safe=''))
        if result.get('id')!=run_id or result.get('runResult')!='Completed' or result.get('errorMessages') or result.get('deviceSerialNumber')!=self.settings()['serial_number']:
            raise TeachingError('Hamilton run did not confirm successful completion. Pickup blocked.')
        return result
