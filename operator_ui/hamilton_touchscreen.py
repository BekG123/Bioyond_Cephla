"""Passive recording and dialog mirror for Hamilton-owned calibration.

The observer only uses GET requests and event subscriptions. It never starts,
aborts, resets or acknowledges an instrument procedure. Explicit dialog answers
are separately validated by HamiltonPrep.respond_touchscreen().
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parent/'reports/hamilton_touchscreen'


def read_snapshot(root=ROOT, now=None):
    try:
        value=json.loads((Path(root)/'live.json').read_text(encoding='utf-8'))
        age=(time.time() if now is None else now)-value['updated_at']
        value['fresh']=0<=age<8 and value.get('connected') is True
        if not value['fresh']:value['prompt']=None
        prompt=value.get('prompt')
        if prompt and (Path(root)/'answers'/(prompt['token']+'.json')).exists():value['prompt']=None
        return value
    except (OSError,ValueError,KeyError,TypeError):
        return dict(fresh=False,connected=False,prompt=None)


class TouchscreenRecorder:
    def __init__(self,adapter,root=ROOT):
        self.adapter=adapter;self.root=Path(root)
        self.session=uuid4().hex
        self.folder=self.root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+self.session[:8])
        self.folder.mkdir(parents=True,exist_ok=False)
        self.state=dict(session=self.session,connected=False,recording=True,prompt=None,
            folder=str(self.folder),event_count=0,trace_count=0,
            coverage='API command/firmware traces, native dialogs, errors and results; not continuous encoder telemetry.')
        self.seen=set();self.lock=threading.Lock();self.stop=threading.Event()

    def log(self,kind,data):
        with self.lock:
            with (self.folder/'recording.jsonl').open('a',encoding='utf-8') as out:
                out.write(json.dumps(dict(at=time.time(),kind=kind,data=data),allow_nan=False,default=str)+'\n')

    def publish(self):
        self.state['updated_at']=time.time()
        temporary=self.root/('live.'+self.session+'.tmp')
        temporary.write_text(json.dumps(self.state,allow_nan=False),encoding='utf-8')
        # Windows readers can briefly prevent replacement. A missed heartbeat
        # disables stale answers; it must not terminate passive recording.
        for attempt in range(3):
            try:
                temporary.replace(self.root/'live.json')
                return True
            except PermissionError:
                if attempt<2:time.sleep(.02)
        self.log('snapshot_deferred','Windows reader temporarily locked live.json; recording continues.')
        return False

    def event(self,channel,event):
        from hamilton_prep import decoded
        self.log('event',dict(channel=channel,event=event));self.state['event_count']+=1
        if channel=='connection_lost':
            self.state.update(connected=False,prompt=None,message='Hamilton event connection lost. Use its touchscreen.');return
        if not isinstance(event,dict):return
        code=str(event.get('code','')).lower();data=decoded(event.get('data'))
        if channel=='instincterrors' or code in ('aborted','error','failed'):
            self.state.update(prompt=None,message='Hamilton reported an error or stopped. Inspect its touchscreen.');return
        if code=='calibrationdata' and isinstance(data,dict):
            self.state['display']=data
            self.state['message']=' '.join(str(x or '') for row in data.get('textSections',[]) for x in row).strip()
            self.state['prompt']=None
            if data.get('id') and data.get('spinnerShown') is False:
                self.state['prompt']=dict(id=data['id'],token=uuid4().hex,source='touchscreen',
                    text=self.state['message'],data=data)
                try:
                    owner=json.loads((self.adapter.folder/'active.json').read_text(encoding='utf-8'))
                    self.state['prompt']['owner_request']=owner['request_id']
                except (OSError,ValueError,KeyError):pass
        elif code in ('preparinginstrument','protocolstarted','initializing','finished'):
            self.state['prompt']=None

    def sample(self):
        if self.adapter.polling_trial and self.adapter.polling_trial['mode']=='reduced':return
        for name,path in [('global_state','instruments/global-run-state'),('run','protocol-run'),
                          ('errors','errors?offset=0&limit=50'),('channel_results','calibration/channel-results')]:
            value=self.adapter.call('GET',path)
            if self.state.get(name)!=value:
                self.log(name,value);self.state[name]=value
        # Keep overlapping windows and deduplicate. Record possible overflow explicitly.
        for source in ('MNE,MLP','RCE'):
            rows=self.adapter.call('GET','traces?offset=0&limit=1000&sources='+source).get('items',[])
            unseen=[]
            for row in rows:
                key=json.dumps(row,sort_keys=True)
                if key not in self.seen:self.seen.add(key);unseen.append(row)
            if len(unseen)==1000:self.log('coverage_warning',dict(source=source,message='Trace window full; older rows may be missing.'))
            if unseen:
                self.log('traces',dict(source=source,items=unseen));self.state['trace_count']+=len(unseen)

    def run(self,seconds=3600):
        from hamilton_prep import PrepEvents
        self.log('begin',dict(session=self.session,coverage=self.state['coverage']))
        deadline=time.monotonic()+seconds
        try:
            info=self.adapter.call('GET','instruments/connection-info')
            if 'Serial Number: '+self.adapter.settings()['serial_number'] not in info:
                raise RuntimeError('Hamilton identity does not match; observer not attached.')
            # Subscribe before snapshots, so instructions during sampling are retained.
            with PrepEvents(self.adapter) as stream:
                self.state['connected']=True
                next_sample=0
                while not self.stop.is_set() and time.monotonic()<deadline:
                    for channel,event in stream.drain():self.event(channel,event)
                    if not self.state['connected']:break
                    self.publish()
                    if time.monotonic()>=next_sample:
                        try:self.sample()
                        except Exception as error:self.log('sample_error',str(error))
                        next_sample=time.monotonic()+2
                    self.stop.wait(.2)
        except Exception as error:
            self.log('observer_error',str(error));self.state['message']=str(error)
        finally:
            self.state.update(connected=False,recording=False,prompt=None)
            self.publish();self.log('end',self.state)


if __name__=='__main__':
    from hamilton_prep import HamiltonPrep
    recorder=TouchscreenRecorder(HamiltonPrep())
    print(json.dumps(dict(folder=str(recorder.folder),mode='read-only')),flush=True)
    recorder.run()
