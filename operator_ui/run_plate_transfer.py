"""Chain Cellvis slot 1 -> HOME -> barcode -> HOME -> Squid or Hamilton.

Preview is offline by default. --execute runs directly from this terminal;
no operator console or Flask server is required. Disconnect other robot clients
first. The terminal connects once and disconnects when finished.
--execute confirms: lid-off Cellvis P24-1.5H-N
flat in slot 1; HOME and the destination holder empty; unchanged fixtures and
clear routes, jaw sweeps and holder rotation (including one small released-holder
correction after HOME reseating and re-centering before each barcode pickup);
healthy running Auto/Lua with
empty jaws at accepted HOME clearance; hands clear and E-stop supervision.
Hamilton additionally requires parked heads and open access; Squid must be at
its verified loading position. No calibration, startup, fault reset, imaging
or pipetting. --roundtrip retrieves immediately and finishes with plate HOME;
otherwise the plate stays at the station and the empty arm returns HOME.
"""
import argparse
import json
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = 'http://127.0.0.1:5002/researcher/api/plate-transfer'


class ApiRejected(RuntimeError):
    """Explicit rejection; never resend Start."""


def api(path, body=None):
    request = Request(BASE + '/' + path,
                      data=None if body is None else json.dumps(body).encode(),
                      headers={'Content-Type': 'application/json',
                               'X-Cephla-Terminal': 'plate-transfer-v1'})
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as error:
        raw = error.read().decode('utf-8', errors='replace')
        try:
            payload = json.loads(raw)
            detail = (payload.get('message') or payload.get('error')) if isinstance(payload, dict) else None
        except ValueError:
            detail = None
        if not detail:
            detail = f'Console HTTP {error.code} during {path}. Check the console traceback for the underlying error.'
        if error.code == 404:
            detail += ' Reload the idle operator console with the updated code; this CLI never restarts it.'
        raise ApiRejected(detail) from error
    if not isinstance(result, dict) or result.get('ok') is not True:
        raise ApiRejected(str(result))
    return result


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-slot', type=int, choices=[1], default=1,
                        help='Accepted Cellvis hotel source (default: 1).')
    parser.add_argument('--destination', '--to', type=str.lower, choices=['squid', 'hamilton'], required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--roundtrip', action='store_true', help='Deliver/release, then retrieve/release in HOME; no instrument work.')
    mode.add_argument('--drop-off', action='store_true', help='Leave plate at station; return empty arm HOME (default).')
    parser.add_argument('--expected-plate-id', help='Exact known barcode; a fresh scan is still required.')
    parser.add_argument('--execute', action='store_true', help='Confirm setup, connect directly to the robot and run once; no console required.')
    parser.add_argument('--via-console', action='store_true', help='Optional legacy mode: use the already-running Flask console instead of a direct connection.')
    args = parser.parse_args(argv)
    if args.expected_plate_id == '':
        parser.error('--expected-plate-id must not be empty.')
    return args


def preview(args):
    from lacry_workflow_composition import composition_outline
    from hotel_squid_composition import hotel, profile_binding
    from hotel_cellvis_handoff import scanner_reference
    from composed_cellvis_registration import delivery_steps
    from cellvis24_workflow import evidence
    destination = args.destination.title()
    steps, blockers = composition_outline('Cellvis P24-1.5H-N', args.source_slot, destination, args.roundtrip)
    _, workflow, _ = hotel(args.source_slot)
    binding = profile_binding('Cellvis P24-1.5H-N', args.source_slot)
    if binding['geometry_sha256'] != workflow['geometry_sha256']['retrieve']:
        raise RuntimeError('Accepted slot-1 retrieval geometry changed.')
    scanner = scanner_reference()
    station_steps = delivery_steps(destination, args.roundtrip)
    if blockers:
        raise RuntimeError('; '.join(blockers))
    return dict(motion_started=False, preview='offline; live readiness checked only with --execute',
                plate_profile='Cellvis P24-1.5H-N (lid off)', source_slot=args.source_slot,
                destination=destination, roundtrip=args.roundtrip, expected_plate_id=args.expected_plate_id,
                steps=steps, station_steps=[s['label'] for s in station_steps],
                scanner_z=scanner['scanner_z'], scan_limit_per_side=5,
                station_acceptance_sha256=evidence(),
                finish=dict(plate='HOME' if args.roundtrip else destination, arm='HOME'),
                transport='console' if args.via_console else 'direct', console_required=args.via_console,
                handling_only=True, automatic_retries=False, requirements=__doc__)


def execute_console(args):
    body = dict(destination=args.destination.title(), roundtrip=args.roundtrip)
    if args.expected_plate_id is not None:
        body['plate_id'] = args.expected_plate_id
    proposed = api('plan', body)
    plan = proposed['plan']
    print(json.dumps(proposed, indent=2), flush=True)
    if proposed.get('blocked') or plan.get('executable') is not True:
        raise RuntimeError('Complete transfer is blocked; no start was sent.')
    ident = plan['id']
    attempted = False
    try:
        # Mark before POST: a lost acknowledgement must never cause a resend.
        attempted = True
        reply = api('start', dict(plan_id=ident, ready=True))
        if reply.get('plan_id') != ident:
            raise RuntimeError('Unexpected start acknowledgement; inspect this transfer, no retry.')
        print(json.dumps(reply), flush=True)
        deadline = time.monotonic() + 930
        last = None
        while True:
            state = api('status/' + ident)
            if state.get('plan_id') != ident:
                raise RuntimeError('Transfer status identity changed; no retry.')
            summary = (state['status'], [(s['step'], s['status']) for s in state.get('steps', [])])
            if summary != last:
                print(json.dumps(state), flush=True)
                last = summary
            if state['status'] == 'completed_controller_verified':
                attempted = False
                return state
            if state['status'] not in ('approved', 'running'):
                raise RuntimeError('Transfer stopped; inspect '+state['record']+': '+str(state.get('error') or state['status']))
            if time.monotonic() > deadline:
                raise TimeoutError('Transfer completion timed out; no retry.')
            time.sleep(.5)
    except BaseException:
        if attempted:
            try:
                print(json.dumps(api('stop', dict(plan_id=ident))), flush=True)
            except Exception as error:
                print('Could not confirm Stop for '+ident+': '+str(error)+'. Check the console and physical E-stop.', file=sys.stderr)
        raise


def execute(args):
    if args.via_console:
        return execute_console(args)
    from standalone_plate_transfer import execute as execute_direct
    return execute_direct(args)


def main(argv=None):
    args = parse_args(argv)
    result = preview(args)
    print(json.dumps(result, indent=2), flush=True)
    return execute(args) if args.execute else result


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted. No commands were retried; inspect the transfer record.', file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
