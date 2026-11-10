"""Empty-jaw Y opening steps that record Position AND EncoderPosition per Y drive.

Default read-only: reports state and a stationary baseline, sends no writes.
--execute-empty-confirmed repeats the previously anomalous MoveYRelative(0.5 mm,
1 mm/s) once from the current pose. --front-to Y instead walks only the front
jaw outward to coordinator Y in <=0.5 mm steps of the same command, stopping
after the first step that does not follow. No lift, retreat, park, fault reset,
or settings change. Each step is firmware-bounded; inward readings below the
hard limit are recorded rather than aborted, because the late host abort never
prevented the earlier steps and would only truncate the trace.
"""
import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import statistics
import time
from pathlib import Path
from uuid import uuid4
from analyze_hamilton_inward_motion import drive_status
from check_hamilton_wider_release import MoveYRelative, ChannelYDistance
from hamilton_dcg_transfer import C, PrepDriver, HamiltonTCPClient, Deck, HamiltonPrep, DoorClosed, to_jsonable, rest_ready
from retry_hamilton_dcg_coordinated import rows
from reseat_hamilton_coordinated_stop import PRIOR

ROOT = Path(__file__).resolve().parent
STEP = .5
HARD_Y = 4.0      # mm from the step start, any feedback field, either direction
HARD_XZ = .25
MIN_SPACING = 30  # mm between jaw references; operator-confirmed empty start at 35.4 mm on 2026-11-09
SIGN = {1: 1, 2: -1}  # outward direction: channel 1 rear (+Y), channel 2 front (-Y)


@dataclass(frozen=True)
class MoveYStep(C.PrepCommand[None]):
    """MoveYRelative with per-channel outward distances; same wire layout and 1 mm/s."""
    command_id = 11
    firmware_path = MoveYRelative.firmware_path
    outward_mm: tuple  # ((channel, outward distance), ...)
    def build_parameters(self):
        if not self.outward_mm or any(c not in SIGN or not 0 < d <= STEP for c, d in self.outward_mm):
            raise ValueError('Diagnostic steps limited to 0.5 mm outward per jaw')
        return C.HoiParams().add([ChannelYDistance(c, SIGN[c] * d) for c, d in self.outward_mm], C.StructArray()).add(1., C.F32)
    @classmethod
    def parse_response_parameters(cls, data): return None


def front_plan(current_y, target_y):
    """Front-jaw-only steps: a short first step, then whole 0.5 mm steps ending on target."""
    distance = current_y - target_y
    if not 0 < distance <= 60: raise ValueError('Front target must be 0..60 mm outward of the current pose')
    whole, first = divmod(round(distance, 4), STEP)
    return ([{2: round(first, 4)}] if first > .01 else []) + [{2: STEP}] * int(whole)


def outward(channel, value, start):
    return (value - start) * SIGN[channel]


def summarize(before, active, channel, field):
    """Outward travel of one feedback field relative to the preceding stationary samples."""
    base = statistics.fmean(s[field] for s in before if s['channel'] == channel)
    travel = [outward(channel, s[field], base) for s in active if s['channel'] == channel]
    return dict(baseline_mm=base, most_inward_mm=-min(travel + [0]), most_outward_mm=max(travel + [0]),
                final_outward_mm=statistics.fmean(travel[-5:]) if travel else None, samples_during_move=len(travel))


def classify(counter, encoder, expected=STEP, tolerance=.15):
    """Findings.md decision table for one drive. Thresholds are in mm."""
    counter_in, encoder_in = counter['most_inward_mm'] > 2 * tolerance, encoder['most_inward_mm'] > 2 * tolerance
    if counter_in and encoder_in: return 'both_inward_actual_reversal'
    if counter_in: return 'counter_jump_only_reporting_or_resync'
    if encoder_in: return 'encoder_inward_only_unexpected'
    reached = lambda v: v['final_outward_mm'] is not None and abs(v['final_outward_mm'] - expected) <= tolerance
    if reached(counter) and not reached(encoder): return 'counter_outward_encoder_not_following'
    if reached(counter) and reached(encoder): return 'no_anomaly_both_followed'
    return 'inconclusive'


async def run(h, ticket, folder, execute, front_to=None, no_tool=False):
    reads = {C.PrepGetPositions, C.PrepGetPlateHeld, C.PrepGetTipDefinitionHeld, C.PrepGetIsInitialized,
             C.PrepGetChannelBounds, C.PrepIsParked, DoorClosed, C.PrepGetIsEnclosurePresent}
    writes = {MoveYStep, C.PrepMethodBegin, C.PrepMethodEnd, C.PrepMethodAbort}
    status_requests = set()
    class Driver(PrepDriver):
        async def setup(self, **kw): raise RuntimeError('No setup')
        async def stop(self, **kw): raise RuntimeError('Transport close only')
        async def send_command(self, cmd, **kw):
            probe = type(cmd) is C.PrepProbeRequest and (cmd.dest, cmd.interface_id, cmd.command_id) in status_requests
            if (type(cmd) not in reads | writes and not probe) or (type(cmd) in writes and not execute):
                raise RuntimeError('Command prohibited')
            if type(cmd) in writes:
                h.journal(ticket, 'encoder_test_request', dict(command=type(cmd).__name__, parameters=to_jsonable(cmd)))
            result = await super().send_command(cmd, **kw)
            if type(cmd) in writes:
                h.journal(ticket, 'encoder_test_response', dict(command=type(cmd).__name__, result=to_jsonable(result)))
            return result
    def make():
        return Driver(deck=Deck(name='encoder_test', size_x=300, size_y=430, size_z=200),
                      io=HamiltonTCPClient(host='192.168.100.102', port=2000, read_timeout=5, write_timeout=5))
    # One connection per sampler so drive reads are not queued behind each other.
    motion, coord, abort, drive_a, drive_b = (make() for _ in range(5))
    drivers = (motion, coord, abort, drive_a, drive_b)
    drive_samples, coord_samples = defaultdict(list), defaultdict(list)  # keyed by phase
    events, faults, steps = [], [], []
    phase = ['baseline']
    done, tripped = asyncio.Event(), asyncio.Event()
    began = False
    pending = None

    def mark(name, **extra):
        events.append(dict(event=name, at=time.time(), **extra))
    def trip(error):
        faults.append(error); tripped.set()
    async def interlocks():
        for cls in (DoorClosed, C.PrepGetIsEnclosurePresent):
            if not (await coord.send_command(cls(), read_timeout=2)).value: raise RuntimeError('Door/enclosure open')
    async def read_status(conn, request):
        t0 = time.time()
        data = await conn.send_command(C.PrepProbeRequest(dest=request[0], interface_id=request[1], command_id=request[2]), read_timeout=2)
        return dict(t0=t0, t1=time.time(), **drive_status(data.hex()))

    try:
        for d in drivers: await asyncio.wait_for(d._open(), 20)
        state = dict(door_closed=(await coord.send_command(DoorClosed())).value,
                     enclosure=(await coord.send_command(C.PrepGetIsEnclosurePresent())).value,
                     initialized=(await coord.send_command(C.PrepGetIsInitialized())).value,
                     plate_held=(await coord.send_command(C.PrepGetPlateHeld())).value,
                     parked=(await coord.send_command(C.PrepIsParked())).value,
                     tool=to_jsonable(await coord.send_command(C.PrepGetTipDefinitionHeld()))['value'])
        start = rows(to_jsonable(await coord.send_command(C.PrepGetPositions())))
        bounds = {b['channel']: b for b in to_jsonable(await coord.send_command(C.PrepGetChannelBounds()))['bounds']}
        addresses = (await coord.request_channel_drives(root_name='Ngc')).ydrive_addrs
        if len(addresses) != 2: raise RuntimeError('Expected two discovered Y drives')
        mapping = {}
        for conn, addr in zip((drive_a, drive_b), addresses):
            method = await coord.request_method_by_name(addr, 'GetStatus')
            if method.to_dict()['params']: raise RuntimeError('Unexpected GetStatus signature')
            request = (addr, method.interface_id, method.method_id)
            status_requests.add(request)
            first = await read_status(conn, request)
            # Counter and encoder may disagree by ~1 mm; the jaws are tens of mm apart.
            near = [c for c in (1, 2) if abs(first['position_mm'] - start[c]['position_y']) < 5]
            if len(near) != 1 or near[0] in mapping: raise RuntimeError('Ambiguous Y-drive mapping')
            mapping[near[0]] = (conn, request)

        reference, window = {}, dict(start)  # guard references, refreshed after every accepted step
        def gap(c):
            # Encoder minus counter. A stopped jaw may sit off its counter; the next
            # move is expected to close that gap, so the window spans both readings.
            return reference[c]['encoder_position_mm'] - reference[c]['position_mm'] if c in reference else 0
        def hard_guard_drive(s):
            values = reference[s['channel']].values()
            for field in ('position_mm', 'encoder_position_mm'):
                if not min(values) - HARD_Y <= s[field] <= max(values) + HARD_Y:
                    raise RuntimeError(f"Channel {s['channel']} {field} left the {HARD_Y} mm test window")
        def hard_guard_coord(p):
            for c in (1, 2):
                offset = p[c]['position_y'] - window[c]['position_y']
                if not min(0, gap(c)) - HARD_Y <= offset <= max(0, gap(c)) + HARD_Y: raise RuntimeError(f'Channel {c} reported Y left the test window')
                if any(abs(p[c][k] - start[c][k]) > HARD_XZ for k in ('position_x', 'position_z')):
                    raise RuntimeError(f'Channel {c} X/Z moved during a Y-only step')
        async def drive_loop(channel):
            conn, request = mapping[channel]
            try:
                while not done.is_set():
                    s = dict(phase=phase[0], channel=channel, **await read_status(conn, request))
                    drive_samples[s['phase']].append(s)
                    if reference: hard_guard_drive(s)
            except BaseException as error: trip(error)
        async def coord_loop():
            try:
                while not done.is_set():
                    t0 = time.time()
                    p = rows(to_jsonable(await coord.send_command(C.PrepGetPositions(), read_timeout=2)))
                    coord_samples[phase[0]].append(dict(phase=phase[0], t0=t0, t1=time.time(), positions=p))
                    hard_guard_coord(p)
                    await interlocks()
            except BaseException as error: trip(error)
        async def hold(seconds):
            try: await asyncio.wait_for(tripped.wait(), seconds)
            except asyncio.TimeoutError: return
            raise faults[0]
        def stationary(name):
            for c in (1, 2):
                for field in ('position_mm', 'encoder_position_mm'):
                    values = [s[field] for s in drive_samples[name] if s['channel'] == c]
                    if len(values) < 5 or max(values) - min(values) > .05: raise RuntimeError(f'Channel {c} {field} not stable while stopped ({name})')
                    reference.setdefault(c, {})[field] = statistics.fmean(values[-5:])

        samplers = [asyncio.create_task(drive_loop(1)), asyncio.create_task(drive_loop(2)), asyncio.create_task(coord_loop())]
        await hold(1.0)
        stationary('baseline')
        baseline = {c: dict(v) for c, v in reference.items()}
        plan = [{1: STEP, 2: STEP}] if front_to is None else front_plan(start[2]['position_y'], front_to)
        goal = {c: start[c]['position_y'] + SIGN[c] * sum(p.get(c, 0) for p in plan) for c in (1, 2)}
        report = dict(motion_sent=False, state=state, start=start, goal_y=goal, steps_planned=len(plan), first_step=plan[0], bounds=bounds,
                      mapping={c: str(r[0]) for c, (_, r) in mapping.items()},
                      baseline={c: dict(v, position_minus_encoder_mm=v['position_mm'] - v['encoder_position_mm']) for c, v in baseline.items()},
                      baseline_samples_per_drive=len(drive_samples['baseline']) // 2, jaw_spacing_mm=start[1]['position_y'] - start[2]['position_y'])
        try:
            rest = await asyncio.to_thread(rest_ready, h)
            report['rest_ready'] = True; report['rest_global_state'] = rest['global_state']
        except Exception as error:
            report['rest_ready'] = False; report['rest_error'] = str(error)
        blockers = []
        if not state['door_closed'] or not state['enclosure']: blockers.append('door/enclosure open')
        if not state['initialized']: blockers.append('not initialized')
        if state['plate_held']: blockers.append('firmware records a held plate')
        if no_tool:
            if state['tool'].get('is_tool') or state['tool'].get('id'): blockers.append('channels must be bare for the no-tool comparison')
        elif state['tool'].get('label') != 'DCG': blockers.append('DCG not attached')
        if not report['rest_ready']: blockers.append('REST not ready: ' + report['rest_error'])
        if report['jaw_spacing_mm'] < MIN_SPACING: blockers.append('jaws closer than the reviewed test spacing')
        for c in (1, 2):
            if not bounds[c]['y_min'] + HARD_Y <= goal[c] <= bounds[c]['y_max'] - HARD_Y: blockers.append(f'channel {c} goal too near native Y bounds')
        method = await motion.request_method_by_name(MoveYStep.firmware_path, 'MoveYRelative')
        structures = await motion.io.introspection.get_structs(await motion.resolve_path(MoveYStep.firmware_path), 1)
        if ((method.interface_id, method.method_id) != (1, 11) or structures[1].name != 'ChannelYDistance'
                or list(structures[1].fields) != ['DefaultValues', 'Channel', 'YDistance']):
            blockers.append('MoveYRelative signature changed')
        report['blockers'] = blockers
        (folder / 'preflight.json').write_text(json.dumps(report, indent=2, default=str))
        print(json.dumps(report, indent=2, default=str), flush=True)
        if not execute: return report
        if blockers: raise RuntimeError('Preflight blocked: ' + '; '.join(blockers))

        h.journal(ticket, 'encoder_test_begin', report)
        began = True
        phase[0] = 'after_begin'; mark('method_begin_request')
        await motion.send_command(C.PrepMethodBegin(automatic_pause=True)); mark('method_begin_reply')
        await hold(.5)
        stationary('after_begin')
        begin_shift = {c: reference[c]['position_mm'] - baseline[c]['position_mm'] for c in (1, 2)}
        before = 'after_begin'
        stopped_on = None
        for index, distances in enumerate(plan):
            move, settle = f'move_{index}', f'settle_{index}'
            if index % 10 == 9 and await asyncio.to_thread(h.call, 'GET', 'errors/check-for-pending-errors'):
                raise RuntimeError('Controller reported a pending error')
            phase[0] = move; mark('move_request', step=index, outward_mm=distances)
            pending = asyncio.create_task(motion.send_command(MoveYStep(tuple(sorted(distances.items()))), read_timeout=5))
            waiter = asyncio.create_task(tripped.wait())
            await asyncio.wait({pending, waiter}, return_when=asyncio.FIRST_COMPLETED)
            waiter.cancel()
            if tripped.is_set(): raise faults[0]
            await pending; mark('move_reply', step=index)
            phase[0] = settle
            await hold(1.0 if index == len(plan) - 1 else .3)
            active = drive_samples[move] + drive_samples[settle]
            record = dict(step=index, outward_mm=distances, channels={})
            for c in (1, 2):
                counter, encoder = (summarize(drive_samples[before], active, c, f) for f in ('position_mm', 'encoder_position_mm'))
                reported = [outward(c, s['positions'][c]['position_y'], window[c]['position_y']) for s in coord_samples[move] + coord_samples[settle]]
                expected = distances.get(c, 0)
                verdict = classify(counter, encoder, expected)
                record['channels'][c] = dict(counter=counter, encoder=encoder, verdict=verdict, expected_mm=expected,
                                             coordinator_most_inward_mm=-min(reported + [0]), coordinator_final_outward_mm=reported[-1] if reported else None)
                settled = [s for s in drive_samples[settle] if s['channel'] == c][-5:]
                end_gap = statistics.fmean(s['position_minus_encoder_mm'] for s in settled)
                reached = abs(record['channels'][c]['coordinator_final_outward_mm'] - expected) <= .15 and abs(end_gap) <= .15
                # A jaw that started off its counter is allowed one correcting step.
                record['channels'][c].update(start_gap_mm=-gap(c), end_gap_mm=end_gap, resync_step=abs(gap(c)) > .15 and reached)
                if record['channels'][c]['resync_step']: continue
                if verdict != 'no_anomaly_both_followed' or record['channels'][c]['coordinator_most_inward_mm'] > .3: stopped_on = index
            steps.append(record)
            if stopped_on is not None: break
            # Slide the hard-limit references to the accepted new pose.
            window = coord_samples[settle][-1]['positions']
            for c in (1, 2):
                for field in ('position_mm', 'encoder_position_mm'):
                    # Filter by channel before slicing: one stalled read can leave the tail all one channel.
                    reference[c][field] = statistics.fmean([s[field] for s in drive_samples[settle] if s['channel'] == c][-5:])
            before = settle
            if index % 10 == 0: print(f"step {index + 1}/{len(plan)} ok; front Y {window[2]['position_y']:.3f}", flush=True)
        mark('method_end_request')
        await motion.send_command(C.PrepMethodEnd()); began = False; mark('method_end_reply')
        phase[0] = 'after_end'
        await hold(.7)
        done.set(); await asyncio.gather(*samplers)
        if faults: raise faults[0]
        final = rows(to_jsonable(await coord.send_command(C.PrepGetPositions())))
        last = {c: [s for s in drive_samples['after_end'] if s['channel'] == c][-1] for c in (1, 2)}
        return dict(status='stopped_on_first_anomalous_step' if stopped_on is not None else 'all_steps_followed',
                    steps_planned=len(plan), steps_run=len(steps), anomalous_step=stopped_on, velocity_mm_s=1.0,
                    counter_shift_on_method_begin_mm=begin_shift, start=start, final_positions=final,
                    final_drive_status={c: {k: last[c][k] for k in ('position_mm', 'encoder_position_mm', 'position_minus_encoder_mm')} for c in (1, 2)},
                    steps=steps, events=events, loaded_release_validated=False, retreat=False,
                    caveat='EncoderPosition independence from Position is assumed from the firmware field names, not proven.')
    except BaseException as error:
        if began:
            mark('abort_request')
            try: await asyncio.wait_for(abort.send_command(C.PrepMethodAbort(), read_timeout=3), 4); mark('abort_reply')
            except BaseException as stop_error: h.journal(ticket, 'encoder_test_abort_error', str(stop_error))
        if pending is not None:
            pending.cancel(); await asyncio.gather(pending, return_exceptions=True)
        if execute:
            (folder / 'result.json').write_text(json.dumps(dict(status='stopped', error=str(error), steps=steps, events=events), indent=2, default=str))
            h.journal(ticket, 'encoder_test_failed', dict(error=str(error), steps_run=len(steps)))
        raise
    finally:
        done.set()
        (folder / 'samples.json').write_text(json.dumps(dict(drive=drive_samples, coordinator=coord_samples, events=events), default=str))
        for d in drivers:
            try: await d._close()
            except Exception: pass


def capture(h, folder, name):
    """Deck-camera still. The gantry hides the jaws and REST is too slow for the transient."""
    try: (folder / name).write_bytes(h.call('GET', 'camera/false', binary=True))
    except Exception as error: (folder / (name + '.error.txt')).write_text(str(error))


if __name__ == '__main__':
    import logging
    logging.disable(logging.WARNING)  # broadcast replies on five connections flood the console
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-empty-confirmed', action='store_true')
    parser.add_argument('--front-to', type=float, help='walk only the front jaw outward to this coordinator Y')
    parser.add_argument('--no-tool', action='store_true', help='comparison walk with bare channels (DCG docked)')
    args = parser.parse_args()
    MoveYStep(((1, STEP), (2, STEP))).build_parameters().build()
    h = HamiltonPrep()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = h.folder / 'release_investigation_20261109' / (('encoder_test_' if args.execute_empty_confirmed else 'encoder_preflight_') + stamp)
    folder.mkdir(parents=True)
    ticket = dict(request_id='dcg_encoder_test_' + uuid4().hex, prior_request_id=PRIOR)
    if not args.execute_empty_confirmed:
        asyncio.run(run(h, ticket, folder, False, args.front_to, args.no_tool))
    else:
        owner = json.loads((h.folder / 'active.json').read_text())
        if owner.get('request_id') != PRIOR or owner.get('status') != 'failed_or_uncertain': raise RuntimeError('Wrong stopped batch')
        lock = h.folder / 'dcg48_execution.lock'
        with lock.open('x') as f: f.write(ticket['request_id'])
        try:
            result = asyncio.run(run(h, ticket, folder, True, args.front_to, args.no_tool))
            (folder / 'result.json').write_text(json.dumps(result, indent=2, default=str))
            h.journal(ticket, 'encoder_test_result', {k: v for k, v in result.items() if k != 'steps'})
            print(json.dumps({k: v for k, v in result.items() if k not in ('steps', 'events')}, indent=2, default=str), flush=True)
            if result['anomalous_step'] is not None: print(json.dumps(result['steps'][-1], indent=2, default=str), flush=True)
        finally: lock.unlink()
    print(folder)
