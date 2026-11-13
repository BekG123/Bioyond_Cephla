"""One supervised PRPGJ2494 site-4 to site-3 transfer using native DCG.

Default is offline packet/geometry verification. --execute-confirmed is physical.
Parameters originate in Hamilton simulator job ca4bd00e-558c-44c9-8b64-8aec4ccfefdf.
The virtual magnet destination is deliberately replaced by the actual flat site's
height; no virtual terrain map is loaded into the real controller.
"""
import argparse
import asyncio
from dataclasses import dataclass
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'tmp/prep-jog-audit'
PIN = 'fc5ae129c39ef645a2a11234dce97f933a317a9c'
if subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip() != PIN:
    raise RuntimeError('Review changed Hamilton toolkit')
sys.path.insert(0, str(SOURCE))
from pylabrobot.hamilton.prep.driver.master import PrepDriver
from pylabrobot.hamilton.prep.driver import prep_commands as C
from pylabrobot.hamilton.prep.driver.configuration import to_jsonable
from pylabrobot.hamilton.transport.tcp.tcp import HamiltonTCPClient
from pylabrobot.resources import Deck
from hamilton_prep import HamiltonPrep

SERIAL = 'PRPGJ2494'
PIP = 'MLPrepRoot.PipettorRoot.Pipettor'
PLAN = dict(serial=SERIAL, source_site=4, destination_site=3, labware_id=226,
    source_top_mm=[62.1, 44.63, 18.3], destination_top_mm=[62.1, 139.83, 18.3],
    plate_dimensions_mm=[127.63, 81.71, 14.3], grip_height_mm=11.3,
    clearance_y_mm=4.0, grip_distance_mm=3.0, grip_speed_mm_s=10.0,
    loaded_traverse_top_z_mm=160.0, x_z_speed_scale=20,
    destination_acceleration_scale=20,
    pickup_dcg=dict(channel=1, x=289.41, z=21.25, y=295.8,
                    seek=51.25, x_radius=17.85, y_radius=2.5))

@dataclass(frozen=True)
class PrepPickupDCG(C.PrepCommand[None]):
    command_id = 45
    firmware_path = PIP
    channel: int
    x: float
    z: float
    y: float
    seek: float
    x_radius: float
    y_radius: float

    def build_parameters(self):
        p = C.HoiParams().add(self.channel, C.WEnum)
        for v in (self.x, self.z, self.y, self.seek, self.x_radius, self.y_radius):
            p.add(v, C.F32)
        return p

    @classmethod
    def parse_response_parameters(cls, data):
        return None

class DoorClosed(C.PrepGetIsEnclosurePresent):
    command_id = 22

class PlateChecking(C.PrepGetPlateHeld):
    command_id = 47

def xyz(p):
    return C.XYZCoord(default_values=False, x_position=p[0], y_position=p[1], z_position=p[2])

def commands():
    p = PLAN
    return [PrepPickupDCG(**p['pickup_dcg']),
        C.PrepPickUpPlate(plate_top_center=xyz(p['source_top_mm']),
            plate=C.PlateDimensions(default_values=False, length=p['plate_dimensions_mm'][0],
                width=p['plate_dimensions_mm'][1], height=p['plate_dimensions_mm'][2]),
            clearance_y=p['clearance_y_mm'], grip_speed_y=p['grip_speed_mm_s'],
            grip_distance=p['grip_distance_mm'], grip_height=p['grip_height_mm']),
        C.PrepMovePlate(plate_top_center=xyz([*p['source_top_mm'][:2],160.0]), acceleration_scale_x=20),
        C.PrepMovePlate(plate_top_center=xyz([*p['destination_top_mm'][:2],160.0]), acceleration_scale_x=20),
        C.PrepDropPlate(plate_top_center=xyz(p['destination_top_mm']), clearance_y=4.0, acceleration_scale_x=20),
        C.PrepDropTool()]

def offline_check():
    d = PLAN['destination_top_mm']; s = PLAN['source_top_mm']
    assert abs(d[1]-s[1]-95.2)<1e-8 and d[0]==s[0] and d[2]==s[2]==18.3
    assert d[2] != 45.87, 'Virtual magnet height must not be used'
    encoded = commands()[0].build_parameters().build()
    decoded = C.HoiParamsParser(encoded).parse_all()
    expected = [1,289.41,21.25,295.8,51.25,17.85,2.5]
    assert len(decoded)==7
    assert all(abs(float(v)-e)<.0001 for (_,v),e in zip(decoded,expected))
    # Compare wire layout against the actual controller's introspection report.
    evidence = json.loads((ROOT/'reports/hamilton_api/transfer_inspection_20261108T103525584334Z.json').read_text())
    signature = evidence['gripper_method_signatures'][PIP+'.PickupDCG']
    assert signature['method_id']==45 and signature['interface_id']==1
    assert signature['parameter_labels']==['channel1Index','toolPositionX','toolPositionZ',
        'channel1PositionY','toolSeek','toolXRadius','toolYRadius']
    assert evidence['dcg_channel_enum']['values']['SingleChannel1']==1
    # Introspection uses type 38 for a float parameter; the encoded data
    # fragment uses HamiltonDataType.F32 (40), as in the pinned wire codec.
    assert [int(t) for t,_ in decoded] == [32]+[40]*6
    return dict(ok=True, motion_sent=False, plan=PLAN, commands=[type(c).__name__ for c in commands()])

def rest_ready(h, initial=False):
    state = h.status(fresh=True)
    if not state['connected'] or state['serial']!=SERIAL or not state['initialized']:
        raise RuntimeError('Hamilton identity/connection/initialization changed')
    if state['pending_errors'] or state['global_state']!='Idle' or state['run'].get('isRunInProgress'):
        raise RuntimeError('Hamilton busy or faulted')
    cfg=h.call('GET','instruments')
    if cfg.get('isFakeInstrument') or cfg.get('endpoint')!='192.168.100.102':
        raise RuntimeError('Real controller connection required')
    sensors=h.call('GET','service-software-api/sensor-status')
    if sensors.get('isDoorClosed') is not True or sensors.get('isEnclosurePresent') is not True:
        raise RuntimeError('Door/enclosure must remain closed')
    verification=h.call('GET','verification/status')
    if any(verification.get(k) for k in ('isWorkflowInProgress','isRunInProgress','isServiceRoutineInProgress')):
        raise RuntimeError('Concurrent Hamilton workflow')
    if initial and h.call('GET','service-software-api/has-tips') is not False:
        raise RuntimeError('Channels must be empty before tool pickup')
    return state

def check_scan(h, completed=False):
    scan=h.call('GET','deck/scan/3')
    by={x['positionId']:x for x in scan}
    occupied, empty = (3,4) if completed else (4,3)
    if by[empty].get('isOccupied') or not by[occupied].get('isOccupied'):
        raise RuntimeError('Plate source/destination occupancy not confirmed')
    matches=by[occupied].get('matches') or [by[occupied]]
    if not any(x.get('detectedLabwareId')==226 and x.get('confidence',0)>=.80 for x in matches):
        raise RuntimeError('Falcon plate identity not confirmed by scan')
    if not completed:
        # The classifier accepted a 48-well plate as labware 226 in trial
        # 1d9c35bc. Class confidence alone must never authorize this geometry.
        import cv2
        import numpy as np
        from hamilton_plate_offset import detect_grid, check_rim, FALCON96, OffsetError
        raw=h.call('GET','camera/position/4/15/14.3',binary=True)
        gray=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_GRAYSCALE)
        try:
            measured=detect_grid(gray,FALCON96)
        except OffsetError as error:
            raise RuntimeError('Plate well layout does not match the 96-well transfer definition. '
                               'Use the 48-well offset preview and review its gripping geometry before motion.') from error
        rim=check_rim(gray,measured,FALCON96)
        if (not rim['accepted'] or np.linalg.norm(measured['offset_plate_axes_mm'])>.5
                or abs(measured['angle_crop_deg'])>.5):
            raise RuntimeError('Plate is not verified at the nominal pickup pose. '
                               'Review the camera offset; this legacy transfer does not apply corrections.')
    return scan

async def execute(h,ticket,dry_run=False):
    read_types={C.PrepGetIsInitialized,C.PrepGetPositions,C.PrepGetChannelBounds,
        C.PrepGetDeckSiteDefinitions,C.PrepGetPlateHeld,C.PrepGetTipDefinitionHeld,
        C.PrepGetXSpeedScale,C.PrepGetZSpeedScale,DoorClosed,C.PrepGetIsEnclosurePresent,PlateChecking}
    write_types={PrepPickupDCG,C.PrepPickUpPlate,C.PrepMovePlate,C.PrepDropPlate,C.PrepDropTool,
        C.PrepMethodBegin,C.PrepMethodEnd,C.PrepMethodAbort,C.PrepSetXSpeedScale,C.PrepSetZSpeedScale}
    class Driver(PrepDriver):
        async def setup(self,**kwargs):raise RuntimeError('Automatic initialization disabled')
        async def stop(self,**kwargs):raise RuntimeError('Automatic motion on close disabled')
        async def send_command(self,command,**kwargs):
            if type(command) not in read_types|write_types:raise RuntimeError('Command not allowed')
            if dry_run and type(command) in write_types:raise RuntimeError('Read-only inspection cannot write')
            if type(command) in write_types:
                ticket['write_attempted']=True
                h.journal(ticket,'native_request',dict(command=type(command).__name__,parameters=to_jsonable(command)))
            result=await super().send_command(command,**kwargs)
            if type(command) in write_types:h.journal(ticket,'native_response',dict(command=type(command).__name__,response=to_jsonable(result)))
            return result
    def make():
        return Driver(deck=Deck(name='dcg_transfer',size_x=300,size_y=430,size_z=200),
            io=HamiltonTCPClient(host='192.168.100.102',port=2000,read_timeout=60,write_timeout=5))
    motion,monitor,abort=make(),make(),make()
    began=False
    async def interlocks():
        if not (await monitor.send_command(DoorClosed(),read_timeout=2)).value:
            raise RuntimeError('Door opened')
        if not (await monitor.send_command(C.PrepGetIsEnclosurePresent(),read_timeout=2)).value:
            raise RuntimeError('Enclosure not present')
    async def checked(command):
        await interlocks()
        await asyncio.to_thread(rest_ready,h)
        pending=asyncio.create_task(motion.send_command(command,read_timeout=60))
        try:
            deadline=time.monotonic()+65
            while not pending.done():
                await asyncio.wait({pending},timeout=.25)
                if pending.done():break
                await interlocks()
                if time.monotonic()>deadline:raise TimeoutError('Native motion timed out')
                if await asyncio.to_thread(h.call,'GET','errors/check-for-pending-errors'):
                    raise RuntimeError('Hamilton reported an error')
            return await pending
        except BaseException:
            pending.cancel()
            await asyncio.gather(pending,return_exceptions=True)
            raise
    try:
        for driver in (motion,monitor,abort):await asyncio.wait_for(driver._open(),20)
        for name,expected in (('PickupDCG',45),('PickupPlate',17),('DropPlate',18),('DropTool',16)):
            m=await motion.request_method_by_name(PIP,name)
            if m.interface_id!=1 or m.method_id!=expected:raise RuntimeError('Firmware signature changed')
        method=await motion.request_method_by_name('MLPrepRoot.MLPrep','GetIsDoorClosed')
        if (method.interface_id,method.method_id)!=(1,22):raise RuntimeError('Door method changed')
        await interlocks()
        if not (await motion.send_command(C.PrepGetIsInitialized())).value:
            raise RuntimeError('Not initialized')
        if (await motion.send_command(C.PrepGetPlateHeld())).value:
            raise RuntimeError('Controller already records a held plate')
        presence_checking=(await motion.send_command(PlateChecking())).value
        h.journal(ticket,'native_presence_configuration',dict(enabled=presence_checking,
            changed=False,held_state_is_not_physical_proof=True,
            verification='Operator-supervised trial plus before/after camera occupancy'))
        # Verify actual physical flat sites, not the simulated magnet terrain.
        sites={v.id:v for v in (await motion.send_command(C.PrepGetDeckSiteDefinitions())).sites}
        for sid,y in ((6,1.4),(0,96.6)):
            v=sites[sid]
            if abs(v.left_bottom_front_x+2.28)>.02 or abs(v.left_bottom_front_y-y)>.02 or abs(v.left_bottom_front_z-4)>.02:
                raise RuntimeError('Physical site geometry changed')
        scales=((await motion.send_command(C.PrepGetXSpeedScale())).value,
                (await motion.send_command(C.PrepGetZSpeedScale())).value)
        bounds={v.channel:v for v in (await motion.send_command(C.PrepGetChannelBounds())).bounds}
        # Channel 1 is rear (+Y), channel 2 front (-Y), corroborated by
        # the measured parked positions on this instrument.
        for p in (PLAN['source_top_mm'],PLAN['destination_top_mm']):
            half=(PLAN['plate_dimensions_mm'][1]+2*PLAN['clearance_y_mm']+3.97)/2
            for channel,sign in ((1,1),(2,-1)):
                b=bounds[channel]
                if not (b.x_min<=p[0]<=b.x_max and b.y_min<=p[1]+sign*half<=b.y_max
                        and b.z_min<=PLAN['grip_height_mm']<=b.z_max
                        and b.z_min<=160<=b.z_max):
                    raise RuntimeError('Proposed plate handling exceeds measured channel bounds')
        h.journal(ticket,'initial_native',dict(positions=to_jsonable(await motion.send_command(C.PrepGetPositions())),
            bounds=to_jsonable(await motion.send_command(C.PrepGetChannelBounds())),scales=scales))
        if dry_run:
            print('READ-ONLY PREFLIGHT PASSED; no commands executed',flush=True)
            return
        await checked(C.PrepMethodBegin(automatic_pause=True));began=True
        await checked(C.PrepSetXSpeedScale(value=20))
        await checked(C.PrepSetZSpeedScale(value=20))
        for index,command in enumerate(commands()):
            print('Running '+type(command).__name__,flush=True)
            await checked(command)
            held=(await motion.send_command(C.PrepGetPlateHeld())).value
            tool=to_jsonable(await motion.send_command(C.PrepGetTipDefinitionHeld()))
            h.journal(ticket,'stage_verified',dict(stage=index,held=held,tool=tool,
                positions=to_jsonable(await motion.send_command(C.PrepGetPositions()))))
            if index==0 and tool['value'].get('is_tool') is not True:
                raise RuntimeError('Tool pickup not confirmed')
            if index in (1,2,3) and held is not True:raise RuntimeError('Held-plate state lost')
            if index in (4,5) and held is not False:raise RuntimeError('Release not confirmed')
            if index==5 and tool['value'].get('is_tool'):raise RuntimeError('Tool return not confirmed')
        await checked(C.PrepSetXSpeedScale(value=scales[0]))
        await checked(C.PrepSetZSpeedScale(value=scales[1]))
        await checked(C.PrepMethodEnd());began=False
    except BaseException:
        if began:
            try:await asyncio.wait_for(abort.send_command(C.PrepMethodAbort(),read_timeout=5),7)
            except BaseException as e:h.journal(ticket,'abort_failed',str(e))
        raise
    finally:
        for driver in (motion,monitor,abort):await driver._close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute-confirmed',action='store_true')
    p.add_argument('--preflight',action='store_true',help='Read-only native validation; no motion')
    args=p.parse_args()
    check=offline_check()
    if not args.execute_confirmed and not args.preflight:
        print(json.dumps(check,indent=2));return
    h=HamiltonPrep();h.preflight(initialized=True);rest_ready(h,initial=True)
    if args.preflight:
        if args.execute_confirmed:raise RuntimeError('Select only one mode')
        ticket=dict(request_id='dcg_preflight_'+str(time.time_ns()))
        h.journal(ticket,'plan',check)
        h.journal(ticket,'deck_before',check_scan(h))
        asyncio.run(execute(h,ticket,dry_run=True))
        return
    with h.owned('native_dcg_site4_to_site3') as ticket:
        h.journal(ticket,'plan',check)
        h.journal(ticket,'deck_before',check_scan(h))
        asyncio.run(execute(h,ticket))
        h.journal(ticket,'deck_after',check_scan(h,completed=True))
        rest_ready(h)
        ticket['status']='completed'
        h.journal(ticket,'outcome',dict(status='completed',source_site=4,destination_site=3))
        print('TRANSFER COMPLETED '+ticket['request_id'],flush=True)

if __name__=='__main__':main()
