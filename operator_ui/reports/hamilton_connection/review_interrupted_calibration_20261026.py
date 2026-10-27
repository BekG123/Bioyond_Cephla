"""Review the operator-resolved interrupted run; no hardware writes or success claim."""
import json
from pathlib import Path
import sys
import time
from urllib.request import urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from hamilton_prep import HamiltonPrep


def main():
    root=Path(__file__).resolve().parents[1]/'hamilton_api'
    marker=root/'active.json'
    original=json.loads(marker.read_text(encoding='utf-8'))
    request_id='d104f3dffc744d67aa15c3d944a4bfea'
    assert original['request_id']==request_id
    journal=root/(request_id+'.jsonl')
    rows=[json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
    outcome=next(row['data'] for row in reversed(rows) if row['kind']=='outcome')
    assert outcome['status']=='failed_or_uncertain' and outcome['abort_sent'] is True
    with urlopen('http://127.0.0.1:5002/state',timeout=8) as response:console=json.load(response)
    assert not console['sequence']['active']
    adapter=HamiltonPrep()
    snapshots=[]
    for _ in range(2):
        current=adapter.status(fresh=True)
        assert current['connected'] and current['global_state']=='Idle'
        assert current['run']['isRunInProgress'] is False and current['pending_errors']==[]
        verification=adapter.call('GET','verification/status')
        assert not any(verification.get(k) for k in ('isWorkflowInProgress','isRunInProgress','isServiceRoutineInProgress'))
        assert adapter.call('GET','service-software-api/has-tips') is False
        snapshots.append(dict(state=current,verification=verification))
    destination=root/(request_id+'_reviewed_interruption.json')
    archived=root/(request_id+'_archived_active.json')
    assert not destination.exists() and not archived.exists()
    review=dict(at=time.time(),request_id=request_id,original_marker=original,original_outcome=outcome,
        operator_statement='Ignore the collision that just happened. I fixed it.',
        decision='Interrupted run verified inactive after operator recovery; archive stale ownership.',
        calibration_completed=False,hardware_writes=0,robot_access_authorized=False,
        current_evidence=snapshots,initialization_required=not snapshots[-1]['state']['initialized'])
    destination.write_text(json.dumps(review,indent=2),encoding='utf-8')
    with journal.open('a',encoding='utf-8') as out:
        out.write(json.dumps(dict(at=time.time(),kind='operator_interruption_review',data=review))+'\n')
    marker.rename(archived)
    print(json.dumps(dict(stale_ownership_archived=True,calibration_completed=False,
        initialization_required=review['initialization_required'],hardware_writes=0)))


if __name__=='__main__':main()
