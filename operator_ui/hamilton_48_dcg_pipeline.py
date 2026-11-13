"""Staged Falcon-48 DCG commissioning. Default: offline preview, NO movement.

Each physical stage requires --execute-confirmed. Stops for inspection after
hover, 5 mm proof lift, and seating BEFORE release. Never retries or clears faults.
An active ownership marker remains across inspection pauses, blocking other work.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import time
from uuid import uuid4
import zipfile
import cv2
import numpy as np
from hamilton_48_dcg_plan import STAGES, actions, verify_plan, assert_bounds, validated_frame
from hamilton_plate_offset import detect_grid, register_crop, camera_offset, FALCON48, OffsetError
from hamilton_dcg_transfer import (C, PrepDriver, HamiltonTCPClient, Deck, HamiltonPrep,
    PrepPickupDCG, DoorClosed, to_jsonable, rest_ready, xyz, PLAN as VENDOR_REFERENCE)
from retry_hamilton_dcg_coordinated import corridor as coordinated_corridor, rows as coordinate_rows

def compile_action(plan,action):
    p=plan['profile'];g=p['plate'];kind=action['command']
    if kind=='PickupDCG': return PrepPickupDCG(**VENDOR_REFERENCE['pickup_dcg'])
    if kind in ('RaiseEmpty','RaiseToSafe'): return C.PrepMoveZUpToSafe(channels=[1,2])
    if kind in ('OpenMove','CoordinatedOpen','CoordinatedLift','CoordinatedClearance'):
        return C.PrepMoveToPosition(move_parameters=C.GantryMoveXYZParameters(default_values=False,
            gantry_x_position=action['x'],axis_parameters=[C.ChannelYZMoveParameters(
                default_values=False,channel=i,y_position=action['y'][i],z_position=action['z']) for i in (1,2)]))
    if kind=='PickupPlate': return C.PrepPickUpPlate(plate_top_center=xyz(action['top']),
        plate=C.PlateDimensions(default_values=False,length=g['base_length_mm'],width=g['grip_body_width_mm'],height=g['height_mm']),
        clearance_y=p['clearance_y_mm'],grip_speed_y=p['grip_speed_mm_s'],
        grip_distance=p['grip_distance_mm'],grip_height=plan['grip_z_mm'])
    if kind=='MovePlate': return C.PrepMovePlate(plate_top_center=xyz(action['top']),acceleration_scale_x=20)
    if kind=='DropPlate': return C.PrepDropPlate(plate_top_center=xyz(action['top']),clearance_y=plan.get('release_clearance_y_mm',p['clearance_y_mm']),acceleration_scale_x=20)
    if kind=='OpenAtSeat':return C.PrepMoveYAbsolute(channels=[C.ChannelYPositionParameters(
        default_values=False,channel=i,y_position=action['y'][i]) for i in (1,2)],velocity=1)
    if kind in ('LiftOpen','RaiseOpen'):return C.PrepMoveZAbsolute(channels=[C.ChannelZPositionParameters(
        default_values=False,channel=i,z_position=action['z']) for i in (1,2)],velocity=action['speed'])
    if kind=='ReleaseAbovePlate':return C.PrepReleasePlate()
    if kind=='DropTool': return C.PrepDropTool()
    if kind=='Park': return C.PrepPark()
    if kind in ('Slow','Fast'): return C.PrepSetZSpeedScale(value=plan['slow_scale' if kind=='Slow' else 'fast_scale'])
    raise ValueError('Unknown action')

def pose_matches(actual,expected,tolerance=.5):
    a={v['channel']:v for v in actual['positions']};b={v['channel']:v for v in expected['positions']}
    return (set(a)==set(b) and all(abs(a[c][key]-b[c][key])<=tolerance
            for c in b for key in ('position_x','position_y','position_z')))

def check_transition(session,plan,stage):
    index=STAGES.index(stage)
    if session is None:
        if index!=0: raise RuntimeError('Begin with the open-gripper hover inspection')
        return
    if (session.get('action')!='falcon48_staged_dcg' or session.get('plan_sha256')!=plan['plan_sha256']
            or session.get('status')!='awaiting_inspection' or session.get('next_stage')!=stage):
        raise RuntimeError('Stage does not match the stopped commissioning session')

def check_reopen_pose(initial,checkpoint,plan):
    """Only permit spreading empty jaws that stayed at the inspected hover X/Z."""
    if initial['plate_held'] or initial['tool']['value'].get('label')!='DCG':
        raise RuntimeError('Reopening requires the empty DCG tool')
    a={p['channel']:p for p in initial['positions']['positions']}
    b={p['channel']:p for p in checkpoint['positions']['positions']}
    target=actions(plan,'hover')[-1]
    if set(a)!={1,2} or set(b)!={1,2}:raise RuntimeError('Unexpected channels')
    for c in (1,2):
        for key,want in (('position_x',target['x']),('position_z',target['z'])):
            if not abs(a[c][key]-want)<=.5 or not abs(a[c][key]-b[c][key])<=.5:
                raise RuntimeError('Reopening requires unchanged inspected hover X/Z')
        if not target['y'][2]-.5<=a[c]['position_y']<=target['y'][1]+.5:
            raise RuntimeError('Jaw moved outside the inspected opening')
    if not a[1]['position_y']>a[2]['position_y']:raise RuntimeError('Unexpected jaw order')

def stage_actions(plan,stage,reopen_hover=False):
    if stage=='release_return' and plan.get('release_mode')=='coordinated_open_retreat':
        if reopen_hover:raise ValueError('Cannot reopen hover in release')
        if plan.get('release_outward_mm')!=10:raise ValueError('Coordinated trial requires the tested 10 mm per jaw')
        x,center,_=plan['destination_top_mm'];half=(plan['profile']['plate']['grip_body_width_mm']+20)/2
        common=dict(x=x,y={1:center+half,2:center-half})
        return [dict(command='Slow'),dict(command='CoordinatedOpen',outward_mm=10,z=plan['grip_z_mm'],**common),
            dict(command='CoordinatedLift',z=plan['grip_z_mm']+10,**common),
            dict(command='CoordinatedClearance',z=165,**common),dict(command='ReleaseAbovePlate'),
            dict(command='Fast'),dict(command='DropTool'),dict(command='Park')]
    if stage=='release_return' and plan.get('release_mode')=='separate_open_retreat':
        if reopen_hover:raise ValueError('Cannot reopen hover in release')
        # Runtime targets are measured jaw positions +/- the requested travel.
        # These preview targets conservatively bound the observed grip width.
        travel=plan.get('release_outward_mm',6.)
        if travel not in (6,10):raise ValueError('Reviewed independent release requires 6 or 10 mm per jaw')
        half=(plan['profile']['plate']['grip_body_width_mm']+2*travel)/2
        center=plan['destination_top_mm'][1]
        return [dict(command='Slow'),dict(command='OpenAtSeat',outward_mm=travel,y={1:center+half,2:center-half}),
            dict(command='LiftOpen',z=plan['grip_z_mm']+10,speed=1),
            dict(command='RaiseToSafe'),dict(command='ReleaseAbovePlate'),
            dict(command='Fast'),dict(command='DropTool'),dict(command='Park')]
    if reopen_hover:
        if stage!='pickup_lift':raise ValueError('Hover reopening is only valid before pickup')
        return [dict(command='Slow'),actions(plan,'hover')[-1],*actions(plan,stage)]
    return actions(plan,stage)

def measured_release_action(action,positions,bounds):
    travel=action.get('outward_mm')
    if action.get('command')!='OpenAtSeat' or travel not in (6,10):
        raise ValueError('Expected reviewed 6 or 10 mm opening')
    rows={p['channel']:p for p in positions['positions']};limits={b['channel']:b for b in bounds}
    if set(rows)!={1,2} or len(positions['positions'])!=2:raise ValueError('Unexpected channels')
    targets={c:rows[c]['position_y']+(travel if c==1 else -travel) for c in (1,2)}
    if not all(np.isfinite(y) and limits[c]['y_min']<=y<=limits[c]['y_max'] for c,y in targets.items()):
        raise ValueError('Opening exceeds native limits')
    return dict(action,y=targets)

def measured_coordinated_action(action,positions,bounds,grip_z):
    """Specify all axes, preserving measured jaw positions throughout vertical retreat."""
    current=coordinate_rows(positions);kind=action['command']
    if kind not in ('CoordinatedOpen','CoordinatedLift','CoordinatedClearance'):raise ValueError('Not a coordinated release action')
    if abs(current[1]['position_x']-current[2]['position_x'])>.1:raise RuntimeError('Shared X feedback disagrees')
    x=current[1]['position_x'];ys={c:current[c]['position_y'] for c in (1,2)}
    if kind=='CoordinatedOpen':
        if action.get('outward_mm')!=10 or any(abs(p['position_z']-grip_z)>.1 for p in current.values()):raise RuntimeError('Opening requires verified seated height')
        ys={1:ys[1]+10,2:ys[2]-10}
    else:
        if any(p['position_z']>action['z']+.1 for p in current.values()):raise RuntimeError('Release retreat must only rise')
    for b in bounds:
        if not (b['x_min']<=x<=b['x_max'] and b['y_min']<=ys[b['channel']]<=b['y_max'] and b['z_min']<=action['z']<=b['z_max']):
            raise RuntimeError('Coordinated release exceeds native bounds')
    return dict(action,x=x,y=ys)

def coordinated_goal(action):
    return {c:dict(position_x=action['x'],position_y=action['y'][c],position_z=action['z']) for c in (1,2)}

def temporal_median(frames):
    if len(frames)!=5 or any(f is None or f.dtype!=np.uint8 or f.shape!=frames[0].shape for f in frames):
        raise ValueError('Five same-size camera frames required')
    return np.median(np.stack(frames),axis=0).astype(np.uint8)

def fresh_source_check(h,plan,ticket=None,*,measurement_only=False):
    source_site=plan.get('source_site',4);destination_site=plan.get('destination_site',3)
    calibration=json.loads((Path(plan['capture_folder'])/'deck-calibration.json').read_text())
    exported=h.call('GET','calibration/export',binary=True)
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        current=json.loads(archive.read('deck-calibration.json'))
    if current!=calibration: raise RuntimeError('Camera calibration changed; rebuild the plan')
    frame=validated_frame(json.loads(Path(plan['frame_file']).read_text()),plan['camera_calibration_sha256'])
    samples=[];rejected=[]
    for index in range(3):
        count=5 if plan.get('temporal_camera_frames')==5 else 1
        raw_frames=[];crop_frames=[]
        for frame_index in range(count):
            raw_bytes=h.call('GET','camera/false',binary=True)
            crop_bytes=h.call('GET',f'camera/position/{source_site}/15/20.19',binary=True)
            raw_frames.append(cv2.imdecode(np.frombuffer(raw_bytes,np.uint8),0))
            crop_frames.append(cv2.imdecode(np.frombuffer(crop_bytes,np.uint8),0))
            if ticket is not None and count==5:
                folder=h.folder/ticket['request_id']/ticket.get('capture_tag','source');folder.mkdir(parents=True,exist_ok=True)
                (folder/f'raw_{index}_burst{frame_index}.png').write_bytes(raw_bytes)
                (folder/f'site{source_site}_{index}_burst{frame_index}.png').write_bytes(crop_bytes)
        raw=temporal_median(raw_frames) if count==5 else raw_frames[0]
        crop=temporal_median(crop_frames) if count==5 else crop_frames[0]
        if count==5:
            raw_bytes=cv2.imencode('.png',raw)[1].tobytes();crop_bytes=cv2.imencode('.png',crop)[1].tobytes()
        if ticket is not None:
            folder=h.folder/ticket['request_id']/ticket.get('capture_tag','source');folder.mkdir(parents=True,exist_ok=True)
            (folder/f'raw_{index}.png').write_bytes(raw_bytes)
            (folder/f'site{source_site}_{index}.png').write_bytes(crop_bytes)
        try:
            grid=detect_grid(crop,FALCON48)
            reg=register_crop(crop,raw,calibration)
            measured=camera_offset(grid,reg,calibration,20.19,20.19)
        except OffsetError as error:
            rejected.append(str(error));continue
        if abs(grid['angle_crop_deg'])>.5 or measured['plane_tilt_deg']>3:
            raise RuntimeError(f'Plate angle/tilt changed: in-plane {grid["angle_crop_deg"]:.3f} degrees (limit 0.5), plane tilt {measured["plane_tilt_deg"]:.3f} degrees (limit 3)')
        native=np.asarray(frame['rotation'])@measured['known_plane_center_export_frame_mm']+frame['translation_mm']
        samples.append(dict(native_center_mm=native.tolist(),grid_wells=len(grid['centers']),
            temporal_frames=count,angle_crop_deg=grid['angle_crop_deg'],plane_tilt_deg=measured['plane_tilt_deg']))
    try:centers=consistent_source_samples(samples,plan,check_target=not measurement_only)
    except RuntimeError as error:
        raise RuntimeError(str(error)+'; rejected exposures: '+repr(rejected)) from error
    scan={v['positionId']:v for v in h.call('GET','deck/scan/3')}
    if not scan[source_site]['isOccupied'] or scan[destination_site]['isOccupied']:
        raise RuntimeError(f'Require source plate at site {source_site} and empty site {destination_site}')
    return dict(native_center_mm=centers.mean(axis=0).tolist(),samples=samples,rejected=rejected,scan=scan)

def consistent_source_samples(samples,plan,*,check_target=True):
    # Up to one unusable exposure is allowed; contradictory estimates are not.
    if len(samples)<2: raise RuntimeError('Fewer than two valid current plate measurements; no movement')
    centers=np.asarray([s['native_center_mm'] for s in samples])
    if not np.isfinite(centers).all(): raise RuntimeError('Nonfinite camera measurement')
    if np.max(np.linalg.norm(centers[:,:2]-centers[:,:2].mean(axis=0),axis=1))>.15:
        raise RuntimeError('Current camera measurements disagree')
    if check_target and np.max(np.linalg.norm(centers[:,:2]-np.asarray(plan['source_top_mm'][:2]),axis=1))>.5:
        raise RuntimeError(f'Plate differs from planned source pose: measured XY {centers[:,:2].mean(axis=0).round(3).tolist()}, expected {np.asarray(plan["source_top_mm"][:2]).round(3).tolist()}; rebuild the plan')
    return centers

async def run_stage(h,plan,stage,ticket,execute,reopen_hover=False):
    if execute and plan.get('release_mode')=='separate_open_retreat':
        raise RuntimeError('Independent-jaw plate cycles suspended: direct-axis opening reproduced front-jaw reversal. Coordinated XYZ passed an empty-jaw test, but loaded release remains unvalidated; do not replay this old release sequence.')
    if execute and plan.get('release_mode')=='coordinated_open_retreat':
        raise RuntimeError('Coordinated plate cycles suspended: the first loaded release at seated height raised both jaws before opening. High-clearance empty validation does not validate seated release; review the stopped plate before recovery.')
    reads={C.PrepGetIsInitialized,C.PrepGetPositions,C.PrepGetChannelBounds,C.PrepGetDeckSiteDefinitions,
           C.PrepGetPlateHeld,C.PrepGetTipDefinitionHeld,C.PrepGetXSpeedScale,C.PrepGetZSpeedScale,
           C.PrepIsParked,DoorClosed,C.PrepGetIsEnclosurePresent}
    writes={PrepPickupDCG,C.PrepMoveZUpToSafe,C.PrepMoveToPosition,C.PrepPickUpPlate,C.PrepMovePlate,
            C.PrepDropPlate,C.PrepDropTool,C.PrepPark,C.PrepSetXSpeedScale,C.PrepSetZSpeedScale,
            C.PrepMethodBegin,C.PrepMethodEnd,C.PrepMethodAbort}
    if plan.get('release_mode') in ('separate_open_retreat','coordinated_open_retreat'):
        writes.update({C.PrepMoveYAbsolute,C.PrepMoveZAbsolute,C.PrepReleasePlate})
    class Driver(PrepDriver):
        async def setup(self,**kw): raise RuntimeError('Automatic setup disabled')
        async def stop(self,**kw): raise RuntimeError('Transport close only')
        async def send_command(self,command,**kwargs):
            if type(command) not in reads|writes: raise RuntimeError('Unreviewed command')
            if type(command) in writes:
                if not execute: raise RuntimeError('Read-only check cannot write')
                ticket['write_attempted']=True
                h.journal(ticket,'native_request',dict(stage=stage,command=type(command).__name__,parameters=to_jsonable(command)))
            response=await super().send_command(command,**kwargs)
            if type(command) in writes:
                h.journal(ticket,'native_response',dict(command=type(command).__name__,response=to_jsonable(response)))
            return response
    def make():
        return Driver(deck=Deck(name='falcon48_trial',size_x=300,size_y=430,size_z=200),
                      io=HamiltonTCPClient(host='192.168.100.102',port=2000,read_timeout=60,write_timeout=5))
    motion,monitor,abort=make(),make(),make();began=False
    async def interlocks():
        if not (await monitor.send_command(DoorClosed(),read_timeout=2)).value:
            raise RuntimeError('Door opened')
        if not (await monitor.send_command(C.PrepGetIsEnclosurePresent(),read_timeout=2)).value:
            raise RuntimeError('Enclosure absent')
    async def checked(command,goal=None,start=None):
        await interlocks();await asyncio.to_thread(rest_ready,h)
        print('Running '+type(command).__name__,flush=True)
        pending=asyncio.create_task(motion.send_command(command,read_timeout=60))
        try:
            deadline=time.monotonic()+65
            while not pending.done():
                await asyncio.wait({pending},timeout=.05 if goal else .25)
                if goal:
                    feedback=to_jsonable(await monitor.send_command(C.PrepGetPositions(),read_timeout=2))
                    h.journal(ticket,'coordinated_motion_sample',dict(positions=feedback,goal=goal))
                    coordinated_corridor(coordinate_rows(feedback),start,goal)
                if pending.done(): break
                await interlocks()
                if time.monotonic()>deadline: raise TimeoutError('Command timed out')
                if await asyncio.to_thread(h.call,'GET','errors/check-for-pending-errors'):
                    raise RuntimeError('Hamilton reported an error')
            result=await pending
            if goal:
                for _ in range(5):
                    feedback=to_jsonable(await monitor.send_command(C.PrepGetPositions(),read_timeout=2))
                    h.journal(ticket,'coordinated_arrival_sample',dict(positions=feedback,goal=goal))
                    coordinated_corridor(coordinate_rows(feedback),start,goal,arrival=True)
                    await asyncio.sleep(.1)
            return result
        except BaseException:
            if goal:
                try:await asyncio.wait_for(abort.send_command(C.PrepMethodAbort(),read_timeout=3),4)
                except BaseException as error:h.journal(ticket,'abort_failed',str(error))
            pending.cancel();await asyncio.gather(pending,return_exceptions=True);raise
    async def snapshot():
        return dict(positions=to_jsonable(await motion.send_command(C.PrepGetPositions())),
                    plate_held=(await motion.send_command(C.PrepGetPlateHeld())).value,
                    tool=to_jsonable(await motion.send_command(C.PrepGetTipDefinitionHeld())))
    try:
        for d in (motion,monitor,abort): await asyncio.wait_for(d._open(),20)
        for name,expected in (('PickupDCG',45),('MoveToPosition',26),('MoveZUpToSafe',28),('PickupPlate',17),('MovePlate',19),('DropPlate',18),('DropTool',16)):
            method=await motion.request_method_by_name('MLPrepRoot.PipettorRoot.Pipettor',name)
            if (method.interface_id,method.method_id)!=(1,expected): raise RuntimeError('Firmware signature changed: '+name)
        for name,expected in (('GetIsDoorClosed',22),('Park',C.PrepPark.command_id),('IsParked',C.PrepIsParked.command_id)):
            method=await motion.request_method_by_name('MLPrepRoot.MLPrep',name)
            if (method.interface_id,method.method_id)!=(1,expected): raise RuntimeError('Firmware signature changed: '+name)
        if plan.get('release_mode')=='separate_open_retreat':
            for cls,name in ((C.PrepMoveYAbsolute,'MoveYAbsolute'),(C.PrepMoveZAbsolute,'MoveZAbsolute'),(C.PrepReleasePlate,'ReleasePlate')):
                method=await motion.request_method_by_name(cls.firmware_path,name)
                if (method.interface_id,method.method_id)!=(1,cls.command_id):raise RuntimeError('Firmware signature changed: '+name)
        await interlocks()
        if not (await motion.send_command(C.PrepGetIsInitialized())).value: raise RuntimeError('Not initialized')
        bounds=to_jsonable(await motion.send_command(C.PrepGetChannelBounds()))['bounds']
        assert_bounds(plan,bounds)
        if plan.get('release_mode') in ('separate_open_retreat','coordinated_open_retreat'):
            split=stage_actions(plan,'release_return');targets=split[1]['y']
            for b in bounds:
                if not b['y_min']<=targets[b['channel']]<=b['y_max'] or not b['z_min']<=plan['grip_z_mm']+10<=165<=b['z_max']:
                    raise RuntimeError('Separate release exceeds native bounds')
        sites={str(v['id']):v for v in to_jsonable(await motion.send_command(C.PrepGetDeckSiteDefinitions()))['sites']}
        for site,expected in plan['native_sites'].items():
            for field in ('left_bottom_front_x','left_bottom_front_y','left_bottom_front_z','length','width'):
                if abs(sites[site][field]-expected[field])>.02: raise RuntimeError('Native site geometry changed')
        initial=await snapshot()
        if not execute:
            print(json.dumps(dict(current=initial),indent=2),flush=True)
        if stage=='hover':
            await asyncio.to_thread(rest_ready,h,initial=True)
            if initial['plate_held'] or initial['tool']['value'].get('is_tool'):
                raise RuntimeError('Hover trial must start parked with empty channels')
            if not (await motion.send_command(C.PrepIsParked())).value: raise RuntimeError('Start parked')
            source_check=await asyncio.to_thread(fresh_source_check,h,plan,ticket if execute else None)
            ticket['original_scales']=[(await motion.send_command(C.PrepGetXSpeedScale())).value,
                                       (await motion.send_command(C.PrepGetZSpeedScale())).value]
            if execute: h.journal(ticket,'fresh_source',source_check)
        else:
            expected_held=stage in ('transfer_seat','release_return')
            if initial['plate_held']!=expected_held or initial['tool']['value'].get('label')!='DCG':
                raise RuntimeError('Payload/tool state differs from the previous checkpoint')
            if reopen_hover:
                if stage!='pickup_lift':raise RuntimeError('Reopening is only valid before pickup')
                check_reopen_pose(initial,ticket['checkpoint'],plan)
            elif not pose_matches(initial['positions'],ticket['checkpoint']['positions']):
                raise RuntimeError('Gripper moved since the last checked stage')
        if not execute:
            print('READ-ONLY STAGE CHECK PASSED; no movement',flush=True);return
        h.journal(ticket,'stage_initial',dict(stage=stage,**initial))
        began=True;await checked(C.PrepMethodBegin(automatic_pause=True))
        await checked(C.PrepSetXSpeedScale(value=plan['fast_scale']))
        await checked(C.PrepSetZSpeedScale(value=plan['fast_scale']))
        held=initial['plate_held']
        previous=initial
        for action in stage_actions(plan,stage,reopen_hover):
            goal=None;start=None
            if action['command'] in ('CoordinatedOpen','CoordinatedLift','CoordinatedClearance'):
                action=measured_coordinated_action(action,previous['positions'],bounds,plan['grip_z_mm'])
                goal=coordinated_goal(action);start=coordinate_rows(previous['positions'])
            if action['command']=='OpenAtSeat':
                action=measured_release_action(action,previous['positions'],bounds)
                for pos in previous['positions']['positions']:
                    c=pos['channel'];target=action['y'][c]
                    if (c==1 and target<=pos['position_y']) or (c==2 and target>=pos['position_y']):
                        raise RuntimeError('Release opening would move a jaw inward')
                    if abs(pos['position_z']-plan['grip_z_mm'])>.1:raise RuntimeError('Release requires verified seated height')
            if action['command']=='ReleaseAbovePlate' and min(p['position_z'] for p in previous['positions']['positions'])<164.9:
                raise RuntimeError('Native release requires clearance above plate')
            await checked(compile_action(plan,action),goal,start)
            state=await snapshot();kind=action['command']
            h.journal(ticket,'action_arrival',dict(action=kind,**state))
            if kind=='PickupPlate': held=True
            if kind in ('DropPlate','ReleaseAbovePlate'): held=False
            if state['plate_held']!=held: raise RuntimeError('Unexpected held-plate state')
            if kind=='PickupDCG' and state['tool']['value'].get('label')!='DCG': raise RuntimeError('DCG pickup not confirmed')
            if kind=='DropTool' and state['tool']['value'].get('is_tool'): raise RuntimeError('Tool return not confirmed')
            if kind in ('OpenAtSeat','LiftOpen','RaiseOpen'):
                old={p['channel']:p for p in previous['positions']['positions']}
                for pos in state['positions']['positions']:
                    c=pos['channel'];want=dict(old[c])
                    if kind=='OpenAtSeat':want['position_y']=action['y'][c]
                    else:want['position_z']=action['z']
                    if any(not np.isfinite(pos[k]) or abs(pos[k]-want[k])>.1 for k in ('position_x','position_y','position_z')):
                        raise RuntimeError('Separate release arrival mismatch')
            if kind=='ReleaseAbovePlate':
                for pos in state['positions']['positions']:
                    if abs(pos['position_x']-plan['destination_top_mm'][0])>.1 or pos['position_z']<164.9:
                        raise RuntimeError('Unexpected native release motion at clearance')
            if kind=='RaiseToSafe':
                for pos in state['positions']['positions']:
                    limit=next(b for b in bounds if b['channel']==pos['channel'])
                    if (not all(np.isfinite(pos[k]) for k in ('position_x','position_y','position_z'))
                        or abs(pos['position_x']-plan['destination_top_mm'][0])>.1
                        or abs(pos['position_z']-limit['z_max'])>.1
                        or not limit['y_min']<=pos['position_y']<=limit['y_max']):
                        raise RuntimeError('Safe-height retreat feedback mismatch')
            if kind in ('OpenMove','MovePlate'):
                z=action.get('z',action.get('top',[0,0,0])[2]-(plan['source_top_mm'][2]-plan['grip_z_mm']))
                x=action.get('x',action.get('top',[0])[0])
                for position in state['positions']['positions']:
                    if abs(position['position_x']-x)>.5 or abs(position['position_z']-z)>.5:
                        raise RuntimeError('Command arrival mismatch')
                    if kind=='OpenMove' and abs(position['position_y']-action['y'][position['channel']])>.5:
                        raise RuntimeError('Open-jaw Y arrival mismatch')
                if kind=='MovePlate':
                    center_y=np.mean([v['position_y'] for v in state['positions']['positions']])
                    if abs(center_y-action['top'][1])>.5: raise RuntimeError('Plate-center Y arrival mismatch')
            h.journal(ticket,'stage_feedback',dict(action=kind,**state))
            previous=state
        if stage=='release_return':
            if not (await motion.send_command(C.PrepIsParked())).value: raise RuntimeError('Park not verified')
            await checked(C.PrepSetXSpeedScale(value=ticket['original_scales'][0]))
            await checked(C.PrepSetZSpeedScale(value=ticket['original_scales'][1]))
        await checked(C.PrepMethodEnd());began=False
        ticket['checkpoint']=await snapshot()
    except BaseException:
        if began:
            try: await asyncio.wait_for(abort.send_command(C.PrepMethodAbort(),read_timeout=5),7)
            except BaseException as e: h.journal(ticket,'abort_failed',str(e))
        raise
    finally:
        for d in (motion,monitor,abort): await d._close()

def save_owned(marker,ticket,*,create=False):
    """Never replace another instrument operation's ownership marker."""
    payload=json.dumps(ticket,indent=2)
    if create:
        with marker.open('x',encoding='utf-8') as stream: stream.write(payload)
        return
    current=json.loads(marker.read_text())
    if current.get('request_id')!=ticket['request_id'] or current.get('action')!='falcon48_staged_dcg':
        raise RuntimeError('Instrument ownership changed; preserving the other operation')
    temp=marker.with_name(ticket['request_id']+'.tmp')
    temp.write_text(payload,encoding='utf-8');os.replace(temp,marker)

def archive_unstarted(h,plan):
    marker=h.folder/'active.json';ticket=json.loads(marker.read_text())
    if (ticket.get('action')!='falcon48_staged_dcg' or ticket.get('plan_sha256')!=plan['plan_sha256']
            or ticket.get('write_attempted') is not False or ticket.get('checkpoint') is not None):
        raise RuntimeError('This operation cannot be resolved as an unstarted preflight')
    events=[json.loads(line) for line in (h.folder/(ticket['request_id']+'.jsonl')).read_text().splitlines()]
    if any(e.get('kind')=='native_request' for e in events):
        raise RuntimeError('A controller write was logged; retain the recovery hold')
    ticket.update(status='preflight_rejected',motion_sent=False)
    archive=h.folder/(ticket['request_id']+'_not_started.json')
    with archive.open('x',encoding='utf-8') as stream:json.dump(ticket,stream,indent=2)
    if json.loads(marker.read_text()).get('request_id')!=ticket['request_id']:
        raise RuntimeError('Ownership changed; marker retained')
    marker.unlink()
    print('Archived rejected preflight; verified no controller commands were sent')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('plan',type=Path);p.add_argument('--stage',choices=STAGES,default='hover')
    p.add_argument('--reopen-hover',action='store_true',help='Explicitly spread empty jaws at unchanged inspected hover before pickup')
    modes=p.add_mutually_exclusive_group();modes.add_argument('--check',action='store_true');modes.add_argument('--execute-confirmed',action='store_true');modes.add_argument('--archive-unstarted',action='store_true')
    args=p.parse_args();plan=json.loads(args.plan.read_text());verify_plan(plan)
    compiled=[compile_action(plan,a) for a in stage_actions(plan,args.stage,args.reopen_hover)]
    for command in compiled: command.build_parameters().build()
    if not args.check and not args.execute_confirmed and not args.archive_unstarted:
        print(json.dumps(dict(stage=args.stage,motion_sent=False,commands=[to_jsonable(c) for c in compiled]),indent=2));return
    h=HamiltonPrep();rest_ready(h)
    if args.archive_unstarted:
        archive_unstarted(h,plan);return
    marker=h.folder/'active.json'
    session=json.loads(marker.read_text()) if marker.exists() else None
    check_transition(session,plan,args.stage)
    ticket=session or dict(request_id='dcg48_'+uuid4().hex,action='falcon48_staged_dcg',
                           plan_sha256=plan['plan_sha256'],status='starting',write_attempted=False)
    if args.check:
        asyncio.run(run_stage(h,plan,args.stage,ticket,False,args.reopen_hover));return
    lock=h.folder/'dcg48_execution.lock'
    with lock.open('x',encoding='utf-8') as stream: stream.write(ticket['request_id'])
    owned=False
    try:
        current=json.loads(marker.read_text()) if marker.exists() else None
        check_transition(current,plan,args.stage)
        if current is not None and current.get('request_id')!=ticket['request_id']:
            raise RuntimeError('Instrument ownership changed')
        ticket.update(status='running',stage=args.stage,operator_confirmation=True)
        ticket['reopen_hover_confirmed']=args.reopen_hover
        save_owned(marker,ticket,create=current is None);owned=True
        h.journal(ticket,'stage_begin',dict(stage=args.stage,plan=plan))
        asyncio.run(run_stage(h,plan,args.stage,ticket,True,args.reopen_hover))
        state=rest_ready(h)
        if args.stage=='release_return':
            if not state.get('parked') or h.call('GET','service-software-api/has-tips') is not False:
                raise RuntimeError('Final parked/empty verification failed')
            ticket.update(status='completed',next_stage=None)
            save_owned(marker,ticket);h.journal(ticket,'outcome',ticket)
            (args.plan.parent/'completed_trial.json').write_text(json.dumps(ticket,indent=2),encoding='utf-8')
            marker.unlink()
            print('Transfer complete; tool returned; Hamilton parked. Physical seating result still requires operator observation.',flush=True)
        else:
            ticket.update(status='awaiting_inspection',next_stage=STAGES[STAGES.index(args.stage)+1])
            save_owned(marker,ticket);h.journal(ticket,'inspection_checkpoint',ticket)
            print('STOPPED FOR INSPECTION: '+args.stage+'; next stage '+ticket['next_stage'],flush=True)
    except BaseException as e:
        ticket.update(status='failed_or_uncertain',error=str(e))
        if owned:
            try: save_owned(marker,ticket)
            except Exception as marker_error: h.journal(ticket,'ownership_changed',str(marker_error))
            h.journal(ticket,'outcome',ticket)
        raise
    finally:
        lock.unlink(missing_ok=True)

if __name__=='__main__':main()
