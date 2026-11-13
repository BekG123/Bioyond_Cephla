"""Pinned second demonstration, with its ordered constant-height turning arc."""
import json
from autonomy import TransferError
from scope_step_trial import near
from short_side_direct_transfer import validate_plan_route
from plan_hamilton_reteach_constant_height import SESSION, build

PLAN=SESSION/'constant_height_order_preserving_ik.json'
PROFILES=('cellvis24_recorded_forward','cellvis24_recorded_reverse')
SMOOTH_PROFILES=('cellvis24_smoothed_forward','cellvis24_smoothed_reverse')
OPPOSITE_PROFILES=('cellvis24_opposite_forward','cellvis24_opposite_reverse')


def profile_variant(profile):
    if profile in OPPOSITE_PROFILES:return 'opposite3'
    if profile in SMOOTH_PROFILES:return 'smooth3'
    if profile in PROFILES:return 'recorded'
    raise TransferError('Unknown recorded Hamilton profile.')


def plan_path(variant='recorded'):
    if variant=='opposite3':
        from hamilton_opposite_wrist_route import PLAN as opposite_plan
        return opposite_plan
    if variant=='recorded':return PLAN
    if variant in ('smooth3','blend3'):
        from plan_hamilton_smooth_transit import PLAN as smooth_plan
        return smooth_plan
    raise TransferError('Unknown recorded Hamilton variant.')


def reference(variant='recorded'):
    saved=json.loads(plan_path(variant).read_bytes())
    builder=build
    if variant in ('smooth3','blend3'):
        from plan_hamilton_smooth_transit import build as builder
    elif variant=='opposite3':
        from hamilton_opposite_wrist_route import build as builder
    if saved!=builder():raise TransferError('Recorded route or demonstration evidence changed.')
    return saved


def validate_shape(start,points,profile):
    route=reference(profile_variant(profile))['routes'][profile.rsplit('_',1)[1]]
    near(start,route['start'],.05)
    if points!=route['points']:raise TransferError('Recorded Hamilton point order/geometry changed.')
    return route


def validate_speeds(start,points,profile,speeds):
    if speeds!=validate_shape(start,points,profile)['segment_speeds']:
        raise TransferError('Recorded Hamilton transit/contact speeds changed.')


def validate_route(start,points,joints,cfg,envelope,profile):
    return validate_plan_route(reference(profile_variant(profile)),validate_shape(start,points,profile),start,points,joints,cfg,envelope)
