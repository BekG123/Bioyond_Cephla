"""One empty 0.5 mm opening retry with independent raw-drive feedback.

Default read-only; --execute-empty-confirmed performs only 4.5 -> 5 mm/side.
No lift, fault reset, plate handling, or automatic continuation to 15 mm.
"""
import argparse
import asyncio
import json
import math
import time
from check_hamilton_wider_release import MoveYRelative, total_target, PRIOR
from hamilton_dcg_transfer import C, PrepDriver, HamiltonTCPClient, Deck, HamiltonPrep, DoorClosed, to_jsonable, rest_ready
from retry_hamilton_dcg_coordinated import rows, corridor


def raw_guard(now, start, arrival=False):
    for channel in (1, 2):
        delta = (now[channel] - start[channel]) * (1 if channel == 1 else -1)
        lo = .5 if arrival else 0
        if not math.isfinite(delta) or not lo - .25 <= delta <= .75:
            raise RuntimeError(f'Raw Y drive channel {channel} moved {delta:.3f} mm outward; expected {lo}..0.5')


async def run(h, ticket, execute):
    reads = {C.PrepGetPositions, C.PrepGetPlateHeld, C.PrepGetTipDefinitionHeld,
             C.PrepGetIsInitialized, C.PrepGetChannelBounds, DoorClosed, C.PrepGetIsEnclosurePresent}
    writes = {MoveYRelative, C.PrepMethodBegin, C.PrepMethodEnd, C.PrepMethodAbort}
    raw_requests = set()
    class Driver(PrepDriver):
        async def setup(self, **kw): raise RuntimeError('No setup')
        async def stop(self, **kw): raise RuntimeError('Transport close only')
        async def send_command(self, cmd, **kw):
            raw_read = type(cmd) is C.PrepProbeRequest and (cmd.dest, cmd.interface_id, cmd.command_id) in raw_requests
            if (type(cmd) not in reads | writes and not raw_read) or (type(cmd) in writes and not execute):
                raise RuntimeError('Command prohibited')
            if type(cmd) in writes:
                h.journal(ticket, 'dual_feedback_request', dict(command=type(cmd).__name__, parameters=to_jsonable(cmd)))
            result = await super().send_command(cmd, **kw)
            if type(cmd) in writes:
                h.journal(ticket, 'dual_feedback_response', dict(command=type(cmd).__name__, result=to_jsonable(result)))
            return result
        async def request_by_name(self, dest, name):
            if name != 'GetPosition': raise RuntimeError('Only raw position requests allowed')
            return await super().request_by_name(dest, name)
    def make():
        return Driver(deck=Deck(name='dual_feedback', size_x=300, size_y=430, size_z=200),
                      io=HamiltonTCPClient(host='192.168.100.102', port=2000, read_timeout=5, write_timeout=5))
    motion, monitor, abort = make(), make(), make()
    began = False
    pending = None
    folder = h.folder / PRIOR
    samples = []
    async def interlocks():
        for cls in (DoorClosed, C.PrepGetIsEnclosurePresent):
            if not (await monitor.send_command(cls())).value: raise RuntimeError('Door/enclosure open')
    async def raw_at(addr):
        data = await monitor.request_by_name(addr, 'GetPosition')
        return float(C.PrepYDriveGetPosition.parse_response_parameters(data).position)
    try:
        for d in (motion, monitor, abort): await asyncio.wait_for(d._open(), 20)
        await interlocks()
        await asyncio.to_thread(rest_ready, h)
        if not (await monitor.send_command(C.PrepGetIsInitialized())).value: raise RuntimeError('Not initialized')
        if (await monitor.send_command(C.PrepGetPlateHeld())).value: raise RuntimeError('Expected released tool')
        if to_jsonable(await monitor.send_command(C.PrepGetTipDefinitionHeld()))['value'].get('label') != 'DCG':
            raise RuntimeError('Expected DCG')
        start = rows(to_jsonable(await monitor.send_command(C.PrepGetPositions())))
        corridor(start, total_target(4.5), total_target(4.5), arrival=True)
        goal = total_target(5)
        for b in to_jsonable(await monitor.send_command(C.PrepGetChannelBounds()))['bounds']:
            for axis in ('x', 'y', 'z'):
                if not b[axis+'_min'] <= goal[b['channel']]['position_'+axis] <= b[axis+'_max']:
                    raise RuntimeError('Target outside native bounds')
        drives = (await monitor.request_channel_drives(root_name='Ngc')).ydrive_addrs
        if len(drives) != 2: raise RuntimeError('Expected two discovered Y drives')
        mapping = {}
        for addr in drives:
            method = await monitor.request_method_by_name(addr, 'GetPosition')
            if method.to_dict()['params']: raise RuntimeError('Unexpected position signature')
            raw_requests.add((addr, method.interface_id, method.method_id))
            value = await raw_at(addr)
            candidates = [c for c in (1, 2) if abs(value-start[c]['position_y']) < 2.5]
            if len(candidates) != 1 or candidates[0] in mapping: raise RuntimeError('Ambiguous raw-drive mapping')
            mapping[candidates[0]] = addr
        async def sample(phase):
            raw = {c: await raw_at(a) for c, a in mapping.items()}
            positions = rows(to_jsonable(await monitor.send_command(C.PrepGetPositions())))
            record = dict(phase=phase, at=time.time(), raw=raw, positions=positions)
            samples.append(record)
            if execute: h.journal(ticket, 'dual_feedback_sample', record)
            return positions, raw
        _, baseline = await sample('baseline')
        for _ in range(5):
            pos, raw = await sample('stationary')
            corridor(pos, start, start, arrival=True)
            if any(abs(raw[c]-baseline[c]) > .1 for c in (1,2)): raise RuntimeError('Raw position unstable while stopped')
            await asyncio.sleep(.05)
        method = await motion.request_method_by_name(MoveYRelative.firmware_path, 'MoveYRelative')
        if (method.interface_id, method.method_id) != (1,11): raise RuntimeError('Relative command signature changed')
        addr = await motion.resolve_path(MoveYRelative.firmware_path)
        structures = await motion.io.introspection.get_structs(addr,1)
        if structures[1].name != 'ChannelYDistance' or list(structures[1].fields) != ['DefaultValues','Channel','YDistance']:
            raise RuntimeError('Relative payload structure changed')
        print(json.dumps(dict(motion_sent=False, start=start, goal=goal, raw=baseline,
                              mapping={c:str(a) for c,a in mapping.items()})), flush=True)
        if not execute: return
        with (folder / 'dual_feedback_retry_attempt.json').open('x') as f:
            json.dump(dict(start=start, goal=goal, raw=baseline, empty_confirmed=True), f)
        began = True
        await motion.send_command(C.PrepMethodBegin(automatic_pause=True))
        pos, raw = await sample('before_move')
        corridor(pos, start, start, arrival=True)
        if any(abs(raw[c]-baseline[c]) > .1 for c in (1,2)): raise RuntimeError('Raw position changed before motion')
        await interlocks()
        pending = asyncio.create_task(motion.send_command(MoveYRelative(.5), read_timeout=5))
        while not pending.done():
            await asyncio.wait({pending}, timeout=.02)
            pos, raw = await sample('moving')
            raw_guard(raw, baseline)
            corridor(pos, start, goal)
        await pending
        for _ in range(5):
            pos, raw = await sample('arrival')
            raw_guard(raw, baseline, arrival=True)
            corridor(pos, start, goal, arrival=True)
            await asyncio.sleep(.1)
        await interlocks()
        await motion.send_command(C.PrepMethodEnd())
        began = False
        result = dict(status='single_empty_step_passed', total_opening_per_jaw_mm=5,
                      loaded_release_validated=False, samples=samples)
        (folder/'dual_feedback_retry_result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps({k:v for k,v in result.items() if k!='samples'}), flush=True)
    except BaseException as error:
        if began:
            try: await asyncio.wait_for(abort.send_command(C.PrepMethodAbort(), read_timeout=3),4)
            except BaseException as stop_error: h.journal(ticket, 'dual_feedback_abort_error', str(stop_error))
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        if execute:
            result = dict(status='stopped', error=str(error), samples=samples)
            h.journal(ticket, 'dual_feedback_retry_failed', result)
            (folder/'dual_feedback_retry_result.json').write_text(json.dumps(result, indent=2))
        raise
    finally:
        for d in (motion,monitor,abort): await d._close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-empty-confirmed', action='store_true')
    args = parser.parse_args()
    h = HamiltonPrep()
    rest_ready(h)
    ticket = json.loads((h.folder/'active.json').read_text())
    if ticket.get('request_id') != PRIOR or ticket.get('status') != 'failed_or_uncertain':
        raise RuntimeError('Wrong stopped batch')
    if args.execute_empty_confirmed:
        lock = h.folder/'dcg48_execution.lock'
        with lock.open('x') as f: f.write(PRIOR)
        try: asyncio.run(run(h,ticket,True))
        finally: lock.unlink()
    else:
        asyncio.run(run(h,ticket,False))
