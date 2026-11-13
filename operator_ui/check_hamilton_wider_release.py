"""Prepare a 15 mm/side empty-jaw diagnostic; never used for loaded plate release.

Default offline. --check reads controller state. --execute-empty-confirmed requires
operator removal of the already released plate. No Z travel or batch continuation.
"""
import argparse
import asyncio
from dataclasses import dataclass
import json
import time
from hamilton_dcg_transfer import C,PrepDriver,HamiltonTCPClient,Deck,HamiltonPrep,DoorClosed,to_jsonable,rest_ready
from retry_hamilton_dcg_coordinated import rows,corridor
from release_hamilton_supported_plate import EXPECTED
from reseat_hamilton_coordinated_stop import PRIOR

@dataclass
class ChannelYDistance:
    channel:int
    distance:float
    def encode_into(self,p):return p.add(False,C.PaddedBool).add(self.channel,C.WEnum).add(self.distance,C.F32)

@dataclass(frozen=True)
class MoveYRelative(C.PrepCommand[None]):
    command_id=11
    firmware_path=C.PrepMoveYAbsolute.firmware_path
    distance:float
    def build_parameters(self):
        if not 0<self.distance<=.5:raise ValueError('Diagnostic steps limited to 0.5 mm per jaw')
        return C.HoiParams().add([ChannelYDistance(1,self.distance),ChannelYDistance(2,-self.distance)],C.StructArray()).add(1.,C.F32)
    @classmethod
    def parse_response_parameters(cls,data):return None

def total_target(total):
    if not 4<=total<=15:raise ValueError('Only 4 to 15 mm total opening')
    return {c:dict(position_x=p[0],position_y=p[1]+(total if c==1 else -total),position_z=p[2]) for c,p in EXPECTED.items()}

async def run(h,ticket,execute):
    read={C.PrepGetPositions,C.PrepGetPlateHeld,C.PrepGetTipDefinitionHeld,C.PrepGetIsInitialized,C.PrepGetChannelBounds,DoorClosed,C.PrepGetIsEnclosurePresent}
    write={MoveYRelative,C.PrepMethodBegin,C.PrepMethodEnd,C.PrepMethodAbort}
    class Driver(PrepDriver):
        async def setup(self,**kw):raise RuntimeError('No setup')
        async def stop(self,**kw):raise RuntimeError('Transport close only')
        async def send_command(self,cmd,**kw):
            if type(cmd) not in read|write or (type(cmd) in write and not execute):raise RuntimeError('Command prohibited')
            if type(cmd) in write:h.journal(ticket,'wider_empty_request',dict(command=type(cmd).__name__,parameters=to_jsonable(cmd)))
            result=await super().send_command(cmd,**kw)
            if type(cmd) in write:h.journal(ticket,'wider_empty_response',dict(command=type(cmd).__name__,result=to_jsonable(result)))
            return result
    def make():return Driver(deck=Deck(name='wider_empty',size_x=300,size_y=430,size_z=200),io=HamiltonTCPClient(host='192.168.100.102',port=2000,read_timeout=5,write_timeout=5))
    motion,monitor,abort=make(),make(),make();began=False;stopped=False
    async def measure():return to_jsonable(await monitor.send_command(C.PrepGetPositions(),read_timeout=2))
    async def interlocks():
        for cls in (DoorClosed,C.PrepGetIsEnclosurePresent):
            if not (await monitor.send_command(cls(),read_timeout=2)).value:raise RuntimeError('Door/enclosure changed')
    async def stop():
        nonlocal stopped
        if not stopped:
            stopped=True;await asyncio.wait_for(abort.send_command(C.PrepMethodAbort(),read_timeout=3),4)
    try:
        for d in (motion,monitor,abort):await asyncio.wait_for(d._open(),20)
        await interlocks();await asyncio.to_thread(rest_ready,h)
        if not (await motion.send_command(C.PrepGetIsInitialized())).value:raise RuntimeError('Not initialized')
        if (await motion.send_command(C.PrepGetPlateHeld())).value:raise RuntimeError('Expected released firmware state; operator must also remove the plate')
        if to_jsonable(await motion.send_command(C.PrepGetTipDefinitionHeld()))['value'].get('label')!='DCG':raise RuntimeError('Expected DCG')
        before=await measure();actual=rows(before);corridor(actual,total_target(4),total_target(4),arrival=True)
        bounds=to_jsonable(await motion.send_command(C.PrepGetChannelBounds()))['bounds']
        for b in bounds:
            for axis in ('x','y','z'):
                if not b[axis+'_min']<=total_target(15)[b['channel']]['position_'+axis]<=b[axis+'_max']:raise RuntimeError('Final target outside native bounds')
        method=await motion.request_method_by_name(MoveYRelative.firmware_path,'MoveYRelative')
        if (method.interface_id,method.method_id)!=(1,11) or [p['name'] for p in method.to_dict()['params']]!=['channels','velocity']:raise RuntimeError('Unexpected relative command signature')
        addr=await motion.resolve_path(MoveYRelative.firmware_path)
        structures=await motion.io.introspection.get_structs(addr,1)
        if structures[1].name!='ChannelYDistance' or list(structures[1].fields)!=['DefaultValues','Channel','YDistance']:raise RuntimeError('Unexpected relative structure')
        print(json.dumps(dict(motion_sent=False,before=before,target=total_target(15),extra_per_jaw_mm=11,step_mm=.5,requires_empty_deck=True)),flush=True)
        if not execute:return
        with (h.folder/PRIOR/'wider_empty_15_attempt.json').open('x') as f:json.dump(dict(before=before,target=total_target(15),physical_plate_removed=True),f)
        began=True;await motion.send_command(C.PrepMethodBegin(automatic_pause=True))
        corridor(rows(await measure()),actual,actual,arrival=True)
        for step in range(1,23):
            start=rows(await measure());goal=total_target(4+step*.5)
            corridor(start,total_target(4+(step-1)*.5),total_target(4+(step-1)*.5),arrival=True)
            await interlocks();await asyncio.to_thread(rest_ready,h)
            pending=asyncio.create_task(motion.send_command(MoveYRelative(.5),read_timeout=5))
            try:
                while not pending.done():
                    await asyncio.wait({pending},timeout=.05)
                    feedback=await measure();h.journal(ticket,'wider_empty_sample',dict(step=step,positions=feedback))
                    corridor(rows(feedback),start,goal)
                await pending
                for _ in range(3):
                    feedback=await measure();corridor(rows(feedback),start,goal,arrival=True);await asyncio.sleep(.1)
            except BaseException:
                try:await stop()
                finally:pending.cancel();await asyncio.gather(pending,return_exceptions=True)
                raise
            print(f'Empty-jaw total opening verified: {4+step*.5:.1f} mm per side',flush=True)
        await motion.send_command(C.PrepMethodEnd());began=False
        final=await measure();corridor(rows(final),total_target(15),total_target(15),arrival=True)
        result=dict(status='empty_opening_complete',physical_plate_present=False,loaded_release_validated=False,total_per_jaw_mm=15,final_positions=final,retreat=False)
        h.journal(ticket,'wider_empty_result',result)
        (h.folder/PRIOR/'wider_empty_15_result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
    except BaseException as error:
        if began:
            try:await stop()
            except BaseException as e:h.journal(ticket,'wider_empty_abort_error',str(e))
        if execute:h.journal(ticket,'wider_empty_failed',str(error))
        raise
    finally:
        for d in (motion,monitor,abort):await d._close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--check',action='store_true');mode.add_argument('--execute-empty-confirmed',action='store_true');args=parser.parse_args()
    MoveYRelative(.5).build_parameters().build()
    if not (args.check or args.execute_empty_confirmed):print(json.dumps(dict(motion_sent=False,target=total_target(15),extra_per_side_mm=11)))
    else:
        h=HamiltonPrep();rest_ready(h);ticket=json.loads((h.folder/'active.json').read_text())
        if ticket.get('request_id')!=PRIOR or ticket.get('status')!='failed_or_uncertain':raise RuntimeError('Wrong stopped batch')
        if args.execute_empty_confirmed:
            lock=h.folder/'dcg48_execution.lock'
            with lock.open('x') as f:f.write(PRIOR)
            try:asyncio.run(run(h,ticket,True))
            finally:lock.unlink()
        else:asyncio.run(run(h,ticket,False))
