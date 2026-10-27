"""Observe a touchscreen calibration; GETs and passive event subscriptions only."""
import json
from pathlib import Path
import time
import sys
import re
from urllib.parse import urlencode
from datetime import datetime, timezone
from hamilton_prep import HamiltonPrep, PrepEvents

def main():
    adapter=HamiltonPrep()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder=Path(__file__).resolve().parent/'reports/hamilton_connection'/('calibration_comparison_'+stamp)
    folder.mkdir(parents=True,exist_ok=False)
    def save(name,value):
        (folder/name).write_text(json.dumps(value,indent=2),encoding='utf-8')
    if '--history-only' in sys.argv:
        # API time filters use controller-local time, not workstation time.
        samples={}
        for name,minute in [('lacry','17'),('touchscreen','20')]:
            query=urlencode(dict(offset=0,limit=1000,sources='RCE,MNE,MLP',
                startTime=f'2026-10-24 09:{minute} PM',endTime=f'2026-10-24 09:{int(minute)+1:02} PM'))
            rows=adapter.call('GET','traces?'+query)
            save(name+'_command_traces.json',rows)
            packets=[]
            for row in rows.get('items',[]):
                if not f'2026-10-25T04:{minute}:00' <= row.get('date','') < f'2026-10-25T04:{int(minute)+1:02}:00':continue
                msg=row.get('message','')
                if 'Type=Send' not in msg or 'Dst=0x0001.0x0001.0x1300' not in msg:continue
                match=re.search(r'Message=([0-9A-Fa-f]+)',msg)
                if match and '010306000006' in match[1]:
                    packets.append(dict(date=row['date'],parameters=match[1].split('010306000006',1)[1]))
            samples[name]=packets
        samples['same_parameters']=bool(samples['lacry'] and samples['touchscreen'] and samples['lacry'][0]['parameters']==samples['touchscreen'][0]['parameters'])
        save('command_comparison.json',samples)
        print(json.dumps(dict(folder=str(folder),comparison=samples)))
        return
    def snapshot(label):
        for name,path in [('status','instruments/global-run-state'),('run','protocol-run'),
                          ('traces','traces?offset=0&limit=1000'),('errors','errors?offset=0&limit=50'),
                          ('channel_results','calibration/channel-results')]:
            save(label+'_'+name+'.json',adapter.call('GET',path))
    snapshot('before')
    rows=[]
    with PrepEvents(adapter) as events:
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            rows.extend(dict(at=time.time(),channel=c,event=e) for c,e in events.drain())
            time.sleep(.25)
        rows.extend(dict(at=time.time(),channel=c,event=e) for c,e in events.drain())
    save('events.json',rows)
    snapshot('after')
    print(json.dumps(dict(folder=str(folder),events=len(rows))))

if __name__=='__main__':main()
