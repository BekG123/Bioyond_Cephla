"""One explicitly authorized, high-clearance camera alignment trial; never pickup.

Original door/enclosure required. Only standard coordinated motion is allowed.
No initialization, raw drive motion, calibration, interlock override or replay.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from urllib.request import ProxyHandler, build_opener

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parents[1]))
from hamilton_hover_alignment import plan_hover, validate_target
from probe_prep_coordinates import main as capture, SOURCE, PIN, BASE

OPENER=build_opener(ProxyHandler({}))


def get(path):
    with OPENER.open(BASE+path,timeout=4) as response:
        raw=response.read()
    return json.loads(raw) if raw else None


def preflight():
    result={p:get(p) for p in ('instruments/connection-info','instruments/global-run-state',
        'service-software-api/sensor-status','service-software-api/has-tips',
        'errors/check-for-pending-errors','protocol-run','verification/status')}
    sensor=result['service-software-api/sensor-status']
    if sensor.get('isDoorClosed') is not True or sensor.get('isEnclosurePresent') is not True:
        raise RuntimeError('Original door/enclosure not confirmed closed and present.')
    if not all(s in result['instruments/connection-info'] for s in ('Serial Number: PRPGD2427','Initialization Status: Initialized')):
        raise RuntimeError('Instrument identity/initialization differs.')
    if result['instruments/global-run-state']!='Idle' or result['errors/check-for-pending-errors'] or result['service-software-api/has-tips'] is not False:
        raise RuntimeError('Instrument is busy, has errors or carries tips.')
    if result['protocol-run'].get('isRunInProgress') or any(result['verification/status'].get(k) for k in ('isWorkflowInProgress','isRunInProgress','isServiceRoutineInProgress')):
        raise RuntimeError('Another workflow owns the instrument.')
    return result


def fixed_post_check(folder,probe):
    d=json.loads((folder/'deck-calibration.json').read_text())
    k=np.array(d['CameraCalibration']['CameraMatrix']['Data'],float)
    dist=np.array(d['CameraCalibration']['DistortionCoefficients']['Data'],float)
    rotation=np.array(d['Rotation']['Data'],float)
    translation=np.array(d['Translation']['Data'],float)
    sites=probe['tcp_queries']['PrepGetCalibrationSiteDefinitions']['sites']
    if len(sites)!=1 or sites[0]['post'] is not True:
        raise RuntimeError('Expected one fixed calibration post.')
    s=sites[0]
    x,y,z=s['left_bottom_front_x'],s['left_bottom_front_y'],s['height']
    corners=np.array([[x,y,z],[x+s['length'],y,z],[x+s['length'],y+s['width'],z],[x,y+s['width'],z]])
    uv=cv2.projectPoints(corners,cv2.Rodrigues(rotation)[0],translation,k,dist)[0].reshape(-1,2)
    expected=uv.mean(axis=0)
    scale=np.linalg.norm(uv[1]-uv[0])/s['length']
    gray=cv2.imread(str(folder/'raw_current.png'),0)
    origin=np.round(expected).astype(int)-35
    if min(origin)<0 or origin[0]+71>gray.shape[1] or origin[1]+71>gray.shape[0]:
        raise RuntimeError('Calibration post projection is outside image.')
    roi=gray[origin[1]:origin[1]+71,origin[0]:origin[0]+71]
    n,labels,stats,centers=cv2.connectedComponentsWithStats((roi>245).astype(np.uint8))
    candidates=[i for i in range(1,n) if 600<stats[i,4]<2200 and 25<=stats[i,2]<=55 and 25<=stats[i,3]<=55]
    if len(candidates)!=1:
        raise RuntimeError('Fixed post is not uniquely visible; no motion.')
    observed=centers[candidates[0]]+origin
    error=float(np.linalg.norm(observed-expected)/scale)
    preview=cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR)
    cv2.polylines(preview,[np.int32(uv)],True,(0,0,255),2)
    cv2.circle(preview,tuple(np.round(observed).astype(int)),3,(0,255,0),-1)
    center=np.round(expected).astype(int)
    cv2.imwrite(str(folder/'fixed_post_check.png'),preview[center[1]-100:center[1]+100,center[0]-100:center[0]+100])
    evidence={'expected_pixel':expected.tolist(),'observed_bright_post_centroid':observed.tolist(),
              'error_mm':error,'purpose':'Approximate frame check for high-clearance trial, not contact calibration'}
    (folder/'fixed_post_check.json').write_text(json.dumps(evidence,indent=2))
    return error


async def execute(folder,plan):
    if subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip()!=PIN:
        raise RuntimeError('Driver source revision changed.')
    sys.path.insert(0,str(SOURCE))
    from pylabrobot.hamilton.prep.driver.master import PrepDriver
    from pylabrobot.hamilton.prep.driver import prep_commands as C
    from pylabrobot.hamilton.prep.driver.configuration import to_jsonable
    from pylabrobot.hamilton.transport.tcp.tcp import HamiltonTCPClient
    from pylabrobot.resources.deck import Deck
    read_types={C.PrepGetPositions,C.PrepGetChannelBounds,C.PrepGetIsInitialized,C.PrepGetXSpeedScale,C.PrepGetZSpeedScale}
    allowed=read_types|{C.PrepMoveToPosition,C.PrepSetXSpeedScale,C.PrepSetZSpeedScale,C.PrepMethodBegin,C.PrepMethodEnd,C.PrepMethodAbort}
    journal=folder/'hover_journal.jsonl'
    def record(kind,data):
        row={'time':datetime.now(timezone.utc).isoformat(),'kind':kind,'data':data}
        with journal.open('a') as out:out.write(json.dumps(row)+'\n')
        if kind not in ('command','response','monitor'):
            print(json.dumps(row),flush=True)
    class TrialDriver(PrepDriver):
        async def send_command(self,command,**kwargs):
            if type(command) not in allowed:raise RuntimeError('Command outside hover-trial allowlist.')
            record('command',{'name':type(command).__name__,'parameters':to_jsonable(command)})
            result=await super().send_command(command,**kwargs)
            record('response',{'name':type(command).__name__,'result':to_jsonable(result)})
            return result
        async def setup(self,**kwargs):raise RuntimeError('High-level setup is disabled.')
        async def stop(self,**kwargs):raise RuntimeError('High-level stop is disabled; it can move.')
    def driver():
        link=HamiltonTCPClient(host='192.168.100.102',port=2000,read_timeout=10,write_timeout=4)
        return TrialDriver(deck=Deck(name='trial',size_x=300,size_y=400,size_z=200),io=link)
    motion,abort=driver(),driver()
    completed=False
    began=False
    changed=False
    scales=None
    async def positions():
        return {int(p.channel):[p.position_x,p.position_y,p.position_z] for p in (await motion.send_command(C.PrepGetPositions())).positions}
    async def checked_move(target):
        # A separate HTTP sensor reader and separate TCP abort connection remain
        # available while the motion session waits for its terminal response.
        params=C.GantryMoveXYZParameters(default_values=False,gantry_x_position=target[1][0],
            axis_parameters=[C.ChannelYZMoveParameters(default_values=False,channel=c,y_position=target[c][1],z_position=target[c][2]) for c in (1,2)])
        pending=asyncio.create_task(motion.send_command(C.PrepMoveToPosition(move_parameters=params),read_timeout=10))
        try:
            while not pending.done():
                await asyncio.wait({pending},timeout=.2)
                if pending.done():break
                sensors=await asyncio.to_thread(get,'service-software-api/sensor-status')
                record('monitor',sensors)
                if sensors.get('isDoorClosed') is not True or sensors.get('isEnclosurePresent') is not True:
                    raise RuntimeError('Door/enclosure changed during motion.')
            await pending
        except BaseException:
            try:await asyncio.wait_for(abort.send_command(C.PrepMethodAbort()),5)
            except BaseException as error:record('abort_failed',str(error))
            pending.cancel()
            await asyncio.gather(pending,return_exceptions=True)
            raise
    try:
        record('preflight',await asyncio.to_thread(preflight))
        await motion._open()
        await abort._open()
        if not (await motion.send_command(C.PrepGetIsInitialized())).value:raise RuntimeError('Controller uninitialized.')
        actual=await positions()
        if any(abs(actual[c][i]-plan['start_positions'][str(c)][i])>.1 for c in (1,2) for i in range(3)):
            raise RuntimeError('Start position changed after planning.')
        bounds={int(b.channel):to_jsonable(b) for b in (await motion.send_command(C.PrepGetChannelBounds())).bounds}
        for step in plan['path']:validate_target(step['positions'],bounds)
        scales=((await motion.send_command(C.PrepGetXSpeedScale())).value,(await motion.send_command(C.PrepGetZSpeedScale())).value)
        record('saved_speed_scales',scales)
        await motion.send_command(C.PrepMethodBegin(automatic_pause=True))
        began=True
        changed=True
        await motion.send_command(C.PrepSetXSpeedScale(value=2))
        await motion.send_command(C.PrepSetZSpeedScale(value=2))
        for number,step in enumerate(plan['path']):
            await asyncio.to_thread(preflight)
            if (datetime.now(timezone.utc)-datetime.fromisoformat(plan['capture_time'])).total_seconds()>180:
                raise RuntimeError('Camera capture expired during trial.')
            record('move_intent',{'step':number,'phase':step['phase'],'target':step['positions']})
            await checked_move(step['positions'])
            actual=await positions()
            record('position_readback',actual)
            if set(actual)!={1,2} or any(abs(actual[c][i]-step['positions'][c][i])>.2 for c in (1,2) for i in range(3)):
                raise RuntimeError('Position readback differs from command; no next step.')
        completed=True
    except BaseException as error:
        record('trial_stopped',{'error':str(error),'no_retry':True})
        if began:
            try:await asyncio.wait_for(abort.send_command(C.PrepMethodAbort()),5)
            except BaseException as failure:record('abort_failed',str(failure))
        raise
    finally:
        # Restore only on a clean, fully observed completion. Unknown motion
        # outcomes must not be followed by more commands on the same session.
        try:
            if completed and changed:
                await motion.send_command(C.PrepSetXSpeedScale(value=scales[0]))
                await motion.send_command(C.PrepSetZSpeedScale(value=scales[1]))
                await motion.send_command(C.PrepMethodEnd())
                record('completed',{'pickup':False,'position':await positions()})
            elif changed:record('speed_scales_not_restored_after_fault',{'previous':scales,'requested_trial_scales':[2,2]})
        finally:
            try:await motion._close()
            finally:await abort._close()
            try:record('http_final',await asyncio.to_thread(preflight))
            except Exception as error:record('http_final_check_failed',str(error))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-authorized',action='store_true')
    args=parser.parse_args()
    folder=capture(['--capture'])
    subprocess.run([sys.executable,'-B',str(ROOT/'estimate_tip_plane.py'),'--root',str(folder)],check=True,capture_output=True)
    probe=json.loads((folder/'probe.json').read_text())
    estimate=json.loads((folder/'tip_plane_estimate.json').read_text())
    if estimate['tip_rims_used']<50 or estimate['pose_reprojection_rms_pixels']>2 or estimate['crop_registration_rms_pixels']>.7:
        raise RuntimeError('Vision quality failed; no motion.')
    visible={(p['column'],p['row']):p for p in estimate['grid_points'] if p['observed']}
    selected=None
    for col in (5,4,6):
        for rows in ((2,5),(1,4),(3,6),(2,4),(3,5)):
            if all((col,row) in visible for row in rows):
                selected=[visible[col,row] for row in rows]
                break
        if selected:break
    if selected is None:raise RuntimeError('No well-separated observed central pair; no motion.')
    candidates=[p['exported_frame_xyz_mm'] for p in selected]
    q=probe['tcp_queries']
    start={p['channel']:[p['position_x'],p['position_y'],p['position_z']] for p in q['PrepGetPositions']['positions']}
    bounds={b['channel']:b for b in q['PrepGetChannelBounds']['bounds']}
    plan=plan_hover(start,bounds,candidates,fixed_post_check(folder,probe))
    plan['start_positions']={str(c):p for c,p in start.items()}
    plan['capture_time']=probe['time_utc']
    plan['selected_image_grid_openings']=selected
    plan['user_authorization']='User requested camera-based alignment above site-4 tips; no contact/pickup in this trial.'
    (folder/'hover_plan.json').write_text(json.dumps(plan,indent=2))
    print('Prepared hover plan: '+str(folder/'hover_plan.json'),flush=True)
    if args.execute_authorized:asyncio.run(execute(folder,plan))


if __name__=='__main__':main()
