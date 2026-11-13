"""Empty-deck DCG characterization at Z150-177 mm; default offline preview.

The operator removes all plates. PickUpPlate in free space is used only to
compare firmware's recorded holding state, never as proof of physical pickup.
No faults are cleared, no failed command retried, no plate batch resumed.
"""
import argparse
import asyncio
import json
import math
from pathlib import Path
import time
from uuid import uuid4
from hamilton_dcg_transfer import C,PrepDriver,HamiltonTCPClient,Deck,HamiltonPrep,DoorClosed,PrepPickupDCG,PLAN,to_jsonable,rest_ready,xyz

PRIOR='dcg48_repeat_f358eb6148794cbb9f6f0957f386193a'
ROOT=Path(__file__).resolve().parent
X,Y=54.04006282697236,44.166698939616914
CLOSED_SPAN=81.11849331855774

def y_command(span):
    return C.PrepMoveYAbsolute(channels=[C.ChannelYPositionParameters(default_values=False,
        channel=c,y_position=Y+sign*span/2) for c,sign in ((1,1),(2,-1))],velocity=1)

def z_command(z):
    if not 150<=z<=160:raise ValueError('Diagnostic heights are restricted to 150-160 mm')
    return C.PrepMoveZAbsolute(channels=[C.ChannelZPositionParameters(default_values=False,channel=c,z_position=z) for c in (1,2)],velocity=1)

def reset_command():
    return C.PrepMoveToPosition(move_parameters=C.GantryMoveXYZParameters(default_values=False,gantry_x_position=X,
        axis_parameters=[C.ChannelYZMoveParameters(default_values=False,channel=c,
            y_position=Y+sign*(CLOSED_SPAN+20)/2,z_position=150) for c,sign in ((1,1),(2,-1))]))

def pickup_in_air():
    p=json.loads((ROOT/'reports/hamilton_api/plate_offset_20261108T112943Z/staged_transfer_plan.json').read_text())['profile']['plate']
    return C.PrepPickUpPlate(plate_top_center=xyz([X,Y,157]),plate=C.PlateDimensions(default_values=False,
        length=p['base_length_mm'],width=p['grip_body_width_mm'],height=p['height_mm']),clearance_y=4,
        grip_speed_y=1,grip_distance=3,grip_height=150)

def cases():
    result=[]
    for name in ('unheld','held','released_before_lift'):
        steps=[('reset',reset_command()),('close_in_air',y_command(CLOSED_SPAN) if name=='unheld' else pickup_in_air()),
               ('open_10mm',y_command(CLOSED_SPAN+20))]
        if name=='released_before_lift':steps.append(('release_at_150',C.PrepReleasePlate()))
        steps.extend([('slow_lift',z_command(160)),('safe_height',C.PrepMoveZUpToSafe(channels=[1,2]))])
        if name=='held':steps.append(('release_at_safe_height',C.PrepReleasePlate()))
        result.append((name,steps))
    return result

def analyze(samples):
    result=[]
    for group in sorted({s['phase'] for s in samples}):
        rows=[s for s in samples if s['phase']==group]
        first,last=rows[0],rows[-1]
        result.append(dict(phase=group,start_spacing_mm=first['spacing_mm'],end_spacing_mm=last['spacing_mm'],
            minimum_spacing_mm=min(s['spacing_mm'] for s in rows),start_y=first['y_mm'],end_y=last['y_mm'],
            first_spacing_change=next((s for s in rows if abs(s['spacing_mm']-first['spacing_mm'])>.2),None)))
    return result

async def run(h,ticket):
    reads={C.PrepGetPositions,C.PrepGetPlateHeld,C.PrepGetTipDefinitionHeld,C.PrepGetIsInitialized,
        C.PrepGetChannelBounds,C.PrepGetXSpeedScale,C.PrepGetZSpeedScale,C.PrepIsParked,DoorClosed,C.PrepGetIsEnclosurePresent}
    writes={PrepPickupDCG,C.PrepMoveZUpToSafe,C.PrepMoveToPosition,C.PrepMoveYAbsolute,C.PrepMoveZAbsolute,
        C.PrepPickUpPlate,C.PrepReleasePlate,C.PrepDropTool,C.PrepPark,C.PrepSetXSpeedScale,C.PrepSetZSpeedScale,
        C.PrepMethodBegin,C.PrepMethodEnd,C.PrepMethodAbort}
    class Driver(PrepDriver):
        async def setup(self,**kw):raise RuntimeError('Automatic setup prohibited')
        async def stop(self,**kw):raise RuntimeError('Transport close only')
        async def send_command(self,command,**kw):
            if type(command) not in reads|writes:raise RuntimeError('Unreviewed command')
            if type(command) in writes:h.journal(ticket,'native_request',dict(command=type(command).__name__,parameters=to_jsonable(command)))
            result=await super().send_command(command,**kw)
            if type(command) in writes:h.journal(ticket,'native_response',dict(command=type(command).__name__,response=to_jsonable(result)))
            return result
    def make():return Driver(deck=Deck(name='empty_characterization',size_x=300,size_y=430,size_z=200),
        io=HamiltonTCPClient(host='192.168.100.102',port=2000,read_timeout=45,write_timeout=5))
    motion,monitor,abort=make(),make(),make();began=False;samples=[]
    async def interlocks():
        for cmd in (DoorClosed(),C.PrepGetIsEnclosurePresent()):
            if not (await monitor.send_command(cmd,read_timeout=2)).value:raise RuntimeError('Door/enclosure interlock')
    async def sample(phase):
        feedback=to_jsonable(await monitor.send_command(C.PrepGetPositions(),read_timeout=2))
        rows=sorted(feedback['positions'],key=lambda p:p['channel'])
        if len(rows)!=2:raise RuntimeError('Unexpected channel feedback')
        for p in rows:
            if not all(math.isfinite(p[k]) for k in ('position_x','position_y','position_z')) or p['position_z']<140:
                raise RuntimeError('Empty diagnostic left high-clearance region')
        data=dict(phase=phase,at=time.time(),y_mm=[p['position_y'] for p in rows],z_mm=[p['position_z'] for p in rows],
            spacing_mm=rows[0]['position_y']-rows[1]['position_y'],positions=feedback)
        samples.append(data);h.journal(ticket,'diagnostic_sample',data)
    async def checked(cmd,phase=None):
        await interlocks();await asyncio.to_thread(rest_ready,h)
        print('Running '+(phase or type(cmd).__name__),flush=True)
        if phase:await sample(phase)
        task=asyncio.create_task(motion.send_command(cmd,read_timeout=45));deadline=time.monotonic()+50;last_guard=0
        try:
            while not task.done():
                await asyncio.wait({task},timeout=.1)
                if phase:await sample(phase)
                if time.monotonic()>deadline:raise TimeoutError('Diagnostic command timed out')
                if time.monotonic()-last_guard>.4:
                    await interlocks()
                    if await asyncio.to_thread(h.call,'GET','errors/check-for-pending-errors'):raise RuntimeError('Controller error')
                    last_guard=time.monotonic()
            await task
            if phase:
                for _ in range(10):await asyncio.sleep(.1);await sample(phase)
            await interlocks()
        except BaseException:
            task.cancel();await asyncio.gather(task,return_exceptions=True);raise
    try:
        for d in (motion,monitor,abort):await asyncio.wait_for(d._open(),20)
        all_cmd=[PrepPickupDCG(**PLAN['pickup_dcg']),reset_command(),pickup_in_air(),y_command(CLOSED_SPAN),z_command(160),C.PrepMoveZUpToSafe(channels=[1,2]),C.PrepReleasePlate(),C.PrepDropTool(),C.PrepPark()]
        names=['PickupDCG','MoveToPosition','PickupPlate','MoveYAbsolute','MoveZAbsolute','MoveZUpToSafe','ReleasePlate','DropTool','Park']
        for cmd,name in zip(all_cmd,names):
            method=await motion.request_method_by_name(cmd.firmware_path,name)
            if (method.interface_id,method.method_id)!=(1,cmd.command_id):raise RuntimeError('Firmware signature changed: '+name)
        if not (await motion.send_command(C.PrepIsParked())).value or (await motion.send_command(C.PrepGetPlateHeld())).value:
            raise RuntimeError('Must start parked without held plate')
        tool=to_jsonable(await motion.send_command(C.PrepGetTipDefinitionHeld()))['value']
        if tool.get('is_tool'):raise RuntimeError('Tool must start docked')
        scales=[(await motion.send_command(C.PrepGetXSpeedScale())).value,(await motion.send_command(C.PrepGetZSpeedScale())).value]
        began=True;await checked(C.PrepMethodBegin(automatic_pause=True))
        await checked(C.PrepSetXSpeedScale(value=5));await checked(C.PrepSetZSpeedScale(value=5))
        await checked(PrepPickupDCG(**PLAN['pickup_dcg']));await checked(C.PrepMoveZUpToSafe(channels=[1,2]))
        bounds=to_jsonable(await motion.send_command(C.PrepGetChannelBounds()))['bounds']
        for b in bounds:
            sign=1 if b['channel']==1 else -1
            if not b['x_min']<=X<=b['x_max'] or not b['y_min']<=Y+sign*(CLOSED_SPAN+20)/2<=b['y_max'] or not b['z_min']<=150<160<=b['z_max']:
                raise RuntimeError('Diagnostic exceeds native bounds')
        for name,steps in cases():
            for label,cmd in steps:
                await checked(cmd,name+'/'+label)
                held=(await motion.send_command(C.PrepGetPlateHeld())).value
                h.journal(ticket,'held_state',dict(phase=name+'/'+label,value=held,physical_plate_present=False))
                if label=='close_in_air' and held!=(name!='unheld'):raise RuntimeError('Unexpected recorded holding state')
                if label.startswith('release') and held:raise RuntimeError('Native release did not clear held state')
            if (await motion.send_command(C.PrepGetPlateHeld())).value:raise RuntimeError('Case ended with held state')
        await checked(C.PrepDropTool());await checked(C.PrepPark())
        if not (await motion.send_command(C.PrepIsParked())).value or to_jsonable(await motion.send_command(C.PrepGetTipDefinitionHeld()))['value'].get('is_tool'):
            raise RuntimeError('Final park/tool verification failed')
        await checked(C.PrepSetXSpeedScale(value=scales[0]));await checked(C.PrepSetZSpeedScale(value=scales[1]))
        await checked(C.PrepMethodEnd());began=False
        result=dict(status='completed',physical_plate_present=False,parked=True,phases=analyze(samples))
        (h.folder/ticket['request_id']/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        h.journal(ticket,'outcome',result);print(json.dumps(result,indent=2),flush=True)
    except BaseException as error:
        if began:
            try:await asyncio.wait_for(abort.send_command(C.PrepMethodAbort(),read_timeout=5),7)
            except BaseException as e:h.journal(ticket,'abort_failed',str(e))
        h.journal(ticket,'outcome',dict(status='failed_or_uncertain',error=str(error),phases=analyze(samples)));raise
    finally:
        for d in (motion,monitor,abort):await d._close()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute-empty-deck-confirmed',action='store_true');args=p.parse_args()
    for _,steps in cases():
        for _,cmd in steps:cmd.build_parameters().build()
    if not args.execute_empty_deck_confirmed:
        print(json.dumps(dict(motion_sent=False,cases=[dict(case=n,steps=[label for label,_ in s]) for n,s in cases()],x=X,y=Y,test_z_mm=[150,160],outward_per_jaw_mm=10),indent=2));return
    h=HamiltonPrep();rest_ready(h,initial=True);marker=h.folder/'active.json';prior=json.loads(marker.read_text())
    if prior.get('request_id')!=PRIOR or prior.get('status')!='failed_or_uncertain':raise RuntimeError('Wrong stopped run')
    ticket=dict(request_id='dcg_empty_diagnosis_'+uuid4().hex,prior_request_id=PRIOR,
        operator_confirmation='Plate removed; tool docked; deck/path clear; door closed; hands clear; E-stop supervised')
    lock=h.folder/'dcg48_execution.lock'
    with lock.open('x',encoding='utf-8') as f:f.write(ticket['request_id'])
    try:
        with (h.folder/PRIOR/'empty_characterization_attempt.json').open('x',encoding='utf-8') as f:json.dump(ticket,f)
        h.journal(ticket,'begin',ticket);print('Diagnostic request: '+ticket['request_id'],flush=True);asyncio.run(run(h,ticket))
    finally:lock.unlink()

if __name__=='__main__':main()
