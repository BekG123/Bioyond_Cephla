"""Explicit opt-in taught three-target Hamilton trial, preserving old routes."""
import json
from autonomy import TransferError
from scope_step_trial import near
from short_side_direct_transfer import validate_plan_route
from plan_hamilton_home_three_waypoints import OUTPUT, build
from cellvis24_rack_route import reference as parent_reference

PROFILES = ('cellvis24_taught_three_forward', 'cellvis24_taught_three_reverse')


def reference():
    saved = json.loads(OUTPUT.read_bytes())
    if saved != build():
        raise TransferError('Three-waypoint candidate or teaching evidence changed.')
    saved['global_envelope'] = parent_reference()['global_envelope']
    return saved


def validate_shape(start, points, profile):
    if profile not in PROFILES:
        raise TransferError('Unknown three-waypoint profile.')
    route = reference()['routes'][profile.rsplit('_', 1)[1]]
    near(start, route['start'], .05)
    if points != route['points']:
        raise TransferError('Three-waypoint geometry changed.')
    return route


def validate_speeds(start, points, profile, speeds):
    if speeds != validate_shape(start, points, profile)['segment_speeds']:
        raise TransferError('Three-waypoint speeds changed.')


def validate_route(start, points, joints, cfg, envelope, profile):
    return validate_plan_route(reference(), validate_shape(start, points, profile),
                               start, points, joints, cfg, envelope)
