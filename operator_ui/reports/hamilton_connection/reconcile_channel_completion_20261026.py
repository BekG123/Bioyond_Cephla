"""Reconcile one finished run against its recorded native event lifecycle.

Hardware GETs only. Retains the original error and does not write a vendor Pass.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
from urllib.request import urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from hamilton_prep import HamiltonPrep,decoded


def main():
    root=Path(__file__).resolve().parents[1]/'hamilton_api'
    request_id='e35f44182a614ff3abeba79c4c3574cc'
    marker=root/'active.json'
    previous=json.loads(marker.read_text(encoding='utf-8'))
    assert previous['request_id']==request_id and previous['status']=='finished_unverified'
    assert previous['error'].startswith('Hamilton finished and is Idle, but did not publish')
    with urlopen('http://127.0.0.1:5002/state',timeout=8) as response:state=json.load(response)
    assert not state['sequence']['active']
    journal=root/(request_id+'.jsonl')
    rows=[json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
    ticket=deepcopy(previous)
    ticket.update(status='running',calibration_cleanup={})
    ticket.pop('channel_activity',None);ticket.pop('channel_finished_after_cleanup',None)
    channel_started=False;evidence=[]
    for row in rows:
        data=row.get('data')
        if not isinstance(data,dict):continue
        if row['kind']=='request' and data.get('path')=='calibration/channel-height-squeeze':channel_started=True
        if not channel_started:continue
        if row['kind']=='cleanup_completed':
            assert data['id']==previous['calibration_cleanup']['id'] and data['event']=='CleanupFinished'
            ticket['calibration_cleanup']=dict(id=data['id'],phase='complete');evidence.append(row)
        if row['kind']!='event':continue
        event=data.get('event')
        if not isinstance(event,dict):continue
        assert event.get('code') not in ('failed','error','aborted')
        assert data.get('channel')!='connection_lost'
        payload=decoded(event.get('data'))
        if isinstance(payload,dict):
            HamiltonPrep.track_channel_activity(ticket,payload)
            if payload.get('Source')=='Xsl' and payload.get('Name') in ('ActivityStarted','ActivityEnded'):
                evidence.append(row)
        if event.get('code')=='finished' and ticket['calibration_cleanup'].get('phase')=='complete':
            ticket['channel_finished_after_cleanup']=True;evidence.append(row)
    adapter=HamiltonPrep()
    current=adapter.status(fresh=True)
    assert HamiltonPrep.channel_lifecycle_completed(ticket,current,None)
    # Parking is a separate robot-access requirement. Ending ownership of an
    # already terminated calibration must not declare the instrument parked.
    parked=adapter.call('GET','service-software-api/is-parked')
    assert adapter.call('GET','service-software-api/has-tips') is False
    # Preserve the history as evidence, without creating or modifying an entry.
    history=adapter.call('GET','calibration/channel-results')
    record=dict(at=time.time(),request_id=request_id,source='native_lifecycle',
        procedure_completed=True,numerical_result_verified=False,
        original_outcome=previous,event_evidence=evidence,current=current,history=history,
        controller_writes=0,parked=parked,robot_access_authorized=False,
        decision='Reviewed native completion; archive stale ownership. No procedure replay or robot-access authorization.')
    folder=root/'polling_20261027T005850Z_87619227'
    destination=folder/'native_completed_reviewed_active.json'
    assert not destination.exists()
    (folder/'native_completion_reconciliation.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    with journal.open('a',encoding='utf-8') as out:
        out.write(json.dumps(dict(at=time.time(),kind='native_completion_reconciled',data=record))+'\n')
    marker.rename(destination)
    print(json.dumps(dict(request_id=request_id,procedure_completed=True,numerical_result_verified=False,controller_writes=0)))


if __name__=='__main__':main()
