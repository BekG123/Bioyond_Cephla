"""One native ReleasePlate attempt on the inspected, supported site-4 plate.

Default read-only. No retreat, tool return, fault reset, or batch continuation.
"""
import argparse
import asyncio
import json
import time
from hamilton_dcg_transfer import C,PrepDriver,HamiltonTCPClient,Deck,HamiltonPrep,DoorClosed,to_jsonable,rest_ready
from retry_hamilton_dcg_coordinated import rows
from reseat_hamilton_coordinated_stop import PRIOR,SEAT_Z

EXPECTED={1:(54.04150772,84.72623444,SEAT_Z),2:(54.04150772,3.60774112,SEAT_Z)}

def preflight(feedback):
    current=rows(feedback)
    for c,p in current.items():
        if any(abs(p[k]-v)>.1 for k,v in zip(('position_x','position_y','position_z'),EXPECTED[c])):
            raise RuntimeError('Inspected seated position changed')
    return current

def validate_motion(start,current,bounds):
    limits={b['channel']:b for b in bounds}
    for c,p in current.items():
        if abs(p['position_x']-start[c]['position_x'])>.25 or abs(p['position_z']-start[c]['position_z'])>.25:
            raise RuntimeError('Native release moved X/Z instead of only opening jaws')
        outward=(p['position_y']-start[c]['position_y'])*(1 if c==1 else -1)
        if not -.1<=outward<=10.25:raise RuntimeError('Native release exceeded inspected outward-only opening corridor')
        if not limits[c]['y_min']<=p['position_y']<=limits[c]['y_max']:raise RuntimeError('Native release exceeded Y limits')

async def run(h,ticket,execute):
    reads={C.PrepGetPositions,C.PrepGetPlateHeld,C.PrepGetTipDefinitionHeld,C.PrepGetIsInitialized,C.PrepGetChannelBounds,DoorClosed,C.PrepGetIsEnclosurePresent}
    writes={C.PrepReleasePlate,C.PrepMethodBegin,C.PrepMethodEnd,C.PrepMethodAbort}
    class Driver(PrepDriver):
        async def setup(self,**kw):raise RuntimeError('Automatic setup prohibited')
        async def stop(self,**kw):raise RuntimeError('Transport close only')
        async def send_command(self,cmd,**kw):
            if type(cmd) not in reads|writes or (type(cmd) in writes and not execute):raise RuntimeError('Command prohibited')
            if type(cmd) in writes:h.journal(ticket,'native_release_request',dict(command=type(cmd).__name__,parameters=to_jsonable(cmd)))
            result=await super().send_command(cmd,**kw)
            if type(cmd) in writes:h.journal(ticket,'native_release_response',dict(command=type(cmd).__name__,result=to_jsonable(result)))
            return result
    def make():return Driver(deck=Deck(name='release_supported',size_x=300,size_y=430,size_z=200),io=HamiltonTCPClient(host='192.168.100.102',port=2000,read_timeout=10,write_timeout=5))
    motion,monitor,abort=make(),make(),make();began=False;abort_sent=False
    async def interlocks():
        for cls in (DoorClosed,C.PrepGetIsEnclosurePresent):
            if not (await monitor.send_command(cls(),read_timeout=2)).value:raise RuntimeError('Door/enclosure changed')
    async def measure():return to_jsonable(await monitor.send_command(C.PrepGetPositions(),read_timeout=2))
    async def stop():
        nonlocal abort_sent
        if not abort_sent:
            abort_sent=True
            await asyncio.wait_for(abort.send_command(C.PrepMethodAbort(),read_timeout=3),4)
    try:
        for d in (motion,monitor,abort):await asyncio.wait_for(d._open(),20)
        await interlocks();await asyncio.to_thread(rest_ready,h)
        if not (await motion.send_command(C.PrepGetIsInitialized())).value:raise RuntimeError('Not initialized; no reset performed')
        if not (await motion.send_command(C.PrepGetPlateHeld())).value:raise RuntimeError('Firmware held state changed')
        if to_jsonable(await motion.send_command(C.PrepGetTipDefinitionHeld()))['value'].get('label')!='DCG':raise RuntimeError('Expected DCG')
        method=await motion.request_method_by_name(C.PrepReleasePlate.firmware_path,'ReleasePlate')
        if (method.interface_id,method.method_id)!=(1,21) or method.to_dict()['params']:raise RuntimeError('Unexpected ReleasePlate signature')
        before=await measure();start=preflight(before)
        bounds=to_jsonable(await motion.send_command(C.PrepGetChannelBounds()))['bounds']
        validate_motion(start,start,bounds)
        print(json.dumps(dict(motion_sent=False,command='PrepReleasePlate',before=before,retreat=False)),flush=True)
        if not execute:return
        with (h.folder/PRIOR/'native_supported_release_attempt.json').open('x') as f:
            json.dump(dict(before=before,operator_confirmed_plate_supported=True,operator_request='try the release'),f)
        began=True;await motion.send_command(C.PrepMethodBegin(automatic_pause=True))
        preflight(await measure());await interlocks()
        pending=asyncio.create_task(motion.send_command(C.PrepReleasePlate(),read_timeout=10));last_guard=0
        try:
            while not pending.done():
                await asyncio.wait({pending},timeout=.05)
                feedback=await measure();h.journal(ticket,'native_release_sample',feedback)
                validate_motion(start,rows(feedback),bounds)
                if time.monotonic()-last_guard>.4:
                    await interlocks()
                    if await asyncio.to_thread(h.call,'GET','errors/check-for-pending-errors'):raise RuntimeError('Controller fault')
                    last_guard=time.monotonic()
            await pending
            for _ in range(5):
                feedback=await measure();h.journal(ticket,'native_release_settle_sample',feedback)
                validate_motion(start,rows(feedback),bounds);await asyncio.sleep(.1)
        except BaseException:
            try:await stop()
            finally:pending.cancel();await asyncio.gather(pending,return_exceptions=True)
            raise
        held=(await motion.send_command(C.PrepGetPlateHeld())).value
        if held:raise RuntimeError('Native release did not clear held state')
        await motion.send_command(C.PrepMethodEnd());began=False
        final=await measure();validate_motion(start,rows(final),bounds)
        opening={c:(rows(final)[c]['position_y']-start[c]['position_y'])*(1 if c==1 else -1) for c in (1,2)}
        result=dict(status='release_command_complete_awaiting_physical_inspection',final_positions=final,
            outward_per_jaw_mm=opening,firmware_plate_held=held,physical_release_verified=False,retreat=False,batch_resumed=False)
        h.journal(ticket,'native_release_result',result)
        (h.folder/PRIOR/'native_supported_release_result.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result),flush=True)
    except BaseException as error:
        if began:
            try:await stop()
            except BaseException as stop_error:h.journal(ticket,'native_release_abort_error',str(stop_error))
        if execute:
            try:
                after=await measure();h.journal(ticket,'native_release_stopped_positions',after)
            except BaseException:after=None
            result=dict(status='failed_or_uncertain',error=str(error),stopped_positions=after,retreat=False,batch_resumed=False)
            h.journal(ticket,'native_release_failed',result)
            (h.folder/PRIOR/'native_supported_release_result.json').write_text(json.dumps(result,indent=2))
        raise
    finally:
        for d in (motion,monitor,abort):await d._close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute-confirmed',action='store_true');args=p.parse_args()
    h=HamiltonPrep();rest_ready(h);ticket=json.loads((h.folder/'active.json').read_text())
    if ticket.get('request_id')!=PRIOR or ticket.get('status')!='failed_or_uncertain':raise RuntimeError('Wrong stopped batch')
    if args.execute_confirmed:
        lock=h.folder/'dcg48_execution.lock'
        with lock.open('x') as f:f.write(PRIOR)
        try:asyncio.run(run(h,ticket,True))
        finally:lock.unlink()
    else:asyncio.run(run(h,ticket,False))
