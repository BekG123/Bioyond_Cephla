"""One empty-deck, high-clearance retry using complete coordinated jaw targets.

Default offline. Never clears faults, changes limits, or resumes plate cycles.
Avoids independent-axis commands and implicit safe-height jaw repacking.
"""
import argparse
import asyncio
import json
import math
import time
from uuid import uuid4
from hamilton_dcg_transfer import C,PrepDriver,HamiltonTCPClient,Deck,HamiltonPrep,DoorClosed,to_jsonable,rest_ready
from diagnose_hamilton_dcg_empty import X,Y,CLOSED_SPAN,PRIOR

def target(span,z):
    if not CLOSED_SPAN<=span<=CLOSED_SPAN+20 or not 150<=z<=160:
        raise ValueError('Only reviewed empty-test targets are allowed')
    return {c:dict(position_x=X,position_y=Y+sign*span/2,position_z=z) for c,sign in ((1,1),(2,-1))}

def command(goal):
    return C.PrepMoveToPosition(move_parameters=C.GantryMoveXYZParameters(default_values=False,gantry_x_position=X,
        axis_parameters=[C.ChannelYZMoveParameters(default_values=False,channel=c,y_position=p['position_y'],z_position=p['position_z']) for c,p in sorted(goal.items())]))

def rows(feedback):
    p={p['channel']:p for p in feedback['positions']}
    if set(p)!={1,2}:raise RuntimeError('Unexpected channels')
    if not all(math.isfinite(p[c][k]) for c in p for k in ('position_x','position_y','position_z')):
        raise RuntimeError('Invalid position feedback')
    return p

def corridor(actual,start,goal,arrival=False):
    for c in (1,2):
        for k in ('position_x','position_y','position_z'):
            lo,hi=sorted((start[c][k],goal[c][k]))
            if arrival:lo=hi=goal[c][k]
            # No implicit Z rise, jaw folding, or lateral detour is accepted.
            if not lo-.25<=actual[c][k]<=hi+.25:
                raise RuntimeError(f'Unexpected channel {c} {k}: {actual[c][k]:.3f}; expected {lo:.3f}..{hi:.3f}')
    spacing=actual[1]['position_y']-actual[2]['position_y']
    minimum=min(p[1]['position_y']-p[2]['position_y'] for p in (start,goal))
    if spacing<minimum-.25:raise RuntimeError('Jaw spacing shrank outside commanded interval')

def steps():
    return [('open_at_150',target(CLOSED_SPAN+20,150)),('close_in_air',target(CLOSED_SPAN,150)),
            ('reopen_10mm_each',target(CLOSED_SPAN+20,150)),('lift_open_10mm',target(CLOSED_SPAN+20,160))]

async def run(h,ticket):
    reads={C.PrepGetPositions,C.PrepGetPlateHeld,C.PrepGetTipDefinitionHeld,C.PrepGetIsInitialized,
           C.PrepGetChannelBounds,C.PrepGetXSpeedScale,C.PrepGetZSpeedScale,C.PrepIsParked,DoorClosed,C.PrepGetIsEnclosurePresent}
    writes={C.PrepMoveToPosition,C.PrepDropTool,C.PrepPark,C.PrepSetXSpeedScale,C.PrepSetZSpeedScale,
            C.PrepMethodBegin,C.PrepMethodEnd,C.PrepMethodAbort}
    class Driver(PrepDriver):
        async def setup(self,**kw):raise RuntimeError('No automatic setup')
        async def stop(self,**kw):raise RuntimeError('Transport close only')
        async def send_command(self,cmd,**kw):
            if type(cmd) not in reads|writes:raise RuntimeError('Command not allowed')
            if type(cmd) in writes:h.journal(ticket,'native_request',dict(command=type(cmd).__name__,parameters=to_jsonable(cmd)))
            result=await super().send_command(cmd,**kw)
            if type(cmd) in writes:h.journal(ticket,'native_response',dict(command=type(cmd).__name__,response=to_jsonable(result)))
            return result
    def make():return Driver(deck=Deck(name='coordinated_retry',size_x=300,size_y=430,size_z=200),io=HamiltonTCPClient(host='192.168.100.102',port=2000,read_timeout=30,write_timeout=5))
    motion,monitor,abort=make(),make(),make();began=False
    async def interlocks():
        for cls in (DoorClosed,C.PrepGetIsEnclosurePresent):
            if not (await monitor.send_command(cls(),read_timeout=2)).value:raise RuntimeError('Door/enclosure changed')
    async def measure(phase):
        feedback=to_jsonable(await monitor.send_command(C.PrepGetPositions(),read_timeout=2))
        h.journal(ticket,'sample',dict(phase=phase,at=time.time(),feedback=feedback))
        return rows(feedback)
    async def checked(cmd,phase,goal=None):
        await interlocks();await asyncio.to_thread(rest_ready,h)
        start=await measure(phase)
        print(phase,flush=True)
        task=asyncio.create_task(motion.send_command(cmd,read_timeout=30));last_guard=time.monotonic()
        try:
            while not task.done():
                await asyncio.wait({task},timeout=.05)
                actual=await measure(phase)
                if goal:corridor(actual,start,goal)
                if time.monotonic()-last_guard>.5:
                    await interlocks()
                    if await asyncio.to_thread(h.call,'GET','errors/check-for-pending-errors'):raise RuntimeError('Controller error')
                    last_guard=time.monotonic()
            await task
            if goal:
                for _ in range(10):
                    actual=await measure(phase);corridor(actual,start,goal,arrival=True);await asyncio.sleep(.1)
            await interlocks()
        except BaseException:
            # Stop on the independent connection before waiting for the failed motion task.
            try:await asyncio.wait_for(abort.send_command(C.PrepMethodAbort(),read_timeout=3),4)
            finally:task.cancel();await asyncio.gather(task,return_exceptions=True)
            raise
    try:
        for d in (motion,monitor,abort):await asyncio.wait_for(d._open(),20)
        method=await motion.request_method_by_name(C.PrepMoveToPosition.firmware_path,'MoveToPosition')
        if (method.interface_id,method.method_id)!=(1,26):raise RuntimeError('Unexpected motion signature')
        if not (await motion.send_command(C.PrepGetIsInitialized())).value:raise RuntimeError('Human recovery required; not initialized')
        if (await motion.send_command(C.PrepGetPlateHeld())).value:raise RuntimeError('Expected no held plate')
        if to_jsonable(await motion.send_command(C.PrepGetTipDefinitionHeld()))['value'].get('label')!='DCG':raise RuntimeError('Expected attached empty DCG')
        current=await measure('preflight')
        expected={1:(X,94.7262344,150),2:(X,59.8957443,150)}
        for c,p in current.items():
            if any(abs(p[k]-v)>.5 for k,v in zip(('position_x','position_y','position_z'),expected[c])):raise RuntimeError('Stopped pose changed; review before motion')
        bounds=to_jsonable(await motion.send_command(C.PrepGetChannelBounds()))['bounds']
        for _,goal in steps():
            for b in bounds:
                for axis in ('x','y','z'):
                    if not b[axis+'_min']<=goal[b['channel']]['position_'+axis]<=b[axis+'_max']:raise RuntimeError('Target outside native bounds')
        scales=[(await motion.send_command(C.PrepGetXSpeedScale())).value,(await motion.send_command(C.PrepGetZSpeedScale())).value]
        began=True;await checked(C.PrepMethodBegin(automatic_pause=True),'begin')
        await checked(C.PrepSetXSpeedScale(value=5),'x_scale_5');await checked(C.PrepSetZSpeedScale(value=5),'z_scale_5')
        for label,goal in steps():await checked(command(goal),label,goal)
        h.journal(ticket,'coordinated_test_passed',dict(physical_plate_present=False,loaded_release_validated=False))
        await checked(C.PrepDropTool(),'return_empty_tool');await checked(C.PrepPark(),'park')
        if not (await motion.send_command(C.PrepIsParked())).value or (await motion.send_command(C.PrepGetPlateHeld())).value or to_jsonable(await motion.send_command(C.PrepGetTipDefinitionHeld()))['value'].get('is_tool'):
            raise RuntimeError('Park/empty verification failed')
        await checked(C.PrepSetXSpeedScale(value=scales[0]),'restore_x');await checked(C.PrepSetZSpeedScale(value=scales[1]),'restore_z')
        await checked(C.PrepMethodEnd(),'end');began=False
        result=dict(status='completed',empty_test_passed=True,parked=True,loaded_release_validated=False)
        h.journal(ticket,'outcome',result);return result
    except BaseException as e:
        if began:
            try:await asyncio.wait_for(abort.send_command(C.PrepMethodAbort(),read_timeout=3),4)
            except BaseException as stop_error:h.journal(ticket,'abort_error',str(stop_error))
        h.journal(ticket,'outcome',dict(status='failed_or_uncertain',error=str(e)));raise
    finally:
        for d in (motion,monitor,abort):await d._close()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute-empty-deck-confirmed',action='store_true');args=p.parse_args()
    for _,goal in steps():command(goal).build_parameters().build()
    if not args.execute_empty_deck_confirmed:
        print(json.dumps(dict(motion_sent=False,steps=steps()),indent=2));return
    h=HamiltonPrep();rest_ready(h);marker=h.folder/'active.json';owner=json.loads(marker.read_text())
    if owner.get('request_id')!=PRIOR or owner.get('status')!='failed_or_uncertain':raise RuntimeError('Wrong stopped owner')
    ticket=dict(request_id='dcg_coordinated_retry_'+uuid4().hex,prior_request_id=PRIOR,
        operator_confirmation='Plate removed; tool docked; all clear, followed by fix it and retry after empty diagnostic')
    lock=h.folder/'dcg48_execution.lock'
    with lock.open('x') as f:f.write(ticket['request_id'])
    try:
        with (h.folder/PRIOR/'coordinated_empty_retry_attempt.json').open('x') as f:json.dump(ticket,f)
        h.journal(ticket,'begin',ticket);print(ticket['request_id'],flush=True)
        owner['latest_diagnostic_request_id']=ticket['request_id'];owner['latest_physical_state']='Empty coordinated test in progress; old checkpoint is historical'
        marker.write_text(json.dumps(owner,indent=2))
        result=asyncio.run(run(h,ticket))
        owner['latest_physical_state']='Verified parked, empty, tool docked after coordinated empty retry'
        owner['latest_diagnostic_result']=result;marker.write_text(json.dumps(owner,indent=2))
        print(json.dumps(result),flush=True)
    except BaseException:
        owner['latest_physical_state']='Empty coordinated retry stopped; inspect its log and fresh feedback before motion'
        marker.write_text(json.dumps(owner,indent=2));raise
    finally:lock.unlink()

if __name__=='__main__':main()
