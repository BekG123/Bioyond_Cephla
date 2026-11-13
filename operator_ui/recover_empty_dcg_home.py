"""Recovery for reviewed DCG trial only; requires confirmed physical plate removal."""
import argparse
import asyncio
import json
import time
from uuid import uuid4
from hamilton_dcg_transfer import (C, PrepDriver, HamiltonTCPClient, Deck,
    HamiltonPrep, DoorClosed, to_jsonable, rest_ready, PIP)

PRIOR = '1d9c35bc7ddb48e696b813bbab8f8844'

async def recover(h, ticket, execute, initial_retreat=None):
    reads = {C.PrepGetIsInitialized, C.PrepGetPositions, C.PrepGetPlateHeld,
             C.PrepGetTipDefinitionHeld, DoorClosed, C.PrepGetIsEnclosurePresent,
             C.PrepIsParked}
    writes = {C.PrepMethodBegin, C.PrepMethodEnd, C.PrepMethodAbort,
              C.PrepReleasePlate, C.PrepMoveZUpToSafe, C.PrepDropTool,
              C.PrepPark, C.PrepSetXSpeedScale, C.PrepSetZSpeedScale}
    if initial_retreat is not None:writes.add(C.PrepMoveZAbsolute)
    class Driver(PrepDriver):
        async def setup(self, **kwargs): raise RuntimeError('No automatic initialization')
        async def stop(self, **kwargs): raise RuntimeError('Transport close only')
        async def send_command(self, command, **kwargs):
            if type(command) not in reads | writes: raise RuntimeError('Unreviewed command')
            if type(command) in writes:
                if not execute: raise RuntimeError('Read-only mode')
                h.journal(ticket, 'native_request', dict(command=type(command).__name__, parameters=to_jsonable(command)))
            result = await super().send_command(command, **kwargs)
            if type(command) in writes:
                h.journal(ticket, 'native_response', dict(command=type(command).__name__, response=to_jsonable(result)))
            return result
    def driver():
        return Driver(deck=Deck(name='empty_dcg_recovery', size_x=300, size_y=430, size_z=200),
                      io=HamiltonTCPClient(host='192.168.100.102', port=2000, read_timeout=60, write_timeout=5))
    motion, monitor, abort = driver(), driver(), driver()
    began = False
    async def interlocks():
        for cmd in (DoorClosed(), C.PrepGetIsEnclosurePresent()):
            if not (await monitor.send_command(cmd, read_timeout=2)).value:
                raise RuntimeError('Door/enclosure interlock not satisfied')
    async def checked(cmd):
        await interlocks()
        await asyncio.to_thread(rest_ready, h)
        print('Running ' + type(cmd).__name__, flush=True)
        task = asyncio.create_task(motion.send_command(cmd, read_timeout=60))
        try:
            deadline = time.monotonic() + 65
            while not task.done():
                await asyncio.wait({task}, timeout=.25)
                if task.done(): break
                await interlocks()
                if time.monotonic() > deadline: raise TimeoutError('Recovery command timeout')
                if await asyncio.to_thread(h.call, 'GET', 'errors/check-for-pending-errors'):
                    raise RuntimeError('Hamilton reported an error')
            return await task
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
    try:
        for d in (motion, monitor, abort): await asyncio.wait_for(d._open(), 20)
        for path, name, expected in ((PIP, 'ReleasePlate', 21), (PIP, 'MoveZUpToSafe', 28),
                                     (PIP, 'DropTool', 16), ('MLPrepRoot.MLPrep', 'Park', 3),
                                     ('MLPrepRoot.MLPrep', 'GetIsDoorClosed', 22)):
            method = await motion.request_method_by_name(path, name)
            if (method.interface_id, method.method_id) != (1, expected):
                raise RuntimeError('Firmware signature changed: ' + name)
        parked_method = await motion.request_method_by_name('MLPrepRoot.MLPrep', 'IsParked')
        if parked_method.method_id != C.PrepIsParked.command_id:
            raise RuntimeError('Park feedback method differs')
        await interlocks()
        if not (await motion.send_command(C.PrepGetIsInitialized())).value:
            raise RuntimeError('Not initialized; no automatic reset')
        initial = {name: to_jsonable(await motion.send_command(getattr(C, name)())) for name in
                   ('PrepGetPositions', 'PrepGetPlateHeld', 'PrepGetTipDefinitionHeld')}
        h.journal(ticket, 'initial', initial)
        if not initial['PrepGetTipDefinitionHeld']['value'].get('is_tool'):
            raise RuntimeError('Expected attached DCG tool')
        if initial['PrepGetTipDefinitionHeld']['value'].get('label') != 'DCG':
            raise RuntimeError('Unexpected tool identity')
        if initial_retreat is not None:
            from reseat_hamilton_48_suspended import verify_arrival
            if initial['PrepGetPlateHeld']['value']:raise RuntimeError('Empty retreat requires unheld plate')
            verify_arrival(initial_retreat['before'],initial['PrepGetPositions'],0)
            method=await motion.request_method_by_name(C.PrepMoveZAbsolute.firmware_path,'MoveZAbsolute')
            if (method.interface_id,method.method_id)!=(1,12):raise RuntimeError('Unexpected vertical retreat method')
        if not execute:
            print('READ-ONLY RECOVERY CHECK PASSED', flush=True)
            return
        await checked(C.PrepMethodBegin(automatic_pause=True)); began = True
        await checked(C.PrepSetXSpeedScale(value=20))
        await checked(C.PrepSetZSpeedScale(value=20))
        if initial['PrepGetPlateHeld']['value']:
            await checked(C.PrepReleasePlate())
        if (await motion.send_command(C.PrepGetPlateHeld())).value:
            raise RuntimeError('Removed plate still recorded as held')
        if initial_retreat is not None:
            await checked(initial_retreat['command'])
            feedback=to_jsonable(await motion.send_command(C.PrepGetPositions()))
            h.journal(ticket,'slow_open_jaw_retreat_feedback',feedback)
            verify_arrival(initial_retreat['before'],feedback,-10)
        await checked(C.PrepMoveZUpToSafe(channels=[1, 2]))
        h.journal(ticket, 'clearance_positions', to_jsonable(await motion.send_command(C.PrepGetPositions())))
        await checked(C.PrepDropTool())
        tool = to_jsonable(await motion.send_command(C.PrepGetTipDefinitionHeld()))
        h.journal(ticket, 'returned_tool', tool)
        if tool['value'].get('is_tool'): raise RuntimeError('Tool return not confirmed')
        await checked(C.PrepPark())
        if not (await motion.send_command(C.PrepIsParked())).value:
            raise RuntimeError('Park not confirmed')
        # Restore scales captured before the original transfer, only after parking.
        await checked(C.PrepSetXSpeedScale(value=100))
        await checked(C.PrepSetZSpeedScale(value=100))
        await checked(C.PrepMethodEnd()); began = False
        h.journal(ticket, 'final_positions', to_jsonable(await motion.send_command(C.PrepGetPositions())))
    except BaseException:
        if began:
            try: await asyncio.wait_for(abort.send_command(C.PrepMethodAbort(), read_timeout=5), 7)
            except BaseException as e: h.journal(ticket, 'abort_failed', str(e))
        raise
    finally:
        for d in (motion, monitor, abort): await d._close()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute-plate-removed-confirmed', action='store_true')
    args = p.parse_args()
    h = HamiltonPrep()
    marker = h.folder / 'active.json'
    prior = json.loads(marker.read_text())
    if prior.get('request_id') != PRIOR or prior.get('status') != 'failed_or_uncertain':
        raise RuntimeError('Only the reviewed stopped transfer can be recovered')
    rest_ready(h)
    ticket = dict(request_id='dcg_recovery_' + uuid4().hex, action='empty_tool_return_and_park',
                  prior_request_id=PRIOR, operator_confirmed='Plate removed; path clear; door closed; hands clear; E-stop supervised')
    h.journal(ticket, 'begin', ticket)
    try:
        asyncio.run(recover(h, ticket, args.execute_plate_removed_confirmed))
        state = rest_ready(h)
        if args.execute_plate_removed_confirmed:
            if not state.get('parked') or h.call('GET', 'service-software-api/has-tips') is not False:
                raise RuntimeError('Final REST park/empty-tool verification failed')
            h.journal(ticket, 'outcome', dict(status='completed', parked=True, tool_returned=True))
            # Preserve failed-transfer evidence; resolve its hold only after verified recovery.
            (h.folder / (PRIOR + '_resolved_by_recovery.json')).write_text(json.dumps(
                dict(original=prior, recovery_request=ticket['request_id'], transfer_succeeded=False,
                     recovery_completed=True), indent=2), encoding='utf-8')
            if json.loads(marker.read_text()).get('request_id') != PRIOR:
                raise RuntimeError('Active operation changed; retain marker')
            marker.unlink()
            print('VERIFIED: EMPTY TOOL RETURNED; HAMILTON PARKED', flush=True)
    except BaseException as e:
        h.journal(ticket, 'outcome', dict(status='failed_or_uncertain', error=str(e)))
        raise

if __name__ == '__main__': main()
