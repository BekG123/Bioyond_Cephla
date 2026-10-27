"""Hamilton local geometry/evidence for the shared station-handling executor.

Travel evidence records its payload scope. Local jaw/lift handling remains a supervised trial.
"""
import hashlib
import json

from autonomy import TransferError, check_path
from hamilton_true_home import ROOT, ENDPOINT, endpoint
from scope_step_trial import near

TRIAL=ROOT/'reports/hamilton/zero_roundtrip_20261020T113537Z.json'


def travel_status():
    """Report saved evidence separately from present clearance/plate handling."""
    try:
        from hamilton_true_home import configured
        _,_,hashes=reference()
        route=configured()
        if route.get('operator_accepted_both_directions'):
            return dict(saved=True,travel_verified=True,empty_travel_verified=False,
                payload_verified=False,operator_accepted_both_directions=True,
                route='Home <-> Hamilton',evidence='reports/trajectory_smoothing/hamilton_reteach_20261026',
                evidence_hashes=hashes,motion_authorized=False,
                message='Both directions of the revised Home-Hamilton route are operator-accepted at speed137. Pickup/release at the new endpoint remains a supervised trial.')
        trial=json.loads(TRIAL.read_bytes())
        for phase,direction in zip(trial['phases'],('reverse','forward')):
            steps=phase['plan']['steps']
            if len(steps)!=1 or steps[0]['points']!=route[direction][1:]:
                raise TransferError('The current Hamilton route differs from the completed travel trial.')
        return dict(saved=True,empty_travel_verified=True,
            route='Home <-> Hamilton',evidence=str(TRIAL.relative_to(ROOT)),
            evidence_hashes=hashes,motion_authorized=False,
            message='The saved Home-Hamilton route has a completed empty-gripper round trip. Loaded handling and current readiness are checked separately.')
    except Exception as error:
        return dict(saved=False,empty_travel_verified=False,motion_authorized=False,message=str(error))


def handling_history():
    """Recovered supervised runs are history, not unattended commissioning."""
    path=ROOT/'reports/hamilton/loaded_handling_history.json'
    try:
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!='dcb976dc3926b62bdbe394125e14705e068d73cfc48c5c02366ede5c2505f284':
            raise TransferError('Recovered Hamilton history changed; review its original audit records.')
        record=json.loads(raw)
        _,_,current=reference()
        for action in ('hamilton_dropoff','hamilton_retrieve'):
            trial=record['completed'][action]
            events=trial['events'];plan=events[0]['event']['plan']
            if plan['actions']!=[action] or plan['handling_evidence']!=current:
                raise TransferError('Historical Hamilton handling geometry differs from the current setup.')
            approved=[x['event']['label'] for x in events if x['event']['event']=='station_handling_inspection_accepted']
            expected=[s['review_label'] for s in plan['steps'] if s['kind']=='hamilton_inspect']
            result=events[-1]['event'].get('result',{})
            if len(expected)!=2 or approved!=expected or result.get('ok') is not True or result.get('done')!=[s['label'] for s in plan['steps']]:
                raise TransferError('Historical Hamilton handling lacks completed steps or operator inspections.')
        return dict(completed_supervised=True,evidence=str(path.relative_to(ROOT)),
            actions=list(record['completed']),later_failures=len(record.get('later_failures',[])),
            automatic_acceptance=False,
            message='Completed supervised Hamilton drop-off and pickup/return are recorded, with both operator inspections. Later failures are retained; unattended acceptance is separate.')
    except Exception as error:
        return dict(completed_supervised=False,automatic_acceptance=False,message=str(error))


def reference():
    config=endpoint()
    seated=dict(config['pose'])
    lifted={**seated,'Z':round(seated['Z']+5,2)}
    if config.get('schema')=='cephla.hamilton-endpoint.v2':
        from hamilton_accepted_route import evidence,HASHES
        evidence()
        return seated,lifted,{
            'hamilton_endpoint':hashlib.sha256(ENDPOINT.read_bytes()).hexdigest(),
            'accepted_travel':dict(HASHES),
            'local_handling':'supervised_trial_open5_close3.7_lift5_speed5_v1',
        }
    raw=TRIAL.read_bytes()
    trial=json.loads(raw)
    if trial.get('status')!='completed' or trial.get('empty_gripper') is not True or trial.get('speed')!=137:
        raise TransferError('Hamilton empty travel reference needs review.')
    near(trial['final']['robot']['pose_mm'],seated,.02)
    phases=trial.get('phases',[])
    if [p.get('action') for p in phases]!=['move_home','move_hamilton'] or any(p.get('status')!='completed' for p in phases):
        raise TransferError('Hamilton round-trip evidence is incomplete.')
    return seated,lifted,{
        'hamilton_endpoint':hashlib.sha256(ENDPOINT.read_bytes()).hexdigest(),
        'empty_travel_trial':hashlib.sha256(raw).hexdigest(),
        'local_handling':'supervised_trial_open5_close3.7_lift5_speed5_v1',
    }


def check_lift(start,target,joints,cfg):
    """A narrow local exception, not a disabled global workspace."""
    seated,lifted,_=reference()
    near(start,seated,.05)
    if target!=lifted:
        raise TransferError('Hamilton lift must be exactly 5 mm at the taught XY/wrist.')
    if not 0<=joints['J1']<=400:
        raise TransferError('Hamilton lift starts outside vertical joint travel.')
    q=check_path(start,target,joints,cfg,None)
    q['J1']=joints['J1']+target['Z']-start['Z']
    if not 0<=q['J1']<=400 or abs(q['J3'])>180:
        raise TransferError('Hamilton lift exceeds joint travel.')
    return q
