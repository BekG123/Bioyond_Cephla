"""Preview or run HOME pickup -> slot2/3, stopping held before release.

--execute confirms empty/free jaws, plate flat in HOME, selected slot empty,
any previous obstruction removed, and the empty return and loaded route clear,
arm released, hands clear and E-stop supervised. May prepare disabled/paused
Auto with EMPTY jaws. No fault reset, calibration, release or automatic retry.
The empty connector turns/crosses at current height then lowers to HOME.
Start at HOME clearance or the bounded near-HOME area shown in the preview.
"""
import argparse
import json
import time
from uuid import uuid4
from run_cellvis24_scanner_hamilton import api,reconnect,dispatch
from hotel_slot1_delivery import geometry as home_geometry,check_geometry
from hotel_slot2_trial import geometry as slot_geometry
from plan_hotel_slot2_from_slot1 import CAPTURE
from scope_step_trial import near
from run_record_io import write_run_record

def parse_args(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--slot',type=int,choices=[2,3],required=True)
    p.add_argument('--execute',action='store_true',help='Confirm setup described above and execute; default is offline preview.')
    return p.parse_args(argv)

def connector(robot,g):
    p=robot['pose_mm']
    # No generic recovery from inside the rack or arbitrary positions.
    if not (290<=p['X']<=335 and -80<=p['Y']<=35 and 105<=p['Z']<=300 and 0<=p['Rz']<=100):
        raise RuntimeError('Start outside the rack, at HOME clearance or the bounded near-HOME area with its connector confirmed clear; no automatic recovery.')
    points=[dict(g['home'],Z=p['Z']),g['home']]
    v=check_geometry(p,points,robot['joints'],g['cfg'],g['envelope'])
    return points,v

def main(argv=None):
    args=parse_args(argv);g=home_geometry();target=slot_geometry(args.slot)
    if not args.execute:
        print(json.dumps(dict(motion_started=False,slot=args.slot,endpoint=target['endpoint'],
            phases=['prepare empty Auto if needed','checked near-HOME connector at5','accepted HOME pickup','5mm lift at5','outside travel137','horizontal entry20','stop held; no release'],
            start_area=dict(X=[290,335],Y=[-80,35],Z=[105,300],Rz=[0,100]),route=target['route'],execute_requirements=__doc__),indent=2))
        return
    from draggo import DragGoRPC
    reconnect();s=api('state');n=DragGoRPC('192.168.201.220').info();r=s['robot']
    if s['sequence']['active'] or r.get('errors') or any(n.get(k,True) for k in ('moving','error','emergency','drag','manual')):
        raise RuntimeError('Stationary fault-free Auto required; no automatic fault reset.')
    if not any(abs(n['external_axes']['E1']-x)<.15 for x in (0,7,28)):
        raise RuntimeError('Expected confirmed empty jaws near0,7 or28mm; do not restart with a held plate.')
    points,v=connector(r,g)
    folder=CAPTURE.parent/'cli_trials';folder.mkdir(exist_ok=True)
    path=folder/(uuid4().hex+'.json')
    record=dict(at=time.time(),status='starting',slot=args.slot,before=s,native=n,connector=points,
        connector_validation=v,candidate=target,steps=[],authorization='Operator --execute setup confirmation',automatic_retries=False)
    def save():write_run_record(path,record)
    def log(phase,result):record['steps'].append(dict(phase=phase,result=result));save()
    save()
    try:
        if not r['enabled']:log('enable_empty',api('enable',{'confirm':True}))
        if r['program_state']['state']!='running':log('start_empty',api('program',{'action':'start'}));time.sleep(.5)
        current=api('state')['robot'];near(current['pose_mm'],r['pose_mm'],.05)
        n=DragGoRPC('192.168.201.220').info()
        if abs(n['external_axes']['E1'])>.15:
            log('prepare_empty_jaws',api('gripper',dict(action='move',e1=0,speed=5)))
        for p in points:
            near_now=api('state')['robot'];n=DragGoRPC('192.168.201.220').info()
            if near_now.get('errors') or any(n[k] for k in ('moving','error','emergency','drag')) or abs(n['external_axes']['E1'])>.15:
                raise RuntimeError('State changed before empty connector.')
            result=api('move',dict(x=p['X'],y=p['Y'],z=p['Z'],rz=p['Rz'],speed=5,interpolation='linear'));log('empty_HOME_connector',result)
            if result.get('recovered'):raise RuntimeError('Uncertain connector; no retry.')
            near(api('state')['robot']['pose_mm'],p,.05)
        plan=api('developer/api/hotel-home-teaching-pickup/preview',{})['plan']
        if plan['geometry']!=g:raise RuntimeError('Loaded pickup differs from reviewed code.')
        log('pickup',dispatch('developer/api/hotel-home-teaching-pickup/start',dict(plan=plan,plate_in_home=True,empty_gripper=True,pickup_route_clear=True,estop_supervised=True),'hotel_home_teaching_pickup',120))
        endpoint=f'developer/api/hotel-slot{args.slot}-taught'
        plan=api(endpoint+'/preview',{})['plan']
        if plan['geometry']!=target:raise RuntimeError('Loaded slot route differs from reviewed candidate.')
        body=dict(plan=plan,plate_secure=True,loaded_route_clear=True,estop_supervised=True)
        body[f'slot{args.slot}_empty']=True
        result=dispatch(endpoint+'/start',body,f'hotel_slot{args.slot}_taught',180)
        log('slot_approach',result);record.update(status='arrived_held_support_inspection_pending',result=result)
    except BaseException as e:
        record.update(status='stopped_or_uncertain',error=str(e))
        try:record['stop']=api('program',{'action':'stop'})
        except Exception as x:record['stop_error']=str(x)
        raise
    finally:
        record['finished_at']=time.time();save();print(json.dumps(dict(status=record['status'],record=str(path))),flush=True)
    return dict(record=record,record_path=str(path))

if __name__=='__main__':main()
