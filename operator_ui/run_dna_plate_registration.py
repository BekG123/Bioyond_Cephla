"""Register a Cellvis plate at the scanner, then run the full HOME/Hamilton/Squid sequence.

One phase per invocation, so a person answers each inspection between phases:
  calibrate      IDLE -> fresh Cellvis calibration, jaws open above the HOME plate
  grip_lift      grip + 5 mm proof lift              (after: alignment inspected)
  to_scanner     loaded route to the scanner         (after: lift secure, route clear)
  scan           at most five triggers; require decoded data; register intended purpose
  return_home    scanner -> HOME, plate still held
  release_home   reseat/release in HOME               (after: plate supported in HOME)
  full_sequence  one HOME->Hamilton->HOME->Squid->HOME cycle from the release receipt
State lives in one run record; a phase already attempted is never repeated.
No startup, fault reset or automatic retry anywhere.
"""
import argparse
import hashlib
import json
import math
import time
from pathlib import Path

from run_record_io import write_run_record

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / 'operator_ui/reports/plate_session/dna_plate_registration'
PHASES = ('calibrate', 'grip_lift', 'to_scanner', 'scan', 'return_home', 'release_home', 'full_sequence')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scan_until_decoded(attempts, interval):
    if type(attempts) is not int or not 1 <= attempts <= 5:
        raise ValueError('Use one to five scan triggers per presented side.')
    if type(interval) not in (int,float) or not math.isfinite(interval) or interval <= 0:
        raise ValueError('Scan interval must be finite and positive.')
    from barcode_scanner_cli import scan_once
    for index in range(1, attempts + 1):
        record, receipt = scan_once('192.168.1.10', 1024, '192.168.1.15', 5.0,
                                    ROOT / 'operator_ui/reports/barcode_scanner')
        print(f'Scan {index}: {record["result"]} {record.get("barcode") or ""}', flush=True)
        if record.get('stop_error') or record['result'] not in ('decoded','no_read'):
            raise RuntimeError(f'Scanner {record["result"]}; stopped, plate still held. Receipt {receipt}')
        if record['result'] == 'decoded':
            return record, receipt, index
        if index < attempts:time.sleep(interval)
    raise RuntimeError(f'No read after {attempts} triggers; plate still held at the scanner.')


def run_phase(phase, state, args):
    from run_cellvis24_workflow import main as workflow
    from cellvis24_scanner_pickup import grip_trial, proof_lift
    from run_cellvis24_scanner import scanner_transfer
    from run_cellvis24_scanner_hamilton import scanner_phase
    ident = state.get('trial_id')
    if phase == 'calibrate':
        result = workflow(['--projected-calibration-trial', '--execute'])
        if result.get('status') != 'awaiting_open_claw_inspection':
            raise RuntimeError('Expected completed open-jaw Cellvis calibration.')
        state['trial_id'] = Path(result['record']).parent.name
        return dict(record=result['record'])
    if phase == 'grip_lift':
        grip = grip_trial(ident, execute=True)
        return dict(grip=str(grip), proof_lift=str(proof_lift(ident)))
    if phase == 'to_scanner':
        return dict(record=scanner_transfer(ident)['record'])
    if phase == 'scan':
        from plate_registry import PlateRegistry
        record, receipt, tries = scan_until_decoded(args.attempts, args.interval)
        saved = record.get('plate_registry', {})
        if saved.get('saved') is not True:
            raise RuntimeError('Decoded but not saved to the plate registry: ' + str(saved))
        plate = PlateRegistry().update(saved['plate_id'], saved['revision'], dict(experiment=args.contents),
                                       'Operator-stated purpose, not measured contents (' + str(receipt) + ')')
        state['plate_id'] = plate['plate_id']
        return dict(record=str(receipt), triggers=tries, plate_id=plate['plate_id'], contents=args.contents)
    if phase == 'return_home':
        return dict(record=scanner_phase(ident, 'return_home')['record'])
    if phase == 'release_home':
        result = scanner_phase(ident, 'release_home', True)
        state['release_record'] = result['record']
        return dict(record=result['record'])
    if phase == 'full_sequence':
        from run_cellvis24_scanner_hamilton import reconnect,api,dispatch
        if not state.get('plate_id') or state['phases'].get('scan',{}).get('status')!='completed':
            raise RuntimeError('Successful barcode registration required before station handling.')
        reconnect()
        plan=api('developer/api/cellvis24-workflow/preview',dict(stations=['hamilton','squid'],cycles=1,
            source=state['release_record'],recorded_hamilton_variant='opposite3'))['plan']
        result=dispatch('developer/api/cellvis24-workflow/start',dict(plan=plan,ready=True,path_clear=True,
            setup_confirmed=True,recorded_clearance_confirmed=True),'cellvis24_workflow',600)
        if state.get('plate_id'):
            from plate_registry import PlateRegistry
            PlateRegistry().record_run(state['plate_id'], str(result.get('record')), 'completed', 'run_dna_plate_registration')
        return dict(record=result.get('record'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('phase', choices=PHASES)
    parser.add_argument('--run', help='Run record name; omit only for calibrate.')
    parser.add_argument('--contents', default='DNA reagents')
    parser.add_argument('--attempts', type=int, choices=range(1,6), default=5)
    parser.add_argument('--interval', type=float, default=1.0)
    args = parser.parse_args(argv)
    RECORDS.mkdir(parents=True, exist_ok=True)
    if args.phase == 'calibrate':
        if args.run:
            parser.error('calibrate starts a new run.')
        path = RECORDS / (time.strftime('%Y%m%dT%H%M%S') + '.json')
        state = dict(at=time.time(), contents=args.contents, phases={}, automatic_retries=False)
    else:
        if not args.run:
            parser.error('--run is required.')
        path = RECORDS / args.run
        state = json.loads(path.read_text(encoding='utf-8'))
        order = PHASES.index(args.phase)
        missing = [p for p in PHASES[:order] if state['phases'].get(p, {}).get('status') != 'completed']
        if missing:
            parser.error('Earlier phases not completed: ' + ', '.join(missing))
    if args.phase in state['phases']:
        parser.error(args.phase + ' was already attempted; inspect it, no retry.')
    entry = state['phases'][args.phase] = dict(status='started', at=time.time())
    write_run_record(path, state)
    try:
        entry.update(run_phase(args.phase, state, args) or {})
        entry['status'] = 'completed'
    except BaseException as error:
        entry.update(status='stopped_or_uncertain', error=str(error))
        raise
    finally:
        entry['finished_at'] = time.time()
        write_run_record(path, state)
        print(json.dumps(dict(run=path.name, phase=args.phase, status=entry['status'],
                              trial_id=state.get('trial_id'), plate_id=state.get('plate_id'))), flush=True)


if __name__ == '__main__':
    main()
