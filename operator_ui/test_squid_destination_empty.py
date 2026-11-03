"""Explicit supervised empty-arm Home return and new Squid destination trial."""
import argparse
import hashlib
import json
import time
import urllib.request
from uuid import uuid4

from projected_pickup import ROOT
from prepare_squid_destination import validate
from scope_step_trial import near

SOURCE=ROOT/'operator_ui/reports/squid_48well_approach/destination_20261101T071149Z.json'
SHA='a633cb7a78bdc2fe21c8b4feb4d82ff9462fec667cbab16492bc876ed0ef983b'


def api(path,body=None):
    request=urllib.request.Request('http://127.0.0.1:5002/'+path,
        data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=130) as response:
        result=json.load(response)
    if result.get('ok') is False:
        raise RuntimeError(str(result))
    return result


def forward_legs(forward, transit_speed, approach_only=False):
    """Slow only the holder descent, never the overhead approach."""
    return [('new_squid_route', point,
             5 if not approach_only and i == len(forward)-2 else transit_speed)
            for i, point in enumerate(forward[1:])]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--transit-speed',type=int,choices=(40,137),default=40)
    parser.add_argument('--return-only',action='store_true')
    parser.add_argument('--loaded-forward-only',action='store_true')
    parser.add_argument('--approach-only',action='store_true',
                        help='Loaded transfer stops above Squid; no holder descent or release')
    parser.add_argument('--confirmed-empty-stale-reading',action='store_true',
                        help='Explicit operator approval to override a stale held-object startup reading')
    args=parser.parse_args()
    if args.approach_only and not args.loaded_forward_only:
        raise RuntimeError('Approach-only requires loaded-forward-only')
    if args.loaded_forward_only and (args.return_only or args.confirmed_empty_stale_reading):
        raise RuntimeError('Loaded transfer forbids return-only and startup override')
    raw=SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SHA:raise RuntimeError('Candidate changed')
    candidate=json.loads(raw);cfg=api('robot_params');state=api('state');robot=state['robot']
    if not robot.get('connected') or robot.get('errors') or state['sequence']['active']:
        raise RuntimeError('Connected, healthy, idle controller required')
    start={k:robot['pose_mm'][k] for k in ('X','Y','Z','Rz')}
    forward=candidate['routes']['forward']
    if args.approach_only:
        forward=forward[:-1]
    near(start,forward[0] if args.loaded_forward_only else forward[-1],.15)
    back=[start] if args.loaded_forward_only else [start,dict(start,Z=forward[-2]['Z']),*reversed(forward[:-1])]
    if args.loaded_forward_only:
        if not robot.get('enabled') or robot['control_mode']['mode']!='auto' or robot['program_state']['state']!='running':
            raise RuntimeError('Loaded arm must already be ready; never start or enable it')
        if abs(robot['external_axes']['E1']-3.9) > .15+1e-9:
            raise RuntimeError('Accepted loaded grip feedback required')
    envelope={k:[state['envelope'][k]['min'],state['envelope'][k]['max']] for k in ('X','Y','Z')}
    if cfg!=candidate['cfg'] or envelope!=candidate['envelope'] or not state['envelope']['enabled']:
        raise RuntimeError('Candidate settings changed')
    checked=dict(final_joints=robot['joints']) if args.loaded_forward_only else validate(back,robot['joints'],cfg,envelope)
    validate(forward,checked['final_joints'],cfg,envelope)
    print(json.dumps(dict(home_return=back,new_forward=forward,execute=args.execute)),flush=True)
    if not args.execute:return
    output=SOURCE.with_name(('loaded_trial_' if args.loaded_forward_only else 'empty_trial_')+uuid4().hex+'.json')
    record=dict(status='preparing',at=time.time(),candidate_sha256=SHA,source_state=state,
        authorization='Operator requested loaded new-route transfer after full calibration; stop seated with claws closed awaiting human confirmation.' if args.loaded_forward_only else 'Operator requested empty return Home; on site, clear route and emergency-stop access.',
        home_return=back,forward=forward,steps=[],preparation=[],release_executed=False,pickup_executed=False,transit_speed=args.transit_speed,
        empty_gripper_startup_override_authorized=args.confirmed_empty_stale_reading)
    def save():output.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
    if args.approach_only:
        record.update(approach_only=True, holder_descent_authorized=False,
                      authorization='Operator requested loaded transfer to above Squid only, stopping before descent and release for teaching.')
    save()
    try:
        # Never reset faults. Stale-reading override requires explicit operator approval.
        if not args.loaded_forward_only and robot['control_mode']['mode']!='auto':
            record['preparation'].append(api('mode',dict(mode='auto')));save()
        robot=api('state')['robot']
        if robot['errors']:raise RuntimeError('Controller fault; no preparation')
        if not args.loaded_forward_only and not robot['enabled']:
            record['preparation'].append(api('enable',dict(confirm=True)));save()
        if not args.loaded_forward_only and api('state')['robot']['program_state']['state']!='running':
            record['preparation'].append(api('program',dict(action='start',force=args.confirmed_empty_stale_reading)));save()
        robot=api('state')['robot'];near(robot['pose_mm'],start,.1)
        validate(forward if args.loaded_forward_only else back,robot['joints'],cfg,envelope)
        e1=robot['external_axes']['E1'];previous=start
        legs=[('return_home',p,5 if i<2 else args.transit_speed) for i,p in enumerate(back[1:])]
        if not args.return_only:
            legs += forward_legs(forward, args.transit_speed, args.approach_only)
        for phase,point,speed in legs:
            state=api('state');robot=state['robot']
            if not robot.get('connected') or robot.get('errors') or not robot.get('enabled') or state['sequence']['active'] or robot['control_mode']['mode']!='auto' or robot['program_state']['state']!='running':
                raise RuntimeError('Controller not ready; no further movement')
            near(robot['pose_mm'],previous,.1)
            if abs(robot['external_axes']['E1']-e1)>.1:raise RuntimeError('Claw feedback changed')
            current_env={k:[state['envelope'][k]['min'],state['envelope'][k]['max']] for k in ('X','Y','Z')}
            if not state['envelope']['enabled'] or current_env!=envelope or api('robot_params')!=cfg or hashlib.sha256(SOURCE.read_bytes()).hexdigest()!=SHA:
                raise RuntimeError('Reviewed settings changed')
            step=dict(phase=phase,target=point,speed=speed,before=robot,status='requested')
            record['steps'].append(step);save()
            result=api('move',dict(x=point['X'],y=point['Y'],z=point['Z'],rz=point['Rz'],speed=speed,interpolation='linear'))
            step['response']=result;save()
            if result.get('recovered'):raise RuntimeError('Recovered response; inspect before continuing')
            near(result['pose_after'],point,.1)
            after=api('state')['robot']
            if after.get('errors') or abs(after['external_axes']['E1']-e1)>.1:
                raise RuntimeError('Fault or changed claw feedback after move')
            step.update(status='arrived',after=after);save();previous=point
            print(json.dumps(dict(phase=phase,arrived=after['pose_mm'])),flush=True)
        record.update(status='loaded_seated_awaiting_human_release_confirmation' if args.loaded_forward_only else ('empty_return_home_completed' if args.return_only else 'empty_route_completed_pending_operator_inspection'),final_robot=api('state')['robot'])
        if args.approach_only:
            record['status']='loaded_above_squid_awaiting_operator_teaching'
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        try:record['stop_response']=api('program',dict(action='stop'))
        except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        record['finished_at']=time.time();save()
        print(json.dumps(dict(record=str(output),status=record['status'])),flush=True)


if __name__=='__main__':main()
