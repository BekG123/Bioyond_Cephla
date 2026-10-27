"""Record the next UI-owned calibration without adding HTTP polling during motion.

Lacry owns all device writes and logs its HTTP requests/events. This helper only
watches those local journals during execution, then retrieves paged native traces
after a terminal outcome and an Idle check. It never starts or answers a routine.
"""
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from hamilton_prep import HamiltonPrep,decoded

ROOT=Path(__file__).resolve().parents[2]
API=ROOT/'reports/hamilton_api'


def read_rows(path):
    rows=[]
    for line in path.read_text(encoding='utf-8').splitlines():
        try:rows.append(json.loads(line))
        except ValueError:pass  # A concurrently appended final line will be read next time.
    return rows


def main():
    folder=ROOT/'reports/hamilton_connection'/('lacry_ui_capture_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    folder.mkdir()
    def save(name,value):(folder/name).write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')
    def state(status,**fields):
        save('status.json',dict(status=status,updated_at=time.time(),**fields))
    state('preparing')
    print(str(folder),flush=True)
    h=HamiltonPrep()
    baseline={p:h.call('GET',p) for p in ('instruments/connection-info','instruments/global-run-state',
        'calibration/channel-results','errors?offset=0&limit=30')}
    assert 'Serial Number: PRPGD2427' in baseline['instruments/connection-info']
    assert baseline['instruments/global-run-state']=='Idle','Arm recording before starting calibration.'
    boundaries={}
    for source in ('MNE,MLP','RCE'):
        rows=h.call('GET','traces?offset=0&limit=1&sources='+source).get('items',[])
        boundaries[source]=rows[0].get('date','') if rows else ''
    save('baseline.json',dict(snapshot=baseline,trace_boundaries=boundaries,
        coverage='Lacry HTTP journal, native events and post-run command traces. Not continuous encoder telemetry or unobserved external-client HTTP calls.'))
    known={p.name for p in API.glob('*.jsonl')}
    deadline=time.monotonic()+7200
    journal=None;request_id=None
    state('armed',message='Waiting for the next Lacry calibration; no device polling during execution.')
    print('ARMED',flush=True)
    while time.monotonic()<deadline and not (folder/'stop').exists():
        if journal is None:
            for path in API.glob('*.jsonl'):
                if path.name in known:continue
                rows=read_rows(path)
                if not rows:continue
                first=rows[0]
                if first.get('kind')=='begin' and first.get('data',{}).get('action') in ('self_calibration','channel_calibration','full_calibration'):
                    journal=path;request_id=first['data']['request_id']
                    state('recording',request_id=request_id,journal=str(journal))
                    print('RECORDING '+request_id,flush=True);break
                known.add(path.name)
        if journal:
            rows=read_rows(journal)
            outcome=next((r for r in reversed(rows) if r.get('kind')=='outcome'),None)
            if outcome:
                # Allow the worker's finally block to close its request journal.
                time.sleep(1)
                shutil.copy2(journal,folder/'operation.jsonl')
                sources=[];requests=[]
                for path in API.glob('polling_*/requests.jsonl'):
                    if path.stat().st_mtime < (folder/'baseline.json').stat().st_mtime:continue
                    raw=path.read_text(encoding='utf-8')
                    if request_id not in raw:continue
                    target=folder/(path.parent.name+'_requests.jsonl')
                    target.write_text(raw,encoding='utf-8');sources.append(str(path))
                    requests.extend(read_rows(path))
                writes=[r for r in requests if r['kind']=='request' and r['data'].get('method') in ('POST','PUT','DELETE','PATCH')]
                ids={r['data']['id'] for r in writes}
                save('api_handshakes.json',[r for r in requests if r.get('data',{}).get('id') in ids])
                save('native_events.json',[r for r in rows if r.get('kind')=='event'])
                final_state=h.call('GET','instruments/global-run-state')
                state('collecting_traces',request_id=request_id,native_state=final_state)
                warnings=[];commands=[]
                if final_state=='Idle':
                    for source in boundaries:
                        collected=[];seen=set();boundary=boundaries[source];reached=False
                        for offset in range(0,100000,1000):
                            # Do not collect traces across another newly started operation.
                            marker=API/'active.json'
                            if marker.exists() and json.loads(marker.read_text()).get('request_id')!=request_id:
                                warnings.append('Another operation started; trace collection stopped.');break
                            result=h.call('GET',f'traces?offset={offset}&limit=1000&sources={source}')
                            page=result.get('items',[])
                            for row in page:
                                if boundary and row.get('date','')<=boundary:reached=True;continue
                                key=json.dumps(row,sort_keys=True)
                                if key not in seen:seen.add(key);collected.append(row)
                            if reached or len(page)<1000:break
                            time.sleep(.2)
                        else:warnings.append(source+': 100,000-row capture limit reached; older entries may be missing.')
                        save('traces_'+source.replace(',','_')+'.json',collected)
                        for row in collected:
                            message=decoded(row.get('message'))
                            if source=='MNE,MLP' and isinstance(message,list) and message and isinstance(message[0],str):
                                commands.append(dict(controller_time=row.get('date'),source=row.get('source'),command=message[0],details=message[1:]))
                    save('final_snapshot.json',{p:h.call('GET',p) for p in ('instruments/global-run-state','calibration/channel-results','errors?offset=0&limit=30')})
                else:warnings.append('Native state is not Idle; no trace requests were added. Retrieve traces after termination.')
                save('command_sequence.json',sorted(commands,key=lambda x:x.get('controller_time') or ''))
                state('captured',request_id=request_id,outcome=outcome['data'],http_logs=sources,
                    api_write_count=len(writes),native_command_records=len(commands),warnings=warnings)
                print('CAPTURED',flush=True);return
        time.sleep(.5)
    state('stopped',request_id=request_id,message='Two-hour capture window ended or stop file requested; existing native journals retained.')


if __name__=='__main__':
    main()
