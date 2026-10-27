"""One authorized experimental two-tip pickup; stop on first failure, never retry.

Uses the controller's stored 300 uL filtered definition and the pinned driver's
collar-rest convention. Does not change calibration or interlock configuration.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from run_camera_hover_trial import get, preflight, fixed_post_check, capture, SOURCE, PIN, ROOT
from hamilton_hover_alignment import plan_hover
from prep_door_monitor import PrepGetIsDoorClosed, verify_door_method, read_interlocks

def prepare(folder):
    probe = json.loads((folder/'probe.json').read_text())
    estimate = json.loads((folder/'tip_plane_estimate.json').read_text())
    if estimate['tip_rims_used'] < 50 or estimate['pose_reprojection_rms_pixels'] > 2 or estimate['crop_registration_rms_pixels'] > .7:
        raise ValueError('Vision quality failed.')
    grid={(p['column'],p['row']):p for p in estimate['grid_points']}
    selected=None
    # Each pair stays within the reviewed site-4 region with 27 mm spacing.
    # Require both current rims to be directly detected; never fill missing rims.
    for rows in ((3,6),(2,5),(1,4)):
        pair=[grid[4,r] for r in rows]
        if all(p['observed'] for p in pair):selected=pair;break
    if selected is None:raise ValueError('No reviewed pair of directly observed openings.')
    old = json.loads((ROOT/'coordinate_probe_20261025T015942Z/tip_plane_estimate.json').read_text())
    old_grid={(p['column'],p['row']):p for p in old['grid_points']}
    for a in selected:
        b=old_grid[a['column'],a['row']]
        if max(abs(x-y) for x,y in zip(a['exported_frame_xyz_mm'],b['exported_frame_xyz_mm'])) > .75:
            raise ValueError('Rack pose changed more than the trial permits.')
    q = probe['tcp_queries']
    definitions = q['PrepGetTipAndNeedleDefinitions']['definitions']
    matches = [d for d in definitions if d['label']=='300uL StdVolFilter' and d['has_filter'] and
               not d['is_needle'] and not d['is_tool'] and d['tip_type']==2 and
               abs(d['length']-51.9)<.001 and abs(d['volume']-360)<.001]
    if len(matches)!=1: raise ValueError('Stored tip definition does not match reviewed 235938 geometry.')
    start = {int(p['channel']):[p['position_x'],p['position_y'],p['position_z']] for p in q['PrepGetPositions']['positions']}
    bounds = {int(b['channel']):b for b in q['PrepGetChannelBounds']['bounds']}
    openings = [p['exported_frame_xyz_mm'] for p in selected]
    approach = plan_hover(start,bounds,openings,fixed_post_check(folder,probe))
    # The pickup command performs descent. Travel only at full clearance here.
    # Keep the reviewed clearance/region checks, but send a single coordinated
    # XY approach instead of restarting the trajectory every 10 mm.
    path = [approach['path'][0]]
    first_x = openings[0][0]
    path.append({'phase':'continuous_xy_approach_at_clearance','positions':{
        c:[first_x,openings[c-1][1],165.5] for c in (1,2)}})
    plan = {'capture_time':probe['time_utc'], 'start':start, 'path':path,
            'selected':selected,'stored_tip_definition':matches[0],
            'collar_height_mm':8.0, 'seek_above_rim_mm':5.0,
            'final_stop_disc_z':165.5,'seek_speed_mm_s':15.0,
            'authorization':'User requested one reattempt with continuous approach; no automatic retries',
            'contact_calibration_validated':False,
            'uncertainty':'Camera pose is an estimate, with only approximate fixed-post frame corroboration.'}
    (folder/'pickup_plan.json').write_text(json.dumps(plan,indent=2))
    return plan

def check_tip_state(expected):
    sensors=get('service-software-api/sensor-status')
    if sensors.get('isDoorClosed') is not True or sensors.get('isEnclosurePresent') is not True:
        raise RuntimeError('Door/enclosure is not confirmed.')
    state=sensors['independentChannelsSensorState']
    held={c for c,name in ((1,'frontChannel'),(2,'rearChannel')) if state[name]['sleeveSensor']}
    if held!=expected:raise RuntimeError(f'Tip sensor mismatch: expected {expected}, observed {held}')
    if get('errors/check-for-pending-errors'):raise RuntimeError('Pending instrument error.')
    if get('protocol-run').get('isRunInProgress'):raise RuntimeError('Concurrent protocol started.')
    status=get('verification/status')
    if any(status.get(k) for k in ('isWorkflowInProgress','isRunInProgress','isServiceRoutineInProgress')):
        raise RuntimeError('Concurrent service routine started.')
    return sensors

async def execute(folder,plan):
    travel_scale=plan.get('travel_x_scale',2)
    if isinstance(travel_scale,bool) or not isinstance(travel_scale,int) or not 2<=travel_scale<=10:
        raise ValueError('Reviewed travel scale is between 2 and 10.')
    seek_speed=plan.get('seek_speed_mm_s',15.0)
    pickup_z_scale=plan.get('pickup_z_scale',2)
    seek_offset=plan.get('z_seek_offset_mm',0.0)
    if not math.isfinite(seek_speed) or not 3<=seek_speed<=15 or pickup_z_scale not in (1,2):
        raise ValueError('Pickup speed outside the reviewed slow-trial range.')
    if seek_offset not in (0.0,-1.0):
        raise ValueError('Only original or native-log seek-start spacing is reviewed.')
    if subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip()!=PIN:
        raise RuntimeError('Source revision changed.')
    sys.path.insert(0,str(SOURCE))
    from pylabrobot.hamilton.prep.driver.master import PrepDriver
    from pylabrobot.hamilton.prep.driver import prep_commands as C
    from pylabrobot.hamilton.prep.driver.configuration import to_jsonable
    from pylabrobot.hamilton.transport.tcp.tcp import HamiltonTCPClient
    from pylabrobot.resources import Deck, Coordinate
    from pylabrobot.resources.hamilton.tip_creators import hamilton_tip_300uL_filter
    tip=hamilton_tip_300uL_filter('235938_trial')
    if tip.collar_height!=8 or abs(tip.get_size_z()-tip.fitting_depth-51.9)>.001:
        raise RuntimeError('Source tip geometry changed.')
    allowed={C.PrepGetPositions,C.PrepGetChannelBounds,C.PrepGetIsInitialized,
        PrepGetIsDoorClosed,C.PrepGetIsEnclosurePresent,
        C.PrepGetXSpeedScale,C.PrepGetZSpeedScale,C.PrepGetTipAndNeedleDefinitions,
        C.PrepGetTipDefinitionHeld,C.PrepMoveToPosition,C.PrepPickUpTipsById,
        C.PrepSetXSpeedScale,C.PrepSetZSpeedScale,C.PrepMethodBegin,C.PrepMethodEnd,C.PrepMethodAbort}
    def record(kind,data):
        row={'time':datetime.now(timezone.utc).isoformat(),'kind':kind,'data':data}
        with (folder/'pickup_journal.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
        if kind not in ('command','response','monitor'):print(json.dumps(row),flush=True)
    class TrialDriver(PrepDriver):
        async def send_command(self,command,**kwargs):
            if type(command) not in allowed:raise RuntimeError('Command outside pickup allowlist.')
            record('command',{'name':type(command).__name__,'parameters':to_jsonable(command)})
            r=await super().send_command(command,**kwargs)
            record('response',{'name':type(command).__name__,'result':to_jsonable(r)})
            return r
        async def setup(self,**kwargs):raise RuntimeError('Automatic setup disabled.')
        async def stop(self,**kwargs):raise RuntimeError('Automatic motion on close disabled.')
    def make_driver():
        return TrialDriver(deck=Deck(name='pickup_trial',size_x=300,size_y=400,size_z=200),
            io=HamiltonTCPClient(host='192.168.100.102',port=2000,read_timeout=90,write_timeout=4))
    motion,abort,monitor=make_driver(),make_driver(),make_driver()
    held=set();began=False;completed=False;scales=None;abort_sent=False
    async def abort_once():
        nonlocal abort_sent
        if not abort_sent:
            abort_sent=True
            try:await asyncio.wait_for(abort.send_command(C.PrepMethodAbort()),5)
            except BaseException as e:record('abort_failed',str(e))
    async def positions():
        return {int(p.channel):[p.position_x,p.position_y,p.position_z] for p in (await motion.send_command(C.PrepGetPositions())).positions}
    async def bounds():
        return {int(b.channel):to_jsonable(b) for b in (await motion.send_command(C.PrepGetChannelBounds())).bounds}
    def fresh():
        if (datetime.now(timezone.utc)-datetime.fromisoformat(plan['capture_time'])).total_seconds()>180:
            raise RuntimeError('Camera capture expired; no next motion.')
    async def checked(command):
        fresh()
        await asyncio.to_thread(check_tip_state,held)
        record('monitor_preflight',await read_interlocks(monitor))
        pending=asyncio.create_task(motion.send_command(command,read_timeout=90))
        try:
            deadline=time.monotonic()+90
            while not pending.done():
                await asyncio.wait({pending},timeout=.25)
                if pending.done():break
                sensors=await read_interlocks(monitor)
                record('monitor',sensors)
                if sensors.get('isDoorClosed') is not True or sensors.get('isEnclosurePresent') is not True:
                    raise RuntimeError('Door/enclosure changed during motion.')
                if time.monotonic()>deadline:raise TimeoutError('Motion exceeded trial deadline.')
            return await pending
        except BaseException:
            await abort_once()
            pending.cancel();await asyncio.gather(pending,return_exceptions=True)
            raise
    async def move(target):
        b=await bounds()
        before=await positions()
        if any(abs(target[c][i]-before[c][i])>.001 for c in (1,2) for i in (0,1)) and min(p[2] for p in before.values())<100:
            raise RuntimeError('Must retract vertically before any horizontal travel.')
        if set(target)!={1,2} or abs(target[1][0]-target[2][0])>.001 or target[2][1]-target[1][1]<15:
            raise RuntimeError('Invalid shared gantry or channel spacing.')
        for c,p in target.items():
            if p[2]<100:raise RuntimeError('Horizontal travel lacks tip-bottom clearance.')
            for axis,value in zip('xyz',p):
                if not math.isfinite(value) or not b[c][axis+'_min']<=value<=b[c][axis+'_max']:
                    raise RuntimeError('Move outside freshly reported channel limits.')
        await checked(C.PrepMoveToPosition(move_parameters=C.GantryMoveXYZParameters(
            default_values=False,gantry_x_position=target[1][0],axis_parameters=[
                C.ChannelYZMoveParameters(default_values=False,channel=c,y_position=target[c][1],z_position=target[c][2]) for c in (1,2)])))
        actual=await positions()
        # Faster clearance travel can return before encoder settling finishes.
        # Wait for stationary readback at clearance before any pickup descent.
        stable=False
        for _ in range(3):
            await asyncio.sleep(.2)
            settled=await positions()
            if all(abs(settled[c][i]-actual[c][i])<.05 for c in (1,2) for i in range(3)):
                actual=settled;stable=True;break
            actual=settled
        if not stable:raise RuntimeError('Position did not settle; no next motion.')
        if any(abs(actual[c][i]-target[c][i])>.2 for c in (1,2) for i in range(3)):
            raise RuntimeError('Position readback mismatch; no next motion.')
        record('position_readback',actual)
    try:
        record('preflight',await asyncio.to_thread(preflight))
        await motion._open();await abort._open();await monitor._open()
        await verify_door_method(monitor)
        record('direct_interlock_preflight',await read_interlocks(monitor))
        if not (await motion.send_command(C.PrepGetIsInitialized())).value:raise RuntimeError('Not initialized.')
        actual=await positions()
        if any(abs(actual[c][i]-plan['start'][c][i])>.1 for c in (1,2) for i in range(3)):
            raise RuntimeError('Start position changed.')
        definitions=to_jsonable(await motion.send_command(C.PrepGetTipAndNeedleDefinitions()))['definitions']
        if plan['stored_tip_definition'] not in definitions:raise RuntimeError('Stored tip definition changed.')
        scales=((await motion.send_command(C.PrepGetXSpeedScale())).value,(await motion.send_command(C.PrepGetZSpeedScale())).value)
        await motion.send_command(C.PrepMethodBegin(automatic_pause=True));began=True
        await motion.send_command(C.PrepSetXSpeedScale(value=2));await motion.send_command(C.PrepSetZSpeedScale(value=2))
        for step in plan['path']:
            await motion.send_command(C.PrepSetXSpeedScale(value=travel_scale if 'continuous' in step['phase'] else 2))
            await move(step['positions'])
        await motion.send_command(C.PrepSetXSpeedScale(value=2))
        if not plan.get('clearance_only'):
            await motion.send_command(C.PrepSetZSpeedScale(value=pickup_z_scale))
        for channel,opening in zip((1,2),[] if plan.get('clearance_only') else plan['selected']):
            x,y,rim=opening['exported_frame_xyz_mm']
            if channel==2:
                target=await positions()
                for p in target.values():p[0]=x
                target[channel][1]=y
                await move(target)
            loc=Coordinate(x,y,rim-tip.collar_height)
            params=C.TipPositionParameters.for_op(channel,loc,tip,z_seek_offset=seek_offset)
            b=(await bounds())[channel]
            if not b['z_min']<=params.z_position<params.z_seek<=b['z_max']:
                raise RuntimeError('Pickup seating/seek outside reported limits.')
            if abs(params.z_seek-(rim+5+seek_offset))>.001 or not 55<=rim<=80:
                raise RuntimeError('Pickup datum validation failed.')
            record('pickup_intent',{'channel':channel,'opening':opening,'seat_and_seek':to_jsonable(params),
                'seek_speed_mm_s':seek_speed,'pickup_z_scale':pickup_z_scale,'retry':False})
            await checked(C.PrepPickUpTipsById(tip_positions=[params],final_z=165.5,seek_speed=seek_speed,
                tip_definition_id=plan['stored_tip_definition']['id'],enable_tadm=False,
                dispenser_volume=0,dispenser_speed=250))
            held.add(channel)
            record('tip_sensor_confirmation',await asyncio.to_thread(check_tip_state,held))
            record('after_pickup',{'positions':await positions(),'bounds':await bounds(),
                'held_definition':to_jsonable(await motion.send_command(C.PrepGetTipDefinitionHeld()))})
        if plan.get('return_to_park') and not plan.get('clearance_only'):
            actual=await positions();limits=await bounds()
            high={c:[p[0],p[1],limits[c]['z_max']-.1] for c,p in actual.items()}
            await move(high)
            await motion.send_command(C.PrepSetXSpeedScale(value=travel_scale))
            await move({1:[289.30,344.99,high[1][2]],2:[289.30,365.01,high[2][2]]})
            record('returned_to_park_area',await positions())
        await motion.send_command(C.PrepSetXSpeedScale(value=scales[0]))
        await motion.send_command(C.PrepSetZSpeedScale(value=scales[1]))
        await motion.send_command(C.PrepMethodEnd());completed=True
        record('completed',{'confirmed_channels':sorted(held),'positions':await positions()})
    except BaseException as e:
        record('trial_stopped',{'error':str(e),'exception_type':type(e).__name__,
            'confirmed_channels':sorted(held),'no_retry':True})
        if began:
            await abort_once()
        raise
    finally:
        if began and not completed:record('speed_scales_not_restored_after_fault',{'previous':scales,'travel_x_scale':travel_scale,'pickup_x_z_scales':[2,pickup_z_scale]})
        try:await motion._close()
        finally:
            try:await abort._close()
            finally:await monitor._close()
        for path in ('service-software-api/sensor-status','service-software-api/has-tips','errors/check-for-pending-errors'):
            try:record('http_final',{path:await asyncio.to_thread(get,path)})
            except Exception as e:record('http_final_failed',str(e))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-authorized',action='store_true')
    parser.add_argument('--travel-x-scale',type=int,choices=range(2,11),default=2)
    parser.add_argument('--return-to-park',action='store_true')
    parser.add_argument('--seek-speed',type=float,default=15.0)
    parser.add_argument('--pickup-z-scale',type=int,choices=(1,2),default=2)
    parser.add_argument('--z-seek-offset',type=float,choices=(0.0,-1.0),default=0.0)
    args=parser.parse_args()
    folder=capture(['--capture'])
    subprocess.run([sys.executable,'-B',str(ROOT/'estimate_tip_plane.py'),'--root',str(folder)],check=True,capture_output=True)
    plan=prepare(folder)
    plan.update(travel_x_scale=args.travel_x_scale,return_to_park=args.return_to_park,
                seek_speed_mm_s=args.seek_speed,pickup_z_scale=args.pickup_z_scale,
                z_seek_offset_mm=args.z_seek_offset,seek_above_rim_mm=5+args.z_seek_offset)
    (folder/'pickup_plan.json').write_text(json.dumps(plan,indent=2))
    print('Pickup plan: '+str(folder/'pickup_plan.json'),flush=True)
    if args.execute_authorized:asyncio.run(execute(folder,plan))
