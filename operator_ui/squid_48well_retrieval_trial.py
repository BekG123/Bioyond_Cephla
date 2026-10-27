"""One authorized empty retreat/Home/retrieval/Home on the accepted corridor."""
import json,time,math
from projected_pickup import ROOT
from autonomy import TransferError
from scope_step_trial import near,preflight
from scope_compact137 import HoldingService
from squid_48well_endpoint_trial import check_route
from squid_48well_higher_route import reference,SHA
from trajectory_queue import LuaTrajectory,travel_program_blocker
from pick_and_hold.Grip.fast_position_plan import plan_closure
from squid_48well_handling import settings as handling_settings

FOLDER=ROOT/'operator_ui/reports/projected_alignment'
OUTPUT=FOLDER/'squid_48well_full7_cycle_20261027_trial.json'
GRIP_SETTLE_SECONDS=5.0

class GripSettlingIncomplete(TransferError):
    """Completed gripper command, healthy arm; end sequence without restarting Lua."""

def phases():
    plan,path=reference();lifted={**path[-1],'Z':275.0}
    return [('dropoff_transit','raised_transit',path[0],path[1:-1],137),
            ('dropoff_descent','raised_descent',path[-2],path[-1:],5),
            ('empty_lift','raised_departure',path[-1],[lifted],5),
            ('empty_return','raised_return',lifted,list(reversed(path[:-1])),137),
            ('retrieval_transit','raised_transit',path[0],path[1:-1],137),
            ('retrieval_descent','raised_descent',path[-2],path[-1:],5),
            ('loaded_lift','raised_departure',path[-1],[lifted],5),
            ('loaded_return','raised_return',lifted,list(reversed(path[:-1])),137)]

def review(service,cfg,stop_before_release=False):
    if OUTPUT.exists():raise TransferError('Retrieval already attempted; inspect before another trial.')
    accepted=json.loads((FOLDER/'squid_obstruction_removed_20261027_summary.json').read_bytes())
    if not (accepted['plate_after_release_visually_confirmed'] and accepted['release_executed']):
        raise TransferError('Operator-confirmed supported release required.')
    recovery=json.loads((FOLDER/'squid_caught_up5_20261027_trial.json').read_bytes())
    if recovery['status']!='up5_completed_contact_inspection_pending' or not recovery.get('operator_confirmed_free'):
        raise TransferError('Successful recovery and operator-confirmed free claw required.')
    state=preflight(service);plan,path=reference();near(state['pose_mm'],phases()[0][2],.05)
    e1=state['external_axes']['E1']
    if not math.isfinite(e1) or not 3.85<=e1<=3.95:raise TransferError('Expected accepted 48-well grip at Home.')
    blocker=travel_program_blocker(LuaTrajectory(service).capability(),137)
    if blocker:raise TransferError(blocker)
    q=state['joints']
    selected=phases()[:2] if stop_before_release else phases()
    for _,phase,start,points,_ in selected:
        q=check_route(start,points,q,cfg,service.envelope,phase)
    return dict(candidate_sha256=SHA,phases=selected,e1=e1,joints=state['joints'],envelope=plan['envelope'],handling=handling_settings(),stop_before_release=stop_before_release)

def execute(run,service,cfg,approved):
    fresh=review(service,cfg,approved.get('stop_before_release',False))
    if fresh['phases']!=approved['phases'] or fresh['handling']!=approved['handling'] or abs(fresh['e1']-approved['e1'])>.05:
        raise TransferError('Reviewed trial changed.')
    if any(abs(fresh['joints'][k]-approved['joints'][k])>.5 for k in fresh['joints']):
        raise TransferError('Starting joints changed.')
    record=dict(status='started',started_at=time.time(),plan=fresh,phases=[],grip_steps=[],
        authorization='Operator requested whole sequence after returning plate to calibration holder, with higher Squid travel and 7 mm release/approach. From loaded Home: drop off, empty Home, retrieve, loaded Home. Existing clearance/E-stop supervision retained.',
        program_restart=False,plate_retention_operator_confirmed=False)
    with OUTPUT.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    def save():OUTPUT.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
    held=fresh['e1']
    opening=fresh['handling']['approach_opening_e1_mm']
    grip=fresh['handling']['grip_e1_mm']
    try:
        for name,phase,start,points,speed in fresh['phases']:
            if run.stopped():raise TransferError('Stopped before '+name)
            if name=='empty_lift':
                preflight(HoldingService(service,held,fresh['envelope']));near(service.pose_mm(),start,.05)
                record['release_requested']=dict(e1=fresh['handling']['release_opening_e1_mm'],speed=5);save()
                response=service.move_gripper(fresh['handling']['release_opening_e1_mm'],5)
                record['release_response']=response;save()
                if not response.get('ok') or response.get('recovered') or response.get('gripper_warning'):
                    raise TransferError('Release uncertain; no retreat.')
                deadline=time.monotonic()+3;stable=0
                while stable<3:
                    state=preflight(service);near(state['pose_mm'],start,.05);held=state['external_axes']['E1']
                    stable=stable+1 if math.isfinite(held) and abs(held-opening)<=.03 else 0
                    if time.monotonic()>deadline:raise TransferError('Release did not settle; no retreat.')
                    time.sleep(.1)
                record['release_settled_mm']=held;save()
            if name=='retrieval_transit':
                near(service.pose_mm(),start,.05);preflight(HoldingService(service,held,fresh['envelope']))
                record['open_at_home_requested']=dict(e1=opening,speed=5);save()
                response=service.move_gripper(opening,5);record['open_at_home_response']=response;save()
                if not response.get('ok') or response.get('recovered') or response.get('gripper_warning'):
                    raise TransferError('Opening response uncertain; no retry.')
                deadline=time.monotonic()+3;stable=0
                while stable<3:
                    state=preflight(service);near(state['pose_mm'],start,.05);held=state['external_axes']['E1']
                    stable=stable+1 if math.isfinite(held) and abs(held-opening)<=.03 else 0
                    if time.monotonic()>deadline:raise TransferError('Opening at Home did not settle.')
                    time.sleep(.1)
                record['open_at_home_settled_mm']=held;save()
            if name=='loaded_lift':
                near(service.pose_mm(),start,.05)
                commands=[s for s in plan_closure(opening)['commands'] if s['target_e1_mm']>=grip]
                if not commands or commands[-1]['target_e1_mm']!=grip:raise TransferError('Unexpected grip plan.')
                for command in commands:
                    if run.stopped():raise TransferError('Stopped before grip increment')
                    preflight(HoldingService(service,held,fresh['envelope']))
                    near(service.pose_mm(),start,.05)
                    step=dict(target=command['target_e1_mm'],speed=5);record['grip_steps'].append(step);save()
                    response=service.move_gripper(step['target'],5);step['response']=response;save()
                    if not response.get('ok') or response.get('recovered') or response.get('gripper_warning'):
                        raise TransferError('Grip increment uncertain; no retry.')
                    deadline=time.monotonic()+GRIP_SETTLE_SECONDS;stable=0
                    tolerance=.05 if step['target']==grip else .03
                    step.update(settling_tolerance_mm=tolerance,settling_samples=[])
                    while stable<3:
                        if run.stopped():raise TransferError('Stopped during grip check.')
                        state=preflight(service);near(state['pose_mm'],start,.05)
                        held=state['external_axes']['E1']
                        step['settling_samples'].append(dict(at=time.time(),e1_mm=held));save()
                        stable=stable+1 if math.isfinite(held) and abs(held-step['target'])<=tolerance else 0
                        if time.monotonic()>deadline and stable<3:
                            raise GripSettlingIncomplete('Grip command completed but feedback did not settle; no lift. Lua remains idle to avoid resetting the jaws.')
                        time.sleep(.1)
                    step['settled_e1_mm']=held;save()
            holding=HoldingService(service,held,fresh['envelope'])
            state=preflight(holding);near(state['pose_mm'],start,.05)
            item=dict(name=name,speed=speed,samples=[]);record['phases'].append(item);save()
            run.say(name.replace('_',' ')+f' at speed {speed}.')
            def progress(stage,done,total):
                item['samples'].append(dict(at=time.time(),stage=stage,done=done,total=total,robot=service.status()));save()
            result=LuaTrajectory(holding).execute(run,start,state['joints'],points,cfg,speed,progress,
                reviewed=True,scope_trial=True,scope_speed137=True,scope_phase=phase)
            if not result.get('ok'):raise TransferError('Unconfirmed '+name)
            preflight(holding);near(service.pose_mm(),points[-1],.1)
            item.update(result=result,status='completed');save()
        if fresh['stop_before_release']:
            record.update(status='seated_endpoint_awaiting_support_inspection',final_robot=service.status(),release_executed=False)
            return dict(ok=True,record=str(OUTPUT),pose=service.pose_mm(),seating_inspection_required=True,release_executed=False)
        record.update(status='completed_awaiting_retention_confirmation',final_robot=service.status())
        return dict(ok=True,record=str(OUTPUT),pose=service.pose_mm(),retention_inspection_required=True)
    except GripSettlingIncomplete as exc:
        record.update(status='grip_unverified_no_lift_lua_left_running',error=str(exc),final_robot=service.status())
        raise
    except Exception as exc:
        record.update(status='stopped_or_failed',error=str(exc))
        record['stop_response']=service.program('stop');raise
    finally:
        record['finished_at']=time.time();save()
