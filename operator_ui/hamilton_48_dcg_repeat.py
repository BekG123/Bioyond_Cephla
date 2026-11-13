"""Repeat the accepted transfer at the original recorded site 3 and 4 positions.

Default is offline. --check reads hardware only. --execute-confirmed runs the
specified count under one operator approval; faults or failed checks stop it.
"""
import argparse
import asyncio
import copy
import json
from pathlib import Path
from uuid import uuid4
import numpy as np
from hamilton_48_dcg_plan import verify_plan,assert_bounds,STAGES
from hamilton_48_dcg_pipeline import (HamiltonPrep,rest_ready,run_stage,fresh_source_check,
    save_owned,compile_action,stage_actions)

EMPTY_RETRY='dcg_coordinated_retry_12292fbcf5ce4edea5ce5e9737b37b24'
STOPPED_BATCH='dcg48_repeat_f358eb6148794cbb9f6f0957f386193a'

def coordinated_evidence(folder):
    result=json.loads((folder/EMPTY_RETRY/'result.json').read_text())
    events=[json.loads(line) for line in (folder/(EMPTY_RETRY+'.jsonl')).read_text().splitlines()]
    outcome=next((e['data'] for e in reversed(events) if e['kind']=='outcome'),{})
    if (result.get('request_id')!=EMPTY_RETRY or result.get('instrument_serial')!='PRPGJ2494'
        or result.get('status')!='completed' or result.get('physical_plate_present') is not False
        or outcome.get('status')!='completed' or outcome.get('parked') is not True
        or outcome.get('empty_test_passed') is not True):raise RuntimeError('Completed coordinated empty test required')
    return result

def verify_empty_recovery(h,owner):
    from inspect_hamilton_48_repeat import snapshot
    coordinated_evidence(h.folder);check_park(h)
    if (owner.get('request_id')!=STOPPED_BATCH or owner.get('status')!='failed_or_uncertain'
        or owner.get('latest_diagnostic_request_id')!=EMPTY_RETRY
        or owner.get('latest_diagnostic_result',{}).get('status')!='completed'):
        raise RuntimeError('Only the specifically recovered empty diagnostic may resolve this owner')
    state=asyncio.run(snapshot())
    if (not state['PrepIsParked']['value'] or state['PrepGetPlateHeld']['value']
        or state['PrepGetTipDefinitionHeld']['value'].get('is_tool')):raise RuntimeError('Recovery is not currently parked and empty')
    return state

def leg_plan(base,source_site):
    if source_site not in (3,4):raise ValueError('Only the accepted sites 3 and 4')
    p=copy.deepcopy(base)
    positions={3:base['destination_top_mm'],4:base['source_top_mm']}
    p['source_site']=source_site;p['destination_site']=7-source_site
    p['source_top_mm']=list(positions[source_site])
    p['destination_top_mm']=list(positions[7-source_site])
    p['repeat_position_policy']='Preserve original measured site4 offset and successful site3 placement'
    assert_bounds(p,p['native_bounds'])
    return p

def accepted_reference(path):
    base=json.loads(path.read_text());verify_plan(base)
    accepted=json.loads(path.with_name('accepted_trial.json').read_text())
    completed=json.loads(path.with_name('completed_trial.json').read_text())
    if (accepted.get('plan_sha256')!=base['plan_sha256'] or
        completed.get('plan_sha256')!=base['plan_sha256'] or
        accepted.get('request_id')!=completed.get('request_id') or
        completed.get('status')!='completed' or completed['checkpoint']['plate_held'] or
        completed['checkpoint']['tool']['value']['is_tool'] or
        not all(accepted['controller_completion'].get(k) is True for k in
                ('plate_released','tool_returned','park_verified'))):
        raise RuntimeError('Completed accepted physical transfer evidence is required')
    return base

def check_park(h):
    s=rest_ready(h,initial=True)
    if not s.get('parked'):raise RuntimeError('Hamilton must be parked between transfers')

def measured_pickup_plan(base,site,measurement):
    p=leg_plan(base,site)
    xy=np.asarray(measurement['native_center_mm'][:2],float)
    if not np.isfinite(xy).all() or np.linalg.norm(xy-np.asarray(p['source_top_mm'][:2]))>1:
        raise RuntimeError('Repeat pickup differs by over 1 mm from the accepted station; review required')
    p['source_top_mm'][:2]=xy.tolist()
    p['pickup_measurement']=measurement
    assert_bounds(p,p['native_bounds'])
    return p

def resume_plan(base,ticket,rounds,clearance):
    if (ticket.get('action')!='falcon48_staged_dcg' or ticket.get('plan_sha256')!=base['plan_sha256']
        or ticket.get('status')!='awaiting_site4_seating_inspection' or ticket.get('rounds_requested')!=rounds
        or ticket.get('cycle')!=1 or ticket.get('source_site')!=3 or ticket.get('next_stage')!='release_return'
        or ticket.get('transfers_completed')!=0 or ticket.get('rounds_completed')!=0):
        raise RuntimeError('Only the pending first site-4 seating inspection can resume')
    p=measured_pickup_plan(base,3,ticket['pending_plan']['pickup_measurement'])
    if any(p[k]!=ticket['pending_plan'][k] for k in ('source_top_mm','destination_top_mm','profile','grip_z_mm')):
        raise RuntimeError('Pending plan differs from accepted geometry/measurement')
    if clearance not in (4,6):raise ValueError('Reviewed release clearance must be 4 or 6 mm')
    p['release_clearance_y_mm']=clearance;assert_bounds(p,p['native_bounds'])
    return p

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',type=Path);parser.add_argument('--rounds',type=int,default=5)
    parser.add_argument('--inspect-first-seat',action='store_true',help='Pause before releasing at site 4 in round 1 after a prior jam')
    parser.add_argument('--resume-first-seat-confirmed',action='store_true')
    parser.add_argument('--release-clearance-mm',type=float,choices=(4,6),default=4)
    parser.add_argument('--separate-release',action='store_true',help='Open slowly, lift with jaws open, then release firmware state at clearance')
    parser.add_argument('--coordinated-release',action='store_true',help='Use the corrected full-XYZ opening and retreat, with live coordinate checks')
    parser.add_argument('--resolve-empty-retry',action='store_true',help='Archive only the specifically verified parked empty recovery before starting a new run')
    parser.add_argument('--release-outward-mm',type=float,choices=(6,10),default=6,help='Measured travel of each jaw during independent release')
    parser.add_argument('--temporal-camera',action='store_true',help='Use five-frame pixel median per independent camera estimate; geometry limits unchanged')
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--check',action='store_true');mode.add_argument('--execute-confirmed',action='store_true')
    args=parser.parse_args()
    if not 1<=args.rounds<=5:raise ValueError('Reviewed batch supports one to five round trips')
    base=accepted_reference(args.plan)
    original_base=copy.deepcopy(base)
    base['release_clearance_y_mm']=args.release_clearance_mm
    if args.temporal_camera:base['temporal_camera_frames']=5
    if args.coordinated_release:
        if args.separate_release or args.resume_first_seat_confirmed:raise ValueError('Coordinated release requires a fresh batch')
        coordinated_evidence(Path(__file__).resolve().parent/'reports/hamilton_api')
        base['release_mode']='coordinated_open_retreat';base['release_outward_mm']=10
        base['empty_validation_request_id']=EMPTY_RETRY
    if args.separate_release:
        if args.resume_first_seat_confirmed:raise RuntimeError('Separate release starts a fresh reviewed batch')
        evidence=json.loads((Path(__file__).resolve().parent/'reports/hamilton_api/dcg48_repeat_e6281769973846d5bb2a090cdd7767a1_resolved_after_supported_release.json').read_text())
        if evidence.get('recovery_completed') is not True:raise RuntimeError('Successful release recovery evidence required')
        base['release_mode']='separate_open_retreat'
        base['release_outward_mm']=args.release_outward_mm
    for site in (3,4):
        for stage in STAGES:
            for action in stage_actions(leg_plan(base,site),stage,stage=='pickup_lift'):
                compile_action(leg_plan(base,site),action).build_parameters().build()
    if not (args.check or args.execute_confirmed):
        print(json.dumps(dict(rounds=args.rounds,transfers=2*args.rounds,motion_sent=False,
            route=[3,4,3],site3=base['destination_top_mm'],site4=base['source_top_mm']),indent=2));return
    h=HamiltonPrep();marker=h.folder/'active.json';resumed=None
    if args.resume_first_seat_confirmed:
        rest_ready(h);resumed=json.loads(marker.read_text())
        pending=resume_plan(original_base,resumed,args.rounds,args.release_clearance_mm)
    else:
        check_park(h)
        if marker.exists():
            if not args.resolve_empty_retry:raise RuntimeError('Another operation or unresolved outcome owns Hamilton')
            verify_empty_recovery(h,json.loads(marker.read_text()))
    if args.check:
        if resumed is not None:
            asyncio.run(run_stage(h,pending,'release_return',resumed,False));return
        measurement=fresh_source_check(h,leg_plan(base,3),measurement_only=True)
        plan=measured_pickup_plan(base,3,measurement)
        print(json.dumps(dict(measured_pickup=plan['source_top_mm'],unchanged_dropoff=plan['destination_top_mm'])),flush=True)
        asyncio.run(run_stage(h,plan,'hover',{},False));return
    ticket=resumed or dict(request_id='dcg48_repeat_'+uuid4().hex,action='falcon48_staged_dcg',
        plan_sha256=base['plan_sha256'],status='running_batch',rounds_requested=args.rounds,
        rounds_completed=0,transfers_completed=0,write_attempted=False,
        operator_confirmation='Five round trips 3 -> 4 -> 3; original recorded placement at both sites',
        original_site3=base['destination_top_mm'],original_site4=base['source_top_mm'])
    lock=h.folder/'dcg48_execution.lock';owned=False
    with lock.open('x',encoding='utf-8') as stream:stream.write(ticket['request_id'])
    try:
        if marker.exists() and resumed is None and args.resolve_empty_retry:
            owner=json.loads(marker.read_text());state=verify_empty_recovery(h,owner)
            archive=h.folder/(STOPPED_BATCH+'_resolved_by_coordinated_empty_retry.json')
            with archive.open('x',encoding='utf-8') as f:json.dump(dict(original=owner,recovery_request_id=EMPTY_RETRY,current_native_state=state,original_run_completed=False),f,indent=2)
            if json.loads(marker.read_text()).get('request_id')!=STOPPED_BATCH:raise RuntimeError('Ownership changed')
            marker.unlink()
        ticket.update(status='running_batch',release_clearance_y_mm=args.release_clearance_mm,
            release_mode=base.get('release_mode','vendor_drop_plate'),release_outward_mm=base.get('release_outward_mm'),
            temporal_camera_frames=base.get('temporal_camera_frames',1))
        save_owned(marker,ticket,create=resumed is None);owned=True
        h.journal(ticket,'batch_begin',dict(ticket))
        camera_references=({int(k):v for k,v in ticket['camera_references'].items()} if resumed else {4:list(base['source_top_mm'])})
        for cycle in range(1,args.rounds+1):
            ticket['cycle']=cycle
            for source in (3,4):
                continuing=resumed is not None and cycle==1 and source==3
                plan=pending if continuing else leg_plan(base,source)
                if not continuing:check_park(h)
                ticket.update(source_site=source,destination_site=7-source,
                    capture_tag=f'cycle{cycle}_site{source}_before',stage='camera_preflight')
                save_owned(marker,ticket)
                print(f'ROUND {cycle}/{args.rounds}: site {source} -> {7-source}',flush=True)
                if not continuing:
                    measurement=fresh_source_check(h,plan,ticket,measurement_only=True)
                    plan=measured_pickup_plan(base,source,measurement)
                    camera_references.setdefault(source,measurement['native_center_mm'])
                    h.journal(ticket,'measured_pickup_plan',plan)
                for stage in (('release_return',) if continuing else STAGES):
                    ticket['stage']=stage;save_owned(marker,ticket)
                    h.journal(ticket,'batch_stage_begin',dict(cycle=cycle,source_site=source,stage=stage,plan=plan))
                    asyncio.run(run_stage(h,plan,stage,ticket,True,reopen_hover=stage=='pickup_lift'))
                    save_owned(marker,ticket)
                    if args.inspect_first_seat and cycle==1 and source==3 and stage=='transfer_seat':
                        ticket.update(status='awaiting_site4_seating_inspection',pending_plan=plan,
                            camera_references=camera_references,next_stage='release_return')
                        save_owned(marker,ticket);h.journal(ticket,'inspection_checkpoint',dict(ticket))
                        print('STOPPED BEFORE SITE 4 RELEASE: inspect seating and jaw/holder contact; five-round batch remains pending',flush=True)
                        return
                check_park(h)
                # After release and parking, verify the actual plate at the exact
                # intended destination before counting the transfer or proceeding.
                ticket.update(stage='camera_arrival',capture_tag=f'cycle{cycle}_site{7-source}_after')
                save_owned(marker,ticket)
                arrival_plan=leg_plan(base,7-source)
                arrival_plan['source_top_mm'][:2]=camera_references[7-source][:2]
                arrival=fresh_source_check(h,arrival_plan,ticket)
                h.journal(ticket,'camera_arrival',dict(cycle=cycle,site=7-source,**arrival))
                ticket['transfers_completed']+=1;save_owned(marker,ticket)
                print(f'VERIFIED transfer {ticket["transfers_completed"]}/{2*args.rounds}: plate at site {7-source}; Hamilton parked',flush=True)
            ticket['rounds_completed']=cycle;save_owned(marker,ticket)
            h.journal(ticket,'round_completed',dict(cycle=cycle,plate_site=3))
        ticket.update(status='completed',stage=None,plate_site=3)
        save_owned(marker,ticket);h.journal(ticket,'outcome',dict(ticket))
        report=h.folder/ticket['request_id']/'result.json'
        report.write_text(json.dumps(ticket,indent=2),encoding='utf-8')
        if json.loads(marker.read_text()).get('request_id')!=ticket['request_id']:
            raise RuntimeError('Ownership changed; retaining marker')
        marker.unlink()
        print(f'COMPLETE: {args.rounds} round trips; plate at original site 3 position; Hamilton parked. Report: {report}',flush=True)
    except BaseException as error:
        ticket.update(status='failed_or_uncertain',error=str(error))
        if owned:
            save_owned(marker,ticket);h.journal(ticket,'outcome',dict(ticket))
        raise
    finally:lock.unlink(missing_ok=True)

if __name__=='__main__':main()
