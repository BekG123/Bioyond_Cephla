"""Pinned first Cellvis Hamilton delivery; preserves the accepted overhead shape.

The entire route is 2 mm higher to match the accepted Cellvis gripping height.
This trial stops held at site 4. No release, instrument operation or recovery.
"""
import hashlib
import json
import math
from pathlib import Path
import time
from urllib.request import urlopen

from autonomy import TransferError
from home_hamilton_exchange import native
from run_record_io import write_run_record
from scope_step_trial import near, preflight
from short_side_direct_transfer import validate_plan_route

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'operator_ui/reports/plate_session/cellvis24_validation'
PLAN=FOLDER/'hamilton_route_plan.json'
PLAN_SHA='cd04e2ea4aaa495a0fa801fbb2cec11ee8263cac49cdce600542144e4af31f98'
PROFILES=('cellvis24_hamilton_forward','cellvis24_hamilton_reverse')
OUTPUT=FOLDER/'hamilton_delivery_trial.json'


def reference():
    raw=PLAN.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PLAN_SHA:raise TransferError('Cellvis Hamilton plan changed.')
    p=json.loads(raw)
    for path,key in [(ROOT/'Pick and Hold/Calibration/plate_profiles/cellvis_p24_1_5h_n.json','profile_sha256'),
                     (FOLDER/'short_side_grip_lift_trial.json','source_sha256'),
                     (FOLDER/'short_side_grip_acceptance.json','acceptance_sha256')]:
        if hashlib.sha256(path.read_bytes()).hexdigest()!=p[key]:raise TransferError('Cellvis acceptance binding changed: '+key)
    from short_side_hover_transfer import reference as parent_reference
    parent,_,_=parent_reference('04')
    if hashlib.sha256(json.dumps(parent['routes']['forward'],sort_keys=True).encode()).hexdigest()!=p['parent_route_sha256']:
        raise TransferError('Parent Hamilton route changed.')
    return p


def validate_shape(start,points,profile):
    if profile not in PROFILES:raise TransferError('Unknown Cellvis Hamilton direction.')
    p=reference();route=p['routes'][profile.rsplit('_',1)[1]]
    near(start,route['start'],.05)
    if points!=route['points']:raise TransferError('Cellvis queue differs from the pinned overhead route.')
    return route


def validate_speeds(start,points,profile,speeds):
    route=validate_shape(start,points,profile)
    if speeds!=route['segment_speeds']:raise TransferError('Cellvis speeds must retain transit137 and final seating/departure5.')


def validate_route(start,points,joints,cfg,envelope,profile):
    p=reference();route=validate_shape(start,points,profile)
    return validate_plan_route(p,route,start,points,joints,cfg,envelope)


def instrument_ready():
    # Read only. Hamilton is independently controlled; never start/park it here.
    with urlopen('http://127.0.0.1:5002/researcher/api/lacry/hamilton/status',timeout=10) as response:
        h=json.load(response)
    return validate_instrument_state(h)


def validate_instrument_state(h):
    """Same readiness contract for console and direct instrument status reads."""
    if (not h.get('connected') or h.get('global_state')!='Idle' or h.get('parked') is not True
            or h.get('pending_errors') or h.get('operation')):
        raise TransferError('Hamilton must remain idle, parked and error-free.')
    return {k:h.get(k) for k in ('connected','global_state','parked','pending_errors','operation')}


def plan(service,cfg):
    if OUTPUT.exists():raise TransferError('This Cellvis delivery was already attempted; inspect its receipt.')
    p=reference();route=p['routes']['forward'];s=preflight(service);n=native(service)
    if n['moving'] or not math.isfinite(n['external_axes']['E1']) or abs(n['external_axes']['E1']-25)>.1:
        raise TransferError('Stationary accepted short-side grip required.')
    validate_route(s['pose_mm'],route['points'],s['joints'],cfg,service.envelope,PROFILES[0])
    from trajectory_queue import LuaTrajectory
    capability=LuaTrajectory(service).capability()
    if not capability.get('available') or capability.get('version')!=220109:
        raise TransferError('Mixed-speed Lua queue220109 required.')
    return dict(plan_sha256=PLAN_SHA,start=s['pose_mm'],joints=s['joints'],points=route['points'],
                segment_speeds=route['segment_speeds'],speed=137,grip_e1_mm=25,
                hamilton=instrument_ready(),stop_before_release=True)


def execute(run,service,cfg,approved):
    fresh=plan(service,cfg)
    for key in ('plan_sha256','points','segment_speeds','speed','grip_e1_mm','stop_before_release'):
        if approved.get(key)!=fresh[key]:raise TransferError('Cellvis delivery changed after review.')
    near(fresh['start'],approved['start'],.05)
    if any(abs(fresh['joints'][k]-approved['joints'][k])>.1 for k in ('J1','J2','J3','J4')):
        raise TransferError('Starting joint configuration changed.')
    record=dict(status='started',plan=fresh,samples=[],gripper_commands=False,
                operator_station_support_acceptance=None,motion_sent=False)
    with OUTPUT.open('x') as stream:json.dump(record,stream,indent=2)
    def save():write_run_record(OUTPUT,record)
    def check(stationary=False):
        s=preflight(service);n=native(service)
        if run.stopped() or (stationary and n['moving']):raise TransferError('Stopped or unexpected motion.')
        if not math.isfinite(n['external_axes']['E1']) or abs(n['external_axes']['E1']-25)>.1:
            raise TransferError('Grip position changed; stop before continuing.')
        record['samples'].append(dict(at=time.time(),pose=s['pose_mm'],axes=n['external_axes']));save()
        return s
    try:
        check(True);instrument_ready()
        run.say('Cellvis: one Lua queue to Hamilton; transit137, final seating5; keep plate held.')
        record['motion_sent']=True;save()
        from trajectory_queue import LuaTrajectory
        result=LuaTrajectory(service).execute(run,fresh['start'],fresh['joints'],fresh['points'],cfg,137,
            lambda *args:check(),reviewed=True,hamilton_short_side=PROFILES[0],segment_speeds=fresh['segment_speeds'])
        if not result.get('ok') or result.get('recovered'):raise TransferError('Cellvis delivery uncertain; no retry.')
        s=check(True);near(s['pose_mm'],fresh['points'][-1],.1)
        record.update(status='at_hamilton_held_support_inspection_pending',result=result,final=s)
        return dict(ok=True,record=str(OUTPUT),pose_mm=s['pose_mm'],payload='held',support_inspection_required=True)
    except Exception as error:
        record.update(status='failed_or_uncertain',error=str(error))
        if record['motion_sent']:
            try:record['stop_response']=service.program('stop')
            except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:record['finished_at']=time.time();save()
