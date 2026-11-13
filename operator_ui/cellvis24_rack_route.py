"""Loaded Cellvis pickup connected to the pinned hotel-rack corridor.

Preserves old commissioned endpoints and records; transit137, contact5.
"""
import hashlib
import json
from autonomy import TransferError
from cellvis24_hamilton_route import FOLDER, PLAN_SHA as ORIGINAL_SHA, reference as original_reference
from hamilton_rack_clearance import FAST_SHA, fast_reference
from scope_step_trial import near
from short_side_direct_transfer import validate_plan_route

PLAN=FOLDER/'hamilton_rack_taught_pivot_plan_v2.json'
PLAN_SHA='69df95757fbd2a0b7fd4e978ee2d39736d4f9fc849992304604a2879bc585137'
PROFILES=('cellvis24_rack_forward','cellvis24_rack_reverse')

def reference():
    raw=PLAN.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PLAN_SHA:raise TransferError('Loaded Cellvis rack plan changed.')
    p=json.loads(raw);old=original_reference();rack,_=fast_reference()
    if p['parent_cellvis_sha256']!=ORIGINAL_SHA or p['rack_sha256']!=FAST_SHA:
        raise TransferError('Loaded rack source binding changed.')
    source=FOLDER/'hamilton_rack_loaded_plan.json'
    if hashlib.sha256(source.read_bytes()).hexdigest()!=p['parent_loaded_sha256']:
        raise TransferError('Loaded rack baseline changed.')
    from plan_cellvis24_taught_rack_pivot import SOURCE,SOURCE_SHA,CAPTURE_SHA,points_for
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest()!=SOURCE_SHA or p['parent_candidate_sha256']!=SOURCE_SHA or p['taught_pivot_sha256']!=CAPTURE_SHA:
        raise TransferError('Taught pivot source binding changed.')
    start=old['routes']['forward']['start']
    expected=points_for(start,rack['forward']['points'][-3:])
    if (p['routes']['forward']['start']!=start or p['routes']['forward']['points']!=expected):
        raise TransferError('Loaded rack connector changed.')
    if p['routes']['reverse']['points']!=list(reversed([start]+expected))[1:]:
        raise TransferError('Taught pivot reverse route changed.')
    return p

def validate_shape(start,points,profile):
    if profile not in PROFILES:raise TransferError('Unknown loaded Cellvis rack profile.')
    route=reference()['routes'][profile.rsplit('_',1)[1]]
    near(start,route['start'],.05)
    if points!=route['points']:raise TransferError('Loaded Cellvis rack geometry changed.')
    return route

def validate_speeds(start,points,profile,speeds):
    if speeds!=validate_shape(start,points,profile)['segment_speeds']:
        raise TransferError('Loaded rack requires transit137 and seating/departure5.')

def validate_route(start,points,joints,cfg,envelope,profile):
    return validate_plan_route(reference(),validate_shape(start,points,profile),start,points,joints,cfg,envelope)
