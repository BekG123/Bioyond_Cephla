"""Bounded Z-only recovery; default read-only. Never opens jaws or resumes cycles."""
import argparse
import asyncio
import json
import time
from hamilton_dcg_transfer import C,PrepDriver,HamiltonTCPClient,Deck,HamiltonPrep,DoorClosed,to_jsonable,rest_ready
from retry_hamilton_dcg_coordinated import rows,corridor

PRIOR='dcg48_repeat_683af88d0e764de8b7a8617903ffd172'
EXPECTED={1:(54.04150772,84.72623444,19.17427635),2:(54.04150772,3.60774112,19.50908852)}
SEAT_Z=17.18999934

def plan(feedback):
    start=rows(feedback)
    for c,p in start.items():
        if any(abs(p[k]-v)>.10 for k,v in zip(('position_x','position_y','position_z'),EXPECTED[c])):
            raise RuntimeError('Stopped pose changed; review recovery again')
        if not 0<p['position_z']-SEAT_Z<3:raise RuntimeError('Recovery is restricted to less than 3 mm down')
    goal={c:dict(p,position_z=SEAT_Z) for c,p in start.items()}
    cmd=C.PrepMoveZAbsolute(channels=[C.ChannelZPositionParameters(default_values=False,channel=c,z_position=SEAT_Z) for c in (1,2)],velocity=1)
    return start,goal,cmd

async def run(h,ticket,execute):
    read={C.PrepGetPositions,C.PrepGetPlateHeld,C.PrepGetTipDefinitionHeld,C.PrepGetIsInitialized,C.PrepGetChannelBounds,DoorClosed,C.PrepGetIsEnclosurePresent}
    write={C.PrepMoveZAbsolute,C.PrepMethodBegin,C.PrepMethodEnd,C.PrepMethodAbort}
    class Driver(PrepDriver):
        async def setup(self,**kw):raise RuntimeError('No setup')
        async def stop(self,**kw):raise RuntimeError('Transport close only')
        async def send_command(self,cmd,**kw):
            if type(cmd) not in read|write or (type(cmd) in write and not execute):raise RuntimeError('Command prohibited')
            if type(cmd) in write:h.journal(ticket,'reseat_native_request',dict(command=type(cmd).__name__,parameters=to_jsonable(cmd)))
            return await super().send_command(cmd,**kw)
    def make():return Driver(deck=Deck(name='reseat_closed',size_x=300,size_y=430,size_z=200),io=HamiltonTCPClient(host='192.168.100.102',port=2000,read_timeout=10,write_timeout=5))
    motion,monitor,abort=make(),make(),make();began=False
    async def interlocks():
        for cls in (DoorClosed,C.PrepGetIsEnclosurePresent):
            if not (await monitor.send_command(cls(),read_timeout=2)).value:raise RuntimeError('Door/enclosure changed')
    async def measured():return to_jsonable(await monitor.send_command(C.PrepGetPositions(),read_timeout=2))
    try:
        for d in (motion,monitor,abort):await asyncio.wait_for(d._open(),20)
        await interlocks();await asyncio.to_thread(rest_ready,h)
        if not (await motion.send_command(C.PrepGetIsInitialized())).value:raise RuntimeError('Not initialized; no reset performed')
        if not (await motion.send_command(C.PrepGetPlateHeld())).value:raise RuntimeError('Held state changed')
        if to_jsonable(await motion.send_command(C.PrepGetTipDefinitionHeld()))['value'].get('label')!='DCG':raise RuntimeError('DCG not attached')
        start,goal,cmd=plan(await measured());cmd.build_parameters().build()
        bounds=to_jsonable(await motion.send_command(C.PrepGetChannelBounds()))['bounds']
        for b in bounds:
            if not b['z_min']<=SEAT_Z<=b['z_max']:raise RuntimeError('Outside native Z bounds')
        method=await motion.request_method_by_name(cmd.firmware_path,'MoveZAbsolute')
        if (method.interface_id,method.method_id)!=(1,12):raise RuntimeError('Unexpected command signature')
        print(json.dumps(dict(motion_sent=False,start=start,goal=goal,speed_mm_s=1)),flush=True)
        if not execute:return
        with (h.folder/PRIOR/'reseat_coordinated_stop_attempt.json').open('x') as f:json.dump(dict(start=start,goal=goal),f)
        began=True;await motion.send_command(C.PrepMethodBegin(automatic_pause=True))
        corridor(rows(await measured()),start,start,arrival=True)
        pending=asyncio.create_task(motion.send_command(cmd,read_timeout=10));last_guard=0
        try:
            while not pending.done():
                await asyncio.wait({pending},timeout=.05)
                feedback=await measured();h.journal(ticket,'reseat_sample',feedback)
                corridor(rows(feedback),start,goal)
                if time.monotonic()-last_guard>.4:
                    await interlocks()
                    if await asyncio.to_thread(h.call,'GET','errors/check-for-pending-errors'):raise RuntimeError('Controller fault')
                    last_guard=time.monotonic()
            await pending
        except BaseException:
            try:await asyncio.wait_for(abort.send_command(C.PrepMethodAbort(),read_timeout=3),4)
            finally:pending.cancel();await asyncio.gather(pending,return_exceptions=True)
            raise
        final=await measured();corridor(rows(final),start,goal,arrival=True)
        await motion.send_command(C.PrepMethodEnd());began=False
        final=await measured();corridor(rows(final),start,goal,arrival=True)
        result=dict(status='lowered_awaiting_support_inspection',final_positions=final,jaws_opened=False,batch_resumed=False)
        h.journal(ticket,'reseat_result',result)
        (h.folder/PRIOR/'reseat_coordinated_stop_result.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result),flush=True)
    except BaseException as e:
        if began:
            try:await asyncio.wait_for(abort.send_command(C.PrepMethodAbort(),read_timeout=3),4)
            except BaseException as err:h.journal(ticket,'reseat_abort_error',str(err))
        if execute:h.journal(ticket,'reseat_failed_or_uncertain',str(e))
        raise
    finally:
        for d in (motion,monitor,abort):await d._close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute-confirmed',action='store_true');args=parser.parse_args()
    h=HamiltonPrep();rest_ready(h);ticket=json.loads((h.folder/'active.json').read_text())
    if ticket.get('request_id')!=PRIOR or ticket.get('status')!='failed_or_uncertain':raise RuntimeError('Wrong stopped batch')
    if args.execute_confirmed:
        lock=h.folder/'dcg48_execution.lock'
        with lock.open('x') as f:f.write(PRIOR)
        try:asyncio.run(run(h,ticket,True))
        finally:lock.unlink()
    else:asyncio.run(run(h,ticket,False))
