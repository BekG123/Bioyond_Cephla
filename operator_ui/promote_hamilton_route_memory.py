"""Update Lacry's versioned notes for the accepted Hamilton route; no motion."""
import json
from pathlib import Path
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parent
BASE='http://127.0.0.1:5002/developer/api/lacry-memory'


def request(url,body=None):
    req=Request(url,data=None if body is None else json.dumps(body).encode(),
                headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=15) as response:return json.load(response)


def main():
    seed=next(x for x in json.loads((ROOT/'lacry_memory_seed.json').read_text())
              if x['id']=='hamilton-revised-route-accepted-20261026')
    rows=request(BASE+'?q=Hamilton')['items'];changes=[]
    for row in rows:
        if row['status']!='approved':continue
        body=row['body'];status='approved'
        if row['title']=='True Home is the intermediate station':body=seed['body']
        elif row['title']=='Hamilton near-zero J1: successful empty-gripper round trip':status='archived'
        elif row['title']=='Station handling: Squid accepted; Hamilton supervised trials available':
            body=body.replace('Hamilton travel has two successful empty-gripper trials;',
                'The revised October26 Hamilton travel passed both directions with operator acceptance; payload was not recorded;')
            body=body.replace('Hamilton seated X195.34 Y-360.31 Z38.61 Rz-1.90, liftedZ43.61.',
                'Current Hamilton seated X144.50 Y-350.68 Z61.22 Rz-3.00, liftedZ66.22. Old-location handling history does not validate the new local handoff.')
        elif row['title']=='Hamilton travel and supervised handoffs exist; preserve tip-pair counts':
            body=body.replace('The current saved route matches the completed Oct 20 empty-gripper round trip.',
                'The current route is the operator-accepted October26 Home-Hamilton revision; the Oct20 route and handoffs below are historical at the previous station pose, not validation of current pickup/release.')
        if body!=row['body'] or status!=row['status']:
            result=request(BASE+'/'+row['id'],dict(revision=row['revision'],status=status,body=body))
            changes.append(dict(id=row['id'],before_revision=row['revision'],after=result['item']))
    output=ROOT/'reports/trajectory_smoothing/hamilton_reteach_20261026/memory_integration.json'
    # API edits have their own persistent revision log even if this report's
    # filesystem write was interrupted. Include that history on an idempotent rerun.
    exported=request(BASE+'/export')
    titles={'True Home is the intermediate station',
            'Hamilton near-zero J1: successful empty-gripper round trip',
            'Station handling: Squid accepted; Hamilton supervised trials available',
            'Hamilton travel and supervised handoffs exist; preserve tip-pair counts'}
    selected=[r for r in exported['memories'] if r['title'] in titles]
    ids={r['id'] for r in selected}
    record=dict(changes_this_invocation=changes,current=selected,
                revisions=[r for r in exported['revisions'] if r['memory_id'] in ids])
    with output.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    print(json.dumps(dict(updated=len(changes),report=str(output))))


if __name__=='__main__':main()
