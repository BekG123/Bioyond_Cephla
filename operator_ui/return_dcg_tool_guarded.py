"""Return the empty DCG to its dock while watching both Y-drive encoders.

Default read-only. --execute-empty-confirmed sends MoveZUpToSafe, DropTool and
MoveZUpToSafe at X/Z speed scale 5. No park, fault reset, or plate handling.
The dock needs the jaws 35 mm apart (2026-11-08 return). The front drive has
stopped following away from that spacing, and reported positions mirror the
encoder during a move, so the only usable check is the encoder-based spacing:
it must stay at the dock spacing for the whole return, or the move is aborted.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import time
from uuid import uuid4
from analyze_hamilton_inward_motion import drive_status
from hamilton_dcg_transfer import C, PrepDriver, HamiltonTCPClient, Deck, HamiltonPrep, DoorClosed, to_jsonable, rest_ready, PIP
from retry_hamilton_dcg_coordinated import rows
from reseat_hamilton_coordinated_stop import PRIOR

DOCK = {1: (289.41, 295.8), 2: (289.41, 260.8)}  # coordinator X, Y at the dock on 2026-11-08
SPACING = (35.5, 39.7)  # mm between Y-drive encoders; hand-closed jaws read 37.7-38.2, docked about 37.1
SCALE = 5


def spacing_ok(rear_encoder, front_encoder):
    return SPACING[0] <= rear_encoder - front_encoder <= SPACING[1]


async def run(h, ticket, folder, execute):
    reads = {C.PrepGetPositions, C.PrepGetPlateHeld, C.PrepGetTipDefinitionHeld, C.PrepGetIsInitialized,
             C.PrepGetXSpeedScale, C.PrepGetZSpeedScale, C.PrepIsParked, DoorClosed, C.PrepGetIsEnclosurePresent}
    writes = {C.PrepMethodBegin, C.PrepMethodEnd, C.PrepMethodAbort, C.PrepMoveZUpToSafe, C.PrepDropTool,
              C.PrepSetXSpeedScale, C.PrepSetZSpeedScale}
    status_requests = set()
    class Driver(PrepDriver):
        async def setup(self, **kw): raise RuntimeError('No setup')
        async def stop(self, **kw): raise RuntimeError('Transport close only')
        async def send_command(self, cmd, **kw):
            probe = type(cmd) is C.PrepProbeRequest and (cmd.dest, cmd.interface_id, cmd.command_id) in status_requests
            if (type(cmd) not in reads | writes and not probe) or (type(cmd) in writes and not execute):
                raise RuntimeError('Command prohibited')
            if type(cmd) in writes:
                h.journal(ticket, 'tool_return_request', dict(command=type(cmd).__name__, parameters=to_jsonable(cmd)))
            result = await super().send_command(cmd, **kw)
            if type(cmd) in writes:
                h.journal(ticket, 'tool_return_response', dict(command=type(cmd).__name__, result=to_jsonable(result)))
            return result
    def make():
        return Driver(deck=Deck(name='tool_return', size_x=300, size_y=430, size_z=200),
                      io=HamiltonTCPClient(host='192.168.100.102', port=2000, read_timeout=60, write_timeout=5))
    motion, coord, abort, drive_a, drive_b = (make() for _ in range(5))
    drivers = (motion, coord, abort, drive_a, drive_b)
    samples, events, faults = [], [], []
    latest = {}
    phase = ['baseline']
    done, tripped = asyncio.Event(), asyncio.Event()
    began = False
    pending = None

    def mark(name): events.append(dict(event=name, at=time.time()))
    def trip(error): faults.append(error); tripped.set()
    async def read_status(conn, request):
        data = await conn.send_command(C.PrepProbeRequest(dest=request[0], interface_id=request[1], command_id=request[2]), read_timeout=2)
        return drive_status(data.hex())
    try:
        for d in drivers: await asyncio.wait_for(d._open(), 20)
        for path, name, expected in ((PIP, 'MoveZUpToSafe', 28), (PIP, 'DropTool', 16)):
            method = await motion.request_method_by_name(path, name)
            if (method.interface_id, method.method_id) != (1, expected): raise RuntimeError('Firmware signature changed: ' + name)
        state = dict(door_closed=(await coord.send_command(DoorClosed())).value,
                     enclosure=(await coord.send_command(C.PrepGetIsEnclosurePresent())).value,
                     initialized=(await coord.send_command(C.PrepGetIsInitialized())).value,
                     plate_held=(await coord.send_command(C.PrepGetPlateHeld())).value,
                     tool=to_jsonable(await coord.send_command(C.PrepGetTipDefinitionHeld()))['value'],
                     scales=[(await coord.send_command(C.PrepGetXSpeedScale())).value, (await coord.send_command(C.PrepGetZSpeedScale())).value])
        start = rows(to_jsonable(await coord.send_command(C.PrepGetPositions())))
        addresses = (await coord.request_channel_drives(root_name='Ngc')).ydrive_addrs
        if len(addresses) != 2: raise RuntimeError('Expected two discovered Y drives')
        found = []
        for conn, addr in zip((drive_a, drive_b), addresses):
            method = await coord.request_method_by_name(addr, 'GetStatus')
            if method.to_dict()['params']: raise RuntimeError('Unexpected GetStatus signature')
            request = (addr, method.interface_id, method.method_id)
            status_requests.add(request)
            found.append((await read_status(conn, request), conn, request))
        # A hand-moved jaw leaves reported Y stale, so order by encoder: the rear
        # channel (1) is always at the larger Y.
        found.sort(key=lambda item: -item[0]['encoder_position_mm'])
        if found[0][0]['encoder_position_mm'] - found[1][0]['encoder_position_mm'] < 15: raise RuntimeError('Ambiguous Y-drive mapping')
        mapping = {c: (conn, request) for c, (_, conn, request) in zip((1, 2), found)}
        latest.update({c: status for c, (status, _, _) in zip((1, 2), found)})

        async def drive_loop(channel):
            conn, request = mapping[channel]
            try:
                while not done.is_set():
                    latest[channel] = await read_status(conn, request)
                    record = dict(phase=phase[0], at=time.time(), rear=latest[1]['encoder_position_mm'], front=latest[2]['encoder_position_mm'])
                    samples.append(record)
                    # The two reads are a few ms apart; at this speed that is well under the margin.
                    if not spacing_ok(record['rear'], record['front']):
                        raise RuntimeError(f"Encoder jaw spacing {record['rear'] - record['front']:.2f} mm left the dock range")
            except BaseException as error: trip(error)
        async def coord_loop():
            last_rest = 0
            try:
                while not done.is_set():
                    p = rows(to_jsonable(await coord.send_command(C.PrepGetPositions(), read_timeout=2)))
                    samples.append(dict(phase=phase[0], at=time.time(), positions=p))
                    for cls in (DoorClosed, C.PrepGetIsEnclosurePresent):
                        if not (await coord.send_command(cls(), read_timeout=2)).value: raise RuntimeError('Door/enclosure open')
                    if began and time.monotonic() - last_rest > .5:
                        if await asyncio.to_thread(h.call, 'GET', 'errors/check-for-pending-errors'): raise RuntimeError('Controller error')
                        last_rest = time.monotonic()
            except BaseException as error: trip(error)
        async def guarded(cmd, name):
            nonlocal pending
            phase[0] = name; mark(name + '_request'); print(name, flush=True)
            pending = asyncio.create_task(motion.send_command(cmd, read_timeout=60))
            waiter = asyncio.create_task(tripped.wait())
            await asyncio.wait({pending, waiter}, return_when=asyncio.FIRST_COMPLETED)
            waiter.cancel()
            if tripped.is_set(): raise faults[0]
            result = await pending; mark(name + '_reply')
            return result

        gaps = {c: latest[c]['position_minus_encoder_mm'] for c in (1, 2)}
        spacing = latest[1]['encoder_position_mm'] - latest[2]['encoder_position_mm']
        report = dict(motion_sent=False, state=state, start=start, encoder_spacing_mm=spacing, counter_minus_encoder_mm=gaps, dock=DOCK)
        try:
            await asyncio.to_thread(rest_ready, h); report['rest_ready'] = True
        except Exception as error:
            report['rest_ready'] = False; report['rest_error'] = str(error)
        blockers = []
        if not state['door_closed'] or not state['enclosure']: blockers.append('door/enclosure open')
        if not state['initialized']: blockers.append('not initialized')
        if state['plate_held']: blockers.append('firmware records a held plate')
        if state['tool'].get('label') != 'DCG': blockers.append('DCG not attached')
        if not report['rest_ready']: blockers.append('REST not ready: ' + report['rest_error'])
        if not spacing_ok(latest[1]['encoder_position_mm'], latest[2]['encoder_position_mm']):
            blockers.append(f'jaws not at dock spacing (encoder spacing {spacing:.2f} mm; need {SPACING[0]}-{SPACING[1]}); push the front jaw closed by hand')
        if any(abs(g) > .15 for g in gaps.values()): blockers.append('a drive counter disagrees with its encoder')
        report['blockers'] = blockers
        (folder / 'preflight.json').write_text(json.dumps(report, indent=2, default=str))
        print(json.dumps(report, indent=2, default=str), flush=True)
        if not execute: return report
        if blockers: raise RuntimeError('Preflight blocked: ' + '; '.join(blockers))

        h.journal(ticket, 'tool_return_begin', report)
        samplers = [asyncio.create_task(drive_loop(1)), asyncio.create_task(drive_loop(2)), asyncio.create_task(coord_loop())]
        began = True
        await guarded(C.PrepMethodBegin(automatic_pause=True), 'begin')
        await guarded(C.PrepSetXSpeedScale(value=SCALE), 'x_scale'); await guarded(C.PrepSetZSpeedScale(value=SCALE), 'z_scale')
        await guarded(C.PrepMoveZUpToSafe(channels=[1, 2]), 'raise_to_safe')
        await guarded(C.PrepDropTool(), 'return_tool')
        # The jaws stay in the dock from here; channel spacing is no longer a tool constraint.
        done.set(); await asyncio.gather(*samplers)
        if faults: raise faults[0]
        tool = to_jsonable(await coord.send_command(C.PrepGetTipDefinitionHeld()))['value']
        if tool.get('is_tool'): raise RuntimeError('Tool return not confirmed')
        await motion.send_command(C.PrepMoveZUpToSafe(channels=[1, 2]), read_timeout=60); mark('raise_after_return')
        await motion.send_command(C.PrepSetXSpeedScale(value=state['scales'][0])); await motion.send_command(C.PrepSetZSpeedScale(value=state['scales'][1]))
        await motion.send_command(C.PrepMethodEnd()); began = False
        final = rows(to_jsonable(await coord.send_command(C.PrepGetPositions())))
        spans = [s['rear'] - s['front'] for s in samples if 'rear' in s and s['phase'] == 'return_tool']
        return dict(status='tool_returned', tool=tool, final_positions=final, parked=(await coord.send_command(C.PrepIsParked())).value,
                    encoder_spacing_during_return_mm=[min(spans), max(spans)], events=events)
    except BaseException as error:
        if began:
            mark('abort_request')
            try: await asyncio.wait_for(abort.send_command(C.PrepMethodAbort(), read_timeout=3), 4); mark('abort_reply')
            except BaseException as stop_error: h.journal(ticket, 'tool_return_abort_error', str(stop_error))
        if pending is not None:
            pending.cancel(); await asyncio.gather(pending, return_exceptions=True)
        if execute:
            (folder / 'result.json').write_text(json.dumps(dict(status='stopped', error=str(error), events=events), indent=2))
            h.journal(ticket, 'tool_return_failed', dict(error=str(error), events=events))
        raise
    finally:
        done.set()
        (folder / 'samples.json').write_text(json.dumps(dict(samples=samples, events=events), default=str))
        for d in drivers:
            try: await d._close()
            except Exception: pass


if __name__ == '__main__':
    import logging
    logging.disable(logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-empty-confirmed', action='store_true')
    args = parser.parse_args()
    h = HamiltonPrep()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = h.folder / 'release_investigation_20261109' / (('tool_return_' if args.execute_empty_confirmed else 'tool_return_preflight_') + stamp)
    folder.mkdir(parents=True)
    ticket = dict(request_id='dcg_tool_return_' + uuid4().hex, prior_request_id=PRIOR)
    if not args.execute_empty_confirmed:
        asyncio.run(run(h, ticket, folder, False))
    else:
        owner = json.loads((h.folder / 'active.json').read_text())
        if owner.get('request_id') != PRIOR or owner.get('status') != 'failed_or_uncertain': raise RuntimeError('Wrong stopped batch')
        lock = h.folder / 'dcg48_execution.lock'
        with lock.open('x') as f: f.write(ticket['request_id'])
        try:
            result = asyncio.run(run(h, ticket, folder, True))
            (folder / 'result.json').write_text(json.dumps(result, indent=2, default=str))
            h.journal(ticket, 'tool_return_result', result)
            print(json.dumps(result, indent=2, default=str), flush=True)
        finally: lock.unlink()
    print(folder)
