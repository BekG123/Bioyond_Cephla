"""Offline checkpoint before the final seating segment that reported collision."""
import json,time
from copy import deepcopy
from projected_pickup import ROOT,sha
from scope_compact137 import accepted
from autonomy import check_path

F=ROOT/'operator_ui/reports/projected_alignment'
SOURCE=F/'squid_48well_endpoint_reteach_e2_candidate_20261027.json'
OUT=F/'squid_48well_clearance_20261027_candidate.json'

def main():
    if OUT.exists():raise RuntimeError('Preserve existing checkpoint candidate')
    raw=SOURCE.read_bytes()
    if sha(raw)!='eed5d90ca04fc2c6f263bedc842993cd28769c5268368d5e602786228dc00d6f':
        raise RuntimeError('Reviewed source changed')
    p=json.loads(raw);_,_,_,trials=accepted()
    route=deepcopy(p['routes']['forward']);route[-1]['Z']=270.
    env={k:tuple(v) for k,v in p['envelope'].items()}
    q=deepcopy(trials['reverse']['final_robot']['joints']);offset=q['J1']-route[0]['Z'];checked=[]
    for name,path in [('forward',route),('reverse',list(reversed(route)))]:
        for start,end in zip(path,path[1:]):
            q=check_path(start,end,q,p['cfg'],env);q['J1']=end['Z']+offset
            if not 0<=q['J1']<=400 or abs(q['J3'])>180:raise RuntimeError('J1/J3 limit')
            checked.append(dict(direction=name,target=end,joints=deepcopy(q)))
    result=dict(at=time.time(),status='offline_checked_pending_supervised_trial',
        parent_candidate_sha256=sha(raw),parent_route=p['parent_route'],cfg=p['cfg'],envelope=p['envelope'],
        routes=dict(forward=route,reverse=list(reversed(route))),validation=checked,
        transit_speed=137,descent_speed=5,release_authorized=False,
        endpoint_kind='clearance_checkpoint_not_seated_endpoint',
        reason='Stop 1.53 mm above the previous requested seating height; collision was first observed after a healthy sample at Z268.902. Physical inspection required before any lower motion or release.',
        seating_verified=False,hardware_commands_sent=False)
    with OUT.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2)
    print(json.dumps(dict(path=str(OUT),sha256=sha(OUT.read_bytes()),target=route[-1])))

if __name__=='__main__':main()
