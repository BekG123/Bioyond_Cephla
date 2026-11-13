"""Supervised run of the plate workflow through the facade.

Default: read-only. Prints the arm's status, every fact the start depends on,
and the workflow's own preview. Sends nothing.

    py -m labfacade.live_plate_workflow --full-calibration --home-to-hamilton-roundtrip --home-to-squid-roundtrip

--execute-confirmed starts the workflow. Use it only after the person named in
--person has said, for this run: the plan is approved, they are at the E-stop,
the plate is supported in HOME, the destination holders are empty, Hamilton
access is open and the routes are clear. Those statements are recorded as
theirs in the run folder.
"""
import argparse
import json
from pathlib import Path
import sys

import psutil

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from labfacade import Facade, HumanConsole, Signer, load_manifests  # noqa: E402
from labfacade.backends import BioyondConsoleBackend, SquidBackend  # noqa: E402
from labfacade.dataset import ConsoleFrame, squid_sources  # noqa: E402

CONFIRMATIONS = ('plate supported in HOME', 'destination holders empty', 'Hamilton access open', 'routes clear')
RECEIPT = 'calibration evidence fresh (30 minutes) or full_calibration selected'


def console_folder(port=5002):
    """The folder the process listening on the console port runs from, or None."""
    for connection in psutil.net_connections(kind='tcp'):
        if connection.status == psutil.CONN_LISTEN and connection.laddr.port == port and connection.pid:
            try:
                return Path(psutil.Process(connection.pid).cwd()).resolve()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return None
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--full-calibration', action='store_true')
    parser.add_argument('--home-to-hamilton-roundtrip', action='store_true')
    parser.add_argument('--home-to-squid-roundtrip', action='store_true')
    parser.add_argument('--cycles', type=int, default=1)
    parser.add_argument('--checkout', default=str(HERE.parent.parent / 'Bioyond_Cephla'),
                        help='The folder the operator console runs from.')
    parser.add_argument('--execute-confirmed', action='store_true')
    parser.add_argument('--person')
    parser.add_argument('--runs', default=str(HERE.parent / 'runs'))
    parser.add_argument('--squid-software', help='Squid software directory for file-only saving-format reporting.')
    parser.add_argument('--squid-config', help='Explicit active Squid INI; never inferred as live runtime proof.')
    args = parser.parse_args()

    params = {k: True for k in BioyondConsoleBackend.FLAGS if getattr(args, k)}
    if args.cycles != 1:
        params['cycles'] = args.cycles
    checkout = Path(args.checkout).resolve()
    squid = SquidBackend(reference=checkout / 'operator_ui' / 'squid_stage_reference.json',
                         dataset_sources=squid_sources(frame=ConsoleFrame(), software_dir=args.squid_software,
                                                       active_config=args.squid_config))
    backend = BioyondConsoleBackend(checkout=checkout, squid=squid)
    signer = Signer.from_file(Path(args.runs) / '.signing_key', create=True)
    facade = Facade.from_manifests(load_manifests(), {'bioyond_s4': backend}, signer, args.runs)
    plan = dict(title='Plate workflow: ' + ', '.join(sorted(params)), plates={'P1': 'bioyond deck'}, steps=[
        dict(id='s01', machine='bioyond_s4', operation='run_plate_workflow', params=params,
             transfer={'plate': 'P1', 'from': 'bioyond deck', 'to': 'bioyond deck'})])

    running_from = console_folder()
    report = dict(motion_sent=False, params=params, timeout_s=backend.timeout_s('run_plate_workflow', params),
                  console_runs_from=str(running_from), checkout=str(checkout),
                  folders_match=running_from == checkout, launcher=backend.python,
                  plan_problems=facade.validate_plan(plan))
    report['squid_saving_format'] = squid.dataset_sources.report()
    for name, read in (('status', lambda: facade.status('bioyond_s4')), ('preflight', lambda: backend.preflight(params)),
                       ('workflow_preview', lambda: backend.preview(params))):
        try:
            report[name] = read()
        except Exception as error:
            report[name + '_error'] = f'{type(error).__name__}: {error}'
    blockers = [k for k in report if k.endswith('_error')]
    blockers += ['folders do not match'] if not report['folders_match'] else []
    blockers += ['plan problems'] if report['plan_problems'] else []
    blockers += [f"status is {report['status']['state']}"] if report.get('status', {}).get('state') != 'idle' else []
    blockers += [f'{k}: {v}' for k, v in report.get('preflight', {}).items()
                 if k in ('controller', 'active', 'hamilton', 'squid') and v]
    report['blockers'] = blockers
    print(json.dumps(report, indent=2, default=str), flush=True)
    if not args.execute_confirmed:
        return 0
    if not args.person:
        parser.error('--execute-confirmed needs --person')
    if blockers:
        print('Not started: the read-only checks above did not pass.')
        return 2

    run = facade.new_run(plan, 'plate-workflow')
    person = HumanConsole(run, signer)
    person.approve_plan(args.person)
    person.attest_presence(args.person)
    for text in CONFIRMATIONS:
        person.confirm('s01', text, args.person)
    print(json.dumps(dict(run_folder=str(run.path), started=True)), flush=True)
    result = facade.run_step(run, 's01')
    events = run.events.read()
    print(json.dumps(dict(result=result, run_folder=str(run.path), event_count=len(events),
                          last_events=[f"{e['kind']}:{e['status']}" for e in events[-8:]]), indent=2, default=str))
    return 0 if result['outcome'] == 'completed' else 1


if __name__ == '__main__':
    sys.exit(main())
