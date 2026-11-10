"""Park the Hamilton with bare channels after the DCG has been returned to its dock.

Default read-only. --execute-confirmed sends native Park at X/Z speed scale 5.
Leaves the unresolved-batch marker (active.json) in place.
"""
import argparse
import asyncio
import json
from uuid import uuid4
from hamilton_dcg_transfer import C, PrepDriver, HamiltonTCPClient, Deck, HamiltonPrep, DoorClosed, to_jsonable, rest_ready
from reseat_hamilton_coordinated_stop import PRIOR


async def run(h, ticket, execute):
    reads = {C.PrepGetPositions, C.PrepGetPlateHeld, C.PrepGetTipDefinitionHeld, C.PrepGetIsInitialized,
             C.PrepGetXSpeedScale, C.PrepGetZSpeedScale, C.PrepIsParked, DoorClosed, C.PrepGetIsEnclosurePresent}
    writes = {C.PrepMethodBegin, C.PrepMethodEnd, C.PrepMethodAbort, C.PrepPark, C.PrepSetXSpeedScale, C.PrepSetZSpeedScale}
    class Driver(PrepDriver):
        async def setup(self, **kw): raise RuntimeError('No setup')
        async def stop(self, **kw): raise RuntimeError('Transport close only')
        async def send_command(self, cmd, **kw):
            if type(cmd) not in reads | writes or (type(cmd) in writes and not execute): raise RuntimeError('Command prohibited')
            if type(cmd) in writes: h.journal(ticket, 'park_request', dict(command=type(cmd).__name__, parameters=to_jsonable(cmd)))
            result = await super().send_command(cmd, **kw)
            if type(cmd) in writes: h.journal(ticket, 'park_response', dict(command=type(cmd).__name__, result=to_jsonable(result)))
            return result
    def make():
        return Driver(deck=Deck(name='park_bare', size_x=300, size_y=430, size_z=200),
                      io=HamiltonTCPClient(host='192.168.100.102', port=2000, read_timeout=60, write_timeout=5))
    motion, monitor, abort = make(), make(), make()
    began = False
    async def interlocks():
        for cls in (DoorClosed, C.PrepGetIsEnclosurePresent):
            if not (await monitor.send_command(cls(), read_timeout=2)).value: raise RuntimeError('Door/enclosure open')
    try:
        for d in (motion, monitor, abort): await asyncio.wait_for(d._open(), 20)
        method = await motion.request_method_by_name('MLPrepRoot.MLPrep', 'Park')
        if (method.interface_id, method.method_id) != (1, 3): raise RuntimeError('Firmware signature changed: Park')
        await interlocks(); await asyncio.to_thread(rest_ready, h)
        if not (await monitor.send_command(C.PrepGetIsInitialized())).value: raise RuntimeError('Not initialized')
        if (await monitor.send_command(C.PrepGetPlateHeld())).value: raise RuntimeError('Firmware records a held plate')
        tool = to_jsonable(await monitor.send_command(C.PrepGetTipDefinitionHeld()))['value']
        if tool.get('is_tool') or tool.get('id'): raise RuntimeError('Channels must be bare')
        before = to_jsonable(await monitor.send_command(C.PrepGetPositions()))
        scales = [(await monitor.send_command(C.PrepGetXSpeedScale())).value, (await monitor.send_command(C.PrepGetZSpeedScale())).value]
        print(json.dumps(dict(motion_sent=False, before=before, scales=scales, parked=(await monitor.send_command(C.PrepIsParked())).value)), flush=True)
        if not execute: return
        began = True
        await motion.send_command(C.PrepMethodBegin(automatic_pause=True))
        await motion.send_command(C.PrepSetXSpeedScale(value=5)); await motion.send_command(C.PrepSetZSpeedScale(value=5))
        task = asyncio.create_task(motion.send_command(C.PrepPark(), read_timeout=60))
        while not task.done():
            await asyncio.wait({task}, timeout=.25)
            await interlocks()
        await task
        if not (await monitor.send_command(C.PrepIsParked())).value: raise RuntimeError('Park not confirmed')
        await motion.send_command(C.PrepSetXSpeedScale(value=scales[0])); await motion.send_command(C.PrepSetZSpeedScale(value=scales[1]))
        await motion.send_command(C.PrepMethodEnd()); began = False
        result = dict(status='parked', final_positions=to_jsonable(await monitor.send_command(C.PrepGetPositions())), tool=tool, marker_retained=True)
        h.journal(ticket, 'park_result', result)
        print(json.dumps(result), flush=True)
    except BaseException as error:
        if began:
            try: await asyncio.wait_for(abort.send_command(C.PrepMethodAbort(), read_timeout=3), 4)
            except BaseException as stop_error: h.journal(ticket, 'park_abort_error', str(stop_error))
        if execute: h.journal(ticket, 'park_failed', str(error))
        raise
    finally:
        for d in (motion, monitor, abort):
            try: await d._close()
            except Exception: pass


if __name__ == '__main__':
    import logging
    logging.disable(logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-confirmed', action='store_true')
    args = parser.parse_args()
    h = HamiltonPrep()
    ticket = dict(request_id='bare_park_' + uuid4().hex, prior_request_id=PRIOR)
    if not args.execute_confirmed:
        asyncio.run(run(h, ticket, False))
    else:
        lock = h.folder / 'dcg48_execution.lock'
        with lock.open('x') as f: f.write(ticket['request_id'])
        try: asyncio.run(run(h, ticket, True))
        finally: lock.unlink()
