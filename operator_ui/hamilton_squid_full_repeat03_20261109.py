"""One authorized Hamilton/Squid release/retrieval round trip; no retries."""
import argparse
import json
import sys
import time
import hamilton_reteach_trial as hamilton
import dropoff_approach_20261103 as approach
import release_empty_home_20261103 as release
import pickup_squid_home_20261103 as pickup
from proof_lift_plate import api,near,write
from squid_handling_route import CURRENT_SOURCE,CURRENT_SHA,load_route
from prepare_squid_destination import validate

OUT=approach.FOLDER/'hamilton_squid_full_repeat03_20261109'
AUTH=('Operator requested full Hamilton -> Home -> Squid drop-off -> empty Home '
      '-> Squid pickup -> loaded Home -> Hamilton sequence. Same previously '
      'accepted geometry, clear routes and supervised E-stop; Hamilton door '
      'open and holder empty/unchanged. No final Hamilton release. Stop on '
      'any fault or uncertain completion; no automatic retries or startup.')
TRIAL='squid_full_repeat03_20261109'

def hamilton_idle():
    h=api('researcher/api/lacry/hamilton/status')
    if not h.get('connected') or h.get('serial')!='PRPGJ2494' or h.get('global_state')!='Idle' or not h.get('parked') or h.get('pending_errors'):
        raise RuntimeError('Hamilton must remain idle, parked and healthy')
    return {k:h.get(k) for k in ('serial','global_state','parked','pending_errors')}

def travel_hamilton(direction, forward_trial_id=None):
    hamilton_idle()
    before=api('state')['robot']['external_axes']['E1']
    body=dict(ready=True,candidate_sha256=hamilton.SHA,direction=direction,trial_id=TRIAL)
    if forward_trial_id is not None:body['forward_trial_id']=forward_trial_id
    result=api('developer/api/hamilton-reteach/start',body)
    write(OUT/(direction+'_dispatch.json'),result)
    if not result.get('ok'):raise RuntimeError(str(result))
    deadline=time.monotonic()+120
    while True:
        q=api('seq');r=api('state')['robot']
        if q.get('name')!='hamilton_reteach' or not r.get('ok') or r.get('errors') or abs(r['external_axes']['E1']-before)>.1:
            raise RuntimeError('Hamilton travel feedback uncertain')
        if not q['active']:
            if not (q.get('result') or {}).get('ok'):raise RuntimeError('Hamilton travel failed: '+str(q.get('result')))
            break
        if time.monotonic()>deadline:raise RuntimeError('Hamilton travel timed out')
        time.sleep(.3)
    p=hamilton.reference()['routes'][direction]
    near(r['pose_mm'],p[-1],.1)
    return dict(sequence=q,robot=r,receipt=str(hamilton.output_path(direction=='reverse',TRIAL)))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    assert not (OUT/'run.json').exists(),'Already attempted'
    s=api('state')
    if not s['robot'].get('connected'):
        assert not s['sequence']['active']
        assert api('connect',{'ip':'192.168.201.220'})['ok']
        s=api('state')
    r=s['robot']
    assert r['ok'] and not r['errors'] and r['enabled'] and r['control_mode']['mode']=='auto' and r['program_state']['state']=='running' and not s['sequence']['active']
    assert abs(r['external_axes']['E1']-3.9)<.15
    assert api('researcher/api/status')['hand_guiding']['state']=='off'
    assert not api('researcher/api/lacry/state')['running']['active']
    hp=hamilton.reference();cfg=api('robot_params')
    env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
    assert s['envelope']['enabled']
    q=hamilton.check_route(r['pose_mm'],hp['routes']['reverse'][1:],r['joints'],cfg,env)
    hamilton.check_route(hp['routes']['forward'][0],hp['routes']['forward'][1:],q,cfg,env)
    sp=load_route(CURRENT_SOURCE,CURRENT_SHA)
    validate(sp['routes']['from_capture'],q,cfg,sp['envelope'])
    assert not hamilton.output_path(True,TRIAL).exists() and not hamilton.output_path(False,TRIAL).exists()
    hs=hamilton_idle()
    print(json.dumps(dict(validated=True,execute=args.execute,authorization=AUTH)),flush=True)
    if not args.execute:sys.exit(0)
    OUT.mkdir(exist_ok=False)
    record=dict(status='running',at=time.time(),authorization=AUTH,initial_robot=r,hamilton=hs,phases=[],automatic_retries=False)
    def phase(name,**extra):
        record['phase']=name;record['phases'].append(dict(name=name,at=time.time(),**extra));write(OUT/'run.json',record)
        print(json.dumps(dict(phase=name)),flush=True)
    try:
        phase('hamilton_to_home')
        result=travel_hamilton('reverse');write(OUT/'initial_home.json',result)
        delivery=OUT/'dropoff';delivery.mkdir()
        phase('squid_dropoff_approach')
        approach.main(delivery,route_source=CURRENT_SOURCE,route_sha=CURRENT_SHA)
        phase('squid_release_and_empty_home')
        release.main(delivery,AUTH,route_source=CURRENT_SOURCE,route_sha=CURRENT_SHA)
        retrieval=OUT/'pickup';retrieval.mkdir()
        phase('squid_pickup_and_loaded_home')
        pickup.main(retrieval,AUTH,route_source=CURRENT_SOURCE,route_sha=CURRENT_SHA)
        phase('loaded_home_to_hamilton')
        result=travel_hamilton('forward');write(OUT/'final_hamilton.json',result)
        record.update(status='completed_pending_operator_assessment',final_robot=result['robot'])
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        try:record['stop_response']=api('program',dict(action='stop'))
        except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        record['finished_at']=time.time();write(OUT/'run.json',record)
        print(json.dumps(dict(status=record['status'],report=str(OUT/'run.json'))),flush=True)
