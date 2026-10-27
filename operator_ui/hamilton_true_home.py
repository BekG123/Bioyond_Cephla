"""Exact Hamilton departure prefix plus a direct, reviewable true-Home connection.

The exact Hamilton approach uses the accepted operator-taught endpoint.
The direct Home connector stays inside the ordinary workspace.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from autonomy import check_path, TransferError
from scope_step_trial import near

ROOT = Path(__file__).resolve().parent
PARENT = ROOT/'reports/trajectory_smoothing/entry_forward_3mm/candidate.json'
PARENT_HASH = '6d532ee8f22607688bee8943e05449415c7a0ad15c59a895f91cd3d251d3c420'
KEYS = ('X','Y','Z','Rz')
ENDPOINT = ROOT/'hamilton_endpoint.json'
RETURN_START = ROOT/'hamilton_return_start.json'
RETURN_START_HASH = '6978eb5e7a6a778e2fbfbe91bbdeaabd5ac6e4ffc7a0084be04c8bc7afbb7354'


def endpoint():
    """Read the active taught endpoint without rewriting historical trials."""
    data=json.loads(ENDPOINT.read_text(encoding='utf-8'))
    if data.get('schema')=='cephla.hamilton-endpoint.v2':
        from hamilton_accepted_route import evidence,HASHES
        reference=evidence()['candidate.json']
        if data.get('candidate_sha256')!=HASHES['candidate.json'] or data['pose']!=reference['endpoint']:
            raise TransferError('Hamilton endpoint differs from its accepted reference.')
        return data
    pose=data['pose']
    if data['parent_sha256']!=PARENT_HASH or any(
        type(pose.get(k)) not in (int,float) or not math.isfinite(pose[k]) for k in KEYS):
        raise TransferError('Hamilton endpoint reference is invalid.')
    if any(pose[k]!=v for k,v in dict(X=195.34,Y=-360.31,Rz=-1.9).items()):
        raise TransferError('Hamilton endpoint revision must preserve taught XY and wrist.')
    if not 0<=pose['Z']-data['reference_z_minus_j1_mm']<=400:
        raise TransferError('Hamilton endpoint exceeds vertical joint travel.')
    return data


def station_reference(original):
    config=endpoint()
    if config.get('schema')=='cephla.hamilton-endpoint.v2':
        from hamilton_accepted_route import evidence
        measured=evidence()['forward_speed137_trial.json']['final_robot']
        q=deepcopy(measured['joints']);q['J1']+=config['pose']['Z']-measured['pose_mm']['Z']
        return deepcopy(config['pose']),q
    reference=deepcopy(original['trajectory'][0])
    pose=deepcopy(endpoint()['pose'])
    q=reference['joints']
    q['J1']+=pose['Z']-reference['pose_mm']['Z']
    return pose,q


def departure_start(pose,review):
    """Allow the 5 mm station lift or a stopped start within that column."""
    if measured_departure(pose, review) is not None:
        return True
    target=review['reverse'][0]
    try:
        near({**pose,'Z':target['Z']},target,.05)
        return target['Z']<=pose['Z']<=target['Z']+5.05
    except (TransferError,KeyError,TypeError):
        return False


def measured_departure(pose, review):
    """Only the individually reviewed measured return start; no wider box."""
    reference = review.get('measured_return_start')
    if not reference:
        return None
    try:
        near(pose, reference['pose'], .05)
        return deepcopy(reference)
    except (TransferError, KeyError, TypeError):
        return None


def candidate(home, envelope):
    config=endpoint()
    if config.get('schema')=='cephla.hamilton-endpoint.v2':
        from hamilton_accepted_route import route
        return route(home,envelope,config)
    raw=PARENT.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PARENT_HASH:
        raise TransferError('The accepted Hamilton source changed.')
    route=json.loads(raw)['routes']['to_hamilton']
    old_lift,hover,hamilton=route['points']
    return_raw = RETURN_START.read_bytes()
    if hashlib.sha256(return_raw).hexdigest() != RETURN_START_HASH:
        raise TransferError('The measured Hamilton return reference changed; review it before travel.')
    return_reference = json.loads(return_raw)
    if (return_reference['parent_sha256'] != PARENT_HASH
            or math.dist([return_reference['pose'][k] for k in ('X','Y','Z')],
                         [hamilton[k] for k in ('X','Y','Z')]) > .6
            or abs(return_reference['pose']['Rz']-hamilton['Rz']) > .3):
        raise TransferError('The measured return start is outside its reviewed Hamilton reference.')
    height_reference=endpoint()
    hamilton=deepcopy(height_reference['pose'])
    # Stop inheriting the old box exception one millimeter inside the Y edge.
    y=envelope['Y'][0]+1.
    fraction=(y-hover['Y'])/(old_lift['Y']-hover['Y'])
    if not 0<fraction<1:
        raise TransferError('Hamilton workspace boundary needs review.')
    boundary={k:round(hover[k]+fraction*(old_lift[k]-hover[k]),2) for k in KEYS}
    home={k:home[k] for k in KEYS}
    if not all(envelope[k][0]<=p[k]<=envelope[k][1] for p in (boundary,home) for k in ('X','Y','Z')):
        raise TransferError('The new Hamilton connector must stay inside the workspace.')
    if math.dist([home[k] for k in ('X','Y','Z')],
                 [route['start'][k] for k in ('X','Y','Z')])<1:
        raise TransferError('Saved Home must not be the obsolete Home-area.')
    return dict(parent_sha256=PARENT_HASH,
                measured_return_start=return_reference,
                endpoint_reference=height_reference,
                reverse=[hamilton,hover,boundary,home],
                forward=[home,boundary,hover,hamilton],
                old_home_area=route['start'],
                physical_clearance_verified=False,
                envelope={k:list(v) for k,v in envelope.items()})


def configured():
    data=json.loads((ROOT/'points.json').read_text(encoding='utf-8-sig'))
    point=data['points'][data['roles']['home']]
    env=json.loads((ROOT/'envelope.json').read_text(encoding='utf-8-sig'))
    env=env.get('envelope',env)
    # The service stores {X:[low,high],...}; disk format uses min/max.
    env={k:(v['min'],v['max']) if isinstance(v,dict) else v for k,v in env.items() if k in ('X','Y','Z')}
    home=dict(X=point['x'],Y=point['y'],Z=point['z_grip'],Rz=point['rz'])
    return candidate(home,env)


def validate_route(start,points,review=None):
    review=review or configured()
    for direction in ('forward','reverse'):
        path=review[direction]
        if len(points)==len(path)-1 and points==path[1:]:
            if direction=='reverse' and departure_start(start,review):
                return review
            near(start,path[0],.05)
            return review
    raise TransferError('Hamilton/Home must use the exact direct route, without Home-area.')


def segment_envelope(start,end,envelope,review):
    reverse=review['reverse']
    if departure_start(start,review) and end==reverse[1]:
        return None  # Station lift or the pinned, individually reviewed return start.
    for a,b in zip(reverse[:2],reverse[1:3]):
        for first,last in ((a,b),(b,a)):
            try:
                near(start,first,.05);near(end,last,.011)
                return None  # Exact height-revised approach / original transit.
            except TransferError:
                pass
    return envelope


def check_route(start,points,joints,cfg,envelope,review=None):
    review=validate_route(start,points,review)
    if {k:list(v) for k,v in envelope.items()}!=review['envelope']:
        raise TransferError('Hamilton workspace changed.')
    q=deepcopy(joints);previous=start;offset=q['J1']-start['Z'];checked=[]
    if not 0<=q['J1']<=400:
        raise TransferError('Hamilton starting vertical joint is outside 0..400 mm.')
    for point in points:
        q=check_path(previous,point,q,cfg,segment_envelope(previous,point,envelope,review))
        q['J1']=point['Z']+offset
        if not 0<=q['J1']<=400 or abs(q['J3'])>180:
            raise TransferError('Hamilton joint travel limit exceeded.')
        checked.append(dict(pose=point,joints=deepcopy(q)))
        previous=point
    return q,checked


def requirement(review):
    if review.get('operator_accepted_both_directions'):
        return ('Use the accepted Home-Hamilton route at speed 137 through saved Home. '
                'Confirm the full arm, claw and any plate sweep is clear and the Hamilton holder remains in its taught position. '
                'Travel in both directions is accepted; pickup/release at the revised station remains a supervised trial.')
    b=review['reverse'][2];h=review['reverse'][-1]
    trial=('An empty-gripper round trip completed; loaded handling at this height is not yet validated. '
           if review['endpoint_reference'].get('automatic_trial_completed')
           else 'The revised height has not yet had an automatic trial. ')
    return (f'New direct Hamilton/Home connector: X{b["X"]:.2f}/Y{b["Y"]:.2f}/Z{b["Z"]:.2f} '
            f'to true Home X{h["X"]:.2f}/Y{h["Y"]:.2f}/Z{h["Z"]:.2f}, including wrist rotation. '
            'Confirm the full arm, claw and any plate sweep is clear before this run. '
            f'Hamilton arrival is now Z{review["reverse"][0]["Z"]:.2f} mm, near J1 zero; '
            +trial+
            'IK checks do not verify physical clearance.')
