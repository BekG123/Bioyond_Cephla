"""IDLE wrist-turn location taught after the hotel rack installation.

Pure IK planning: no robot access, fault recovery or clearance claims.
"""
import hashlib
import json
import math
from pathlib import Path

from autonomy import TransferError, check_path, wrap

REFERENCE = Path(__file__).resolve().parent/'reports/hamilton_empty_clearance/taught_idle_pivot_20261111.json'
REFERENCE_SHA = '57e6441b174de238726f79093415d96eccea71fd3f14d36dcc841a80ca2b536f'


def reference():
    raw=REFERENCE.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=REFERENCE_SHA:
        raise TransferError('Taught IDLE pivot changed; review its reference before travel.')
    return json.loads(raw)


def validate_rotation(start,points):
    d=reference();pivot=d['commanded_pivot']
    if len(points)!=1:raise TransferError('IDLE pivot turn requires one continuous command.')
    end=points[0]
    for pose in (start,end):
        if any(type(pose.get(k)) not in (int,float) or not math.isfinite(pose[k]) for k in ('X','Y','Z','Rz')):
            raise TransferError('Invalid IDLE pivot pose.')
        if any(abs(pose[k]-pivot[k])>.02 for k in ('X','Y','Z')):
            raise TransferError('IDLE wrist turn must stay at the taught pivot.')
    if any(abs(end[k]-start[k])>.006 for k in ('X','Y','Z')):
        raise TransferError('IDLE wrist turn cannot translate.')
    if abs(wrap(end['Rz']-d['idle']['Rz']))>.001 or abs(end['Rz']-start['Rz'])>180.001:
        raise TransferError('IDLE pivot turn must end at IDLE yaw along the checked short arc.')


def stages_for_idle(start,target,joints,params,envelope):
    """Return stages for the taught IDLE target, or None for other targets.

    Translation to the pivot retains the starting wrist angle. Rotation occurs
    only at the taught pivot; the subsequent IDLE translation retains its yaw.
    """
    d=reference()
    if any(abs(target[k]-d['idle'][k])>.001 for k in ('X','Y','Z','Rz')):
        return None
    delta=wrap(target['Rz']-start['Rz'])
    if abs(delta)<=.01:
        return None  # Existing direct translation already needs no wrist turn.
    from trajectory_queue import prepare_points
    pivot=d['commanded_pivot'];current={k:start[k] for k in ('X','Y','Z','Rz')}
    q=dict(joints);offset=q['J1']-current['Z'];stages=[]

    def checked(point):
        nonlocal q,current
        q=check_path(current,point,q,params,envelope)
        q['J1']=point['Z']+offset
        if not 0<=q['J1']<=400 or abs(q['J3'])>180:
            raise TransferError('IDLE pivot route exceeds joint travel.')
        current=dict(point)

    def queue(points):
        # Remove exact no-ops, retaining a small rise to the rotation minimum.
        cleaned=[];previous=current
        for point in points:
            point={k:math.floor(point[k]*100+.5)/100 for k in current}
            if abs(point['Z']-previous['Z'])>.001 or math.hypot(point['X']-previous['X'],point['Y']-previous['Y'])>.02:
                cleaned.append(point);previous=point
        if not cleaned:return
        cleaned,_=prepare_points(current,q,cleaned,params,reviewed=True,home_transit=True)
        for point in cleaned:checked(point)
        stages.append(dict(kind='queue',points=cleaned))

    height=max(pivot['Z'],current['Z'])
    queue([dict(current,Z=height),
           dict(X=pivot['X'],Y=pivot['Y'],Z=height,Rz=start['Rz']),
           dict(X=pivot['X'],Y=pivot['Y'],Z=pivot['Z'],Rz=start['Rz'])])
    origin=current['Rz'];delta=wrap(target['Rz']-origin)
    yaw=origin+delta
    end=dict(current,Rz=yaw)
    validate_rotation(current,[end]);checked(end)
    stages.append(dict(kind='rotate',rz=yaw,queued_pivot=True))
    # Keep yaw numerically continuous through the final translations.
    arrival=dict(target,Rz=current['Rz'])
    queue([dict(arrival,Z=pivot['Z']),arrival])
    return stages
