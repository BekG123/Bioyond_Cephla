"""Pinned HOME proof-lift -> clearance -> scanner path; no IDLE waypoint."""
import math
from autonomy import TransferError, check_path
from scope_step_trial import near
from scanner_empty_route import TARGET, TRIAL, KEYS

PROFILE_SHA='1ddb2a2a3029eacb34317581d204cca62c68fc992420c49140e9b8efee0a09bc'


def geometry():
    from plate48_workflow import reference
    profile,digest,_=reference()
    if digest!=PROFILE_SHA:raise TransferError('Direct scanner pickup geometry changed; review required.')
    quantize=lambda p:{k:math.floor(p[k]*100+.5)/100 for k in KEYS}
    seat=profile['candidate_endpoint']
    start=quantize(dict(seat,Z=seat['Z']+5))
    points=[dict(start,Z=300.),dict(TARGET,Z=300.),dict(TARGET)]
    return dict(start=start,points=points,profile_sha256=digest,clearance_z_mm=300.,idle_travel=False)


def prepare(start,joints,points,cfg,envelope):
    g=geometry()
    if any(type(p.get(k)) not in (int,float) or not math.isfinite(p[k]) for p in [start]+list(points) for k in KEYS):
        raise TransferError('Direct scanner route requires finite coordinates.')
    near(start,g['start'],.05)
    if points!=g['points'] or {k:tuple(v) for k,v in envelope.items()}!=TRIAL:
        raise TransferError('Exact direct scanner clearance route and workspace required.')
    q=dict(joints);previous=start;offset=q['J1']-start['Z']
    for point in points:
        q=check_path(previous,point,q,cfg,envelope);q['J1']=point['Z']+offset
        if not math.isfinite(q['J1']) or not 0<=q['J1']<=400 or abs(q['J3'])>180:
            raise TransferError('Direct scanner route exceeds joint travel.')
        previous=point
    return [dict(p) for p in points],q
