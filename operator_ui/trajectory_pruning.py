"""Offline loop-removal proposals. This module grants no hardware replay permission."""
import math
from autonomy import TransferError, check_path, wrap

XYZ=('X','Y','Z')


def distance(a,b):
    return math.dist([a[k] for k in XYZ],[b[k] for k in XYZ])


def prune_middle(start,joints,points,cfg):
    """Find a shorter ordered route using near-return bridges on the highest plateau.

    Only contiguous highest-height travel is eligible. All ascent/descent and
    approach points outside it remain verbatim. New connectors are <=5 mm and
    <=3 degrees, save >=20 mm, and retain the original IK branch. Clearance of
    every connector still needs review; these are not collision-free assertions.
    """
    vertices=[dict(start)]+[dict(p) for p in points]
    if len(vertices)<3:
        raise TransferError('Loop review needs at least two segments.')
    if any(not math.isfinite(p[k]) for p in vertices for k in (*XYZ,'Rz')):
        raise TransferError('Loop review received non-finite coordinates.')
    peak=max(p['Z'] for p in vertices)
    runs=[];begin=None
    for i,p in enumerate(vertices+[{'Z':peak-1}]):
        if peak-p['Z']<=.2:
            if begin is None:begin=i
        elif begin is not None:
            runs.append((begin,i-1));begin=None
    lo,hi=max(runs,key=lambda pair:pair[1]-pair[0])
    arc=[0.];qs=[dict(joints)]
    for a,b in zip(vertices,vertices[1:]):
        arc.append(arc[-1]+distance(a,b))
        qs.append(check_path(a,b,qs[-1],cfg,None))
    cost=[0.]+[math.inf]*len(points)
    previous=[None]*len(vertices)
    for i,a in enumerate(vertices[:-1]):
        candidates=[i+1]
        if lo<=i<hi:
            candidates.extend(range(i+2,hi+1))
        for j in candidates:
            b=vertices[j];length=distance(a,b)
            if j>i+1:
                if length>5 or abs(wrap(b['Rz']-a['Rz']))>3 or arc[j]-arc[i]-length<20:
                    continue
                try:
                    q=check_path(a,b,qs[i],cfg,None)
                except TransferError:
                    continue
                if any(abs(q[k]-qs[j][k])>.1 for k in ('J2','J3','J4')):
                    continue
            if cost[i]+length<cost[j]-1e-9:
                cost[j]=cost[i]+length;previous[j]=i
    indices=[len(vertices)-1]
    while indices[-1]:indices.append(previous[indices[-1]])
    indices.reverse()
    bridges=[];q=dict(joints)
    for i,j in zip(indices,indices[1:]):
        q=check_path(vertices[i],vertices[j],q,cfg,None)
        if any(abs(q[k]-qs[j][k])>.1 for k in ('J2','J3','J4')):
            raise TransferError('Pruned route changed the taught IK branch.')
        if j>i+1:
            bridges.append(dict(first=i,last=j,start=vertices[i],end=vertices[j],
                                removed_travel_mm=arc[j]-arc[i],connector_mm=distance(vertices[i],vertices[j]),
                                saved_mm=arc[j]-arc[i]-distance(vertices[i],vertices[j]),
                                yaw_change_deg=abs(wrap(vertices[j]['Rz']-vertices[i]['Rz'])),
                                clearance_review_required=True))
    output=[vertices[i] for i in indices[1:]]
    return output,dict(method='near_return_loop_removal_v1',execution_authorized=False,
                       original_length_mm=arc[-1],pruned_length_mm=cost[-1],saved_mm=arc[-1]-cost[-1],
                       saved_percent=100*(arc[-1]-cost[-1])/arc[-1] if arc[-1] else 0,
                       plateau_indices=[lo,hi],plateau_z_mm=peak,retained_indices=indices,
                       prefix_and_suffix_preserved=True,ik_passed=True,bridges=bridges)
