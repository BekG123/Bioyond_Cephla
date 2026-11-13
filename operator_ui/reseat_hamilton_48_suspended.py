"""One-shot, Z-only supervised recovery of the observed suspended site-4 plate.

Does not release, change jaw spacing, reset faults, clear ownership or resume batch.
Default is read-only validation. Both jaws descend by the same 10 mm at 1 mm/s.
"""
import argparse
import asyncio
import json
import math
import time
from hamilton_dcg_transfer import C, PrepDriver, HamiltonTCPClient, Deck, HamiltonPrep, DoorClosed, to_jsonable, rest_ready

PRIOR='dcg48_repeat_e6281769973846d5bb2a090cdd7767a1'
EXPECTED={1:(54.04150772,86.59623718,27.18883705),2:(54.04150772,2.23074102,27.64614296)}
SEATED={1:(54.04150772,86.73223877,17.18918419),2:(54.04150772,2.30874109,17.64579201)}

def opening(positions):
    rows={p['channel']:p for p in positions['positions']}
    if len(positions['positions'])!=2 or set(rows)!={1,2}:raise RuntimeError('Unexpected channels')
    for c,p in rows.items():
        for key,want in zip(('position_x','position_y','position_z'),SEATED[c]):
            if not math.isfinite(p[key]) or abs(p[key]-want)>.10:raise RuntimeError('Seated position changed; review required')
    return C.PrepMoveYAbsolute(channels=[C.ChannelYPositionParameters(default_values=False,channel=c,
        y_position=rows[c]['position_y']+(2 if c==1 else -2)) for c in (1,2)],velocity=1.0)

def verify_opening(before,after,opened):
    expected={'positions':[dict(p,position_y=p['position_y']+((2 if p['channel']==1 else -2) if opened else 0))
        for p in before['positions']]}
    verify_arrival(expected,after,0)

def lowering(positions):
    rows={p['channel']:p for p in positions['positions']}
    if len(positions['positions'])!=2 or set(rows)!={1,2}:raise RuntimeError('Unexpected channels')
    for c,p in rows.items():
        for key,want in zip(('position_x','position_y','position_z'),EXPECTED[c]):
            if not math.isfinite(p[key]) or abs(p[key]-want)>.10:raise RuntimeError('Position changed; recovery must be reviewed again')
        if p['position_z']-10 <17.18:raise RuntimeError('Recovery would descend below previously seated height')
    return C.PrepMoveZAbsolute(channels=[C.ChannelZPositionParameters(default_values=False,channel=c,
        z_position=rows[c]['position_z']-10) for c in (1,2)],velocity=1.0)

def verify_arrival(before,after,drop):
    a={p['channel']:p for p in after['positions']}
    if set(a)!={1,2}:raise RuntimeError('Unexpected feedback')
    for p in before['positions']:
        q=a[p['channel']]
        for key in ('position_x','position_y','position_z'):
            want=p[key]-(drop if key=='position_z' else 0)
            if not math.isfinite(q[key]) or abs(q[key]-want)>.10:raise RuntimeError('Recovery arrival mismatch or jaw opening changed')

async def run(h,ticket,execute,open_supported=False):
    operation='open_supported' if open_supported else 'reseat'
    reads={C.PrepGetPositions,C.PrepGetPlateHeld,C.PrepGetTipDefinitionHeld,C.PrepGetChannelBounds,
        C.PrepGetIsInitialized,DoorClosed,C.PrepGetIsEnclosurePresent}
    move_type=C.PrepMoveYAbsolute if open_supported else C.PrepMoveZAbsolute
    writes={move_type,C.PrepMethodBegin,C.PrepMethodEnd,C.PrepMethodAbort}
    class Driver(PrepDriver):
        async def setup(self,**kw):raise RuntimeError('Setup prohibited')
        async def stop(self,**kw):raise RuntimeError('Transport close only')
        async def send_command(self,command,**kw):
            if type(command) not in reads|writes:raise RuntimeError('Unreviewed command')
            if type(command) in writes:
                if not execute:raise RuntimeError('Read-only mode')
                h.journal(ticket,operation+'_native_request',dict(command=type(command).__name__,parameters=to_jsonable(command)))
            result=await super().send_command(command,**kw)
            if type(command) in writes:h.journal(ticket,operation+'_native_response',dict(command=type(command).__name__,response=to_jsonable(result)))
            return result
    def make():return Driver(deck=Deck(name='reseat',size_x=300,size_y=430,size_z=200),
        io=HamiltonTCPClient(host='192.168.100.102',port=2000,read_timeout=30,write_timeout=5))
    motion,monitor,abort=make(),make(),make();began=False
    async def interlocks():
        if not (await monitor.send_command(DoorClosed(),read_timeout=2)).value:raise RuntimeError('Door open')
        if not (await monitor.send_command(C.PrepGetIsEnclosurePresent(),read_timeout=2)).value:raise RuntimeError('Enclosure absent')
        await asyncio.to_thread(rest_ready,h)
    async def positions():return to_jsonable(await motion.send_command(C.PrepGetPositions()))
    async def checked(cmd):
        await interlocks()
        task=asyncio.create_task(motion.send_command(cmd,read_timeout=30));deadline=time.monotonic()+35
        try:
            while not task.done():
                await asyncio.wait({task},timeout=.25)
                if not task.done():
                    if time.monotonic()>deadline:raise TimeoutError('Recovery timed out')
                    await interlocks()
            return await task
        except BaseException:
            task.cancel();await asyncio.gather(task,return_exceptions=True);raise
    try:
        for d in (motion,monitor,abort):await asyncio.wait_for(d._open(),20)
        method=await motion.request_method_by_name(move_type.firmware_path,'MoveYAbsolute' if open_supported else 'MoveZAbsolute')
        if (method.interface_id,method.method_id)!=(1,move_type.command_id):raise RuntimeError('Unexpected movement command signature')
        await interlocks()
        if not (await motion.send_command(C.PrepGetIsInitialized())).value:raise RuntimeError('Not initialized')
        tool=to_jsonable(await motion.send_command(C.PrepGetTipDefinitionHeld()))['value']
        if tool.get('label')!='DCG' or not tool.get('is_tool'):raise RuntimeError('DCG not mounted')
        if (await motion.send_command(C.PrepGetPlateHeld())).value:raise RuntimeError('Firmware state changed; review required')
        before=await positions();command=(opening if open_supported else lowering)(before);command.build_parameters().build()
        bounds=to_jsonable(await motion.send_command(C.PrepGetChannelBounds()))['bounds']
        # All target coordinates remain inside the native bounds checked below.
        print(json.dumps(dict(before=before,command=to_jsonable(command),bounds=bounds),indent=2),flush=True)
        for channel in command.channels:
            b=next(b for b in bounds if b['channel']==channel.channel)
            axis='y' if open_supported else 'z'
            if not b[axis+'_min']<=getattr(channel,axis+'_position')<=b[axis+'_max']:raise RuntimeError('Target outside native bounds')
        if not execute:return
        h.journal(ticket,operation+'_before',dict(positions=before,physical_plate_held=True,
            operator_confirmed_fully_supported=open_supported,operator_clear_downward_path=not open_supported))
        with (h.folder/PRIOR/(operation+'_attempt.json')).open('x',encoding='utf-8') as f:
            json.dump(dict(command=to_jsonable(command),status='attempt_started',before=before),f)
        began=True;await checked(C.PrepMethodBegin(automatic_pause=True))
        verify_arrival(before,await positions(),0)
        await checked(command)
        after=await positions()
        h.journal(ticket,operation+'_arrival',after)
        if open_supported:verify_opening(before,after,True)
        else:verify_arrival(before,after,10)
        await checked(C.PrepMethodEnd());began=False
        final=await positions()
        if open_supported:verify_opening(before,final,True)
        else:verify_arrival(before,final,10)
        result=dict(status='opened_awaiting_clearance_inspection' if open_supported else 'lowered_awaiting_support_inspection',before=before,after=final,
            jaws_opened=open_supported,retreated=False,batch_resumed=False,physical_support_unverified=not open_supported)
        (h.folder/PRIOR/(operation+'_result.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
        h.journal(ticket,operation+'_result',result);print(json.dumps(result,indent=2),flush=True)
    except BaseException as error:
        if began:
            try:await asyncio.wait_for(abort.send_command(C.PrepMethodAbort(),read_timeout=5),7)
            except BaseException as abort_error:h.journal(ticket,'reseat_abort_error',str(abort_error))
        if execute:h.journal(ticket,operation+'_stopped',str(error))
        raise
    finally:
        for d in (motion,monitor,abort):await d._close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--execute-confirmed',action='store_true')
    modes.add_argument('--open-supported-confirmed',action='store_true')
    parser.add_argument('--check-opening',action='store_true')
    args=parser.parse_args();h=HamiltonPrep();rest_ready(h)
    ticket=json.loads((h.folder/'active.json').read_text())
    if ticket.get('request_id')!=PRIOR or ticket.get('status')!='failed_or_uncertain':raise RuntimeError('Recovery ownership mismatch')
    if args.check_opening and (args.execute_confirmed or args.open_supported_confirmed):raise RuntimeError('Check cannot execute')
    if args.execute_confirmed or args.open_supported_confirmed:
        lock=h.folder/'dcg48_execution.lock'
        with lock.open('x',encoding='utf-8') as f:f.write(PRIOR)
        try:asyncio.run(run(h,ticket,True,args.open_supported_confirmed))
        finally:lock.unlink()
    else:asyncio.run(run(h,ticket,False,args.check_opening))

if __name__=='__main__':main()
