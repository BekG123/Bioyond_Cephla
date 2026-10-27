"""One-shot trials in each direction on the reviewed four-point scope route."""
import hashlib
import json
import math
from pathlib import Path
from autonomy import TransferError, check_path
from scope_step_trial import near, preflight, execute as execute_steps

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'operator_ui/reports/squid/compact4_20261017T131133Z_ace8e9/candidate.json'
OUTPUT=PLAN.with_name('compact4_reverse_speed40_trial.json')
KEYS=('X','Y','Z','Rz')


def trial_output(forward=False):
    return OUTPUT.with_name('compact4_forward_speed40_trial.json') if forward else OUTPUT


def review(service,cfg,forward=False):
    if trial_output(forward).exists():raise TransferError('Four-point trial already attempted; inspect before retry.')
    raw=PLAN.read_bytes();plan=json.loads(raw)
    if cfg!=plan['params']:raise TransferError('Joint policy differs from the reviewed candidate.')
    if any(list(service.envelope[k])!=plan['envelope'][k] for k in KEYS[:3]):raise TransferError('Workspace changed.')
    source=Path(plan['source_trial']);source_raw=source.read_bytes()
    if hashlib.sha256(source_raw).hexdigest()!=plan['source_sha256']:raise TransferError('Accepted baseline changed.')
    baseline=json.loads(source_raw)
    if baseline['status']!='completed':raise TransferError('Successful baseline required.')
    route=list(reversed([plan['start']]+plan['points']))
    if len(route)!=5:raise TransferError('Exactly four reverse moves required.')
    home_file=json.loads((ROOT/'operator_ui/points.json').read_text(encoding='utf-8-sig'))
    h=home_file['points'][home_file['roles']['home']]
    near(route[-1],dict(X=h['x'],Y=h['y'],Z=h['z_grip'],Rz=h['rz']),.001)
    # Validate the agreed shape: short insertion withdrawal, two level legs,
    # then descent to exact Home. Do not accept arbitrary supplied targets.
    if route[0]!=baseline['steps'][-1]['target'] or route[1]!=baseline['steps'][-2]['target']:raise TransferError('Accepted final approach changed.')
    if any(abs(p['Z']-286.24)>.001 for p in route[1:4]):raise TransferError('Reviewed transit height changed.')
    if any(abs(route[3][k]-route[4][k])>.001 for k in ('X','Y','Rz')):raise TransferError('Home descent must be vertical with fixed yaw.')
    expected_joints=baseline['final_robot']['joints']
    if forward:
        route=list(reversed(route))
        near(route[0],baseline['plan']['start'],.001)
        expected_joints=baseline['steps'][0]['joints_before']
    state=preflight(service);near(state['pose_mm'],route[0],.05)
    for k in ('J1','J2','J3','J4'):
        if abs(state['joints'][k]-expected_joints[k])>.5:raise TransferError('Starting joint winding/configuration changed: '+k)
    previous=route[0];q=state['joints'];j1offset=q['J1']-state['pose_mm']['Z']
    for point in route[1:]:
        q=check_path(previous,point,q,cfg,service.envelope)
        if not 0<=point['Z']+j1offset<=400 or abs(q['J3'])>180:raise TransferError('J1/J3 travel limit')
        previous=point
    e1=service.external_axes().get('E1')
    if type(e1) not in (float,int) or not math.isfinite(e1):raise TransferError('Missing E1 position feedback.')
    return dict(plan_sha256=hashlib.sha256(raw).hexdigest(),start=route[0],points=route[1:],
        speed=40,executor='individual_MoveL',e1_start=e1,cfg=cfg,envelope=plan['envelope'])


def execute(run,service,cfg,approved):
    return execute_steps(run,service,cfg,approved,review_fn=review,output=OUTPUT,label='Home',
        authorization='Operator requested scope to Home and confirmed new Z286.24 corridor via X354 Y270 clear, arm released and E-stop supervised. Individual moves at speed 40; no Lua queue.')


def review_forward(service,cfg):
    return review(service,cfg,forward=True)


def execute_forward(run,service,cfg,approved):
    return execute_steps(run,service,cfg,approved,review_fn=review_forward,
        output=trial_output(True),label='Scope',
        authorization='Operator requested Home to scope using the same cleared Z286.24 corridor via X354 Y270 just completed in reverse, with E-stop supervision. Four individual moves at speed 40; accepted final placement approach preserved.')
