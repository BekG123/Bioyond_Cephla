"""Supervised check of Squid return_to_loading through the facade.

Default: read-only. Prints Squid's status and every fact the move depends on.

    py -m labfacade.live_squid_return

--execute-confirmed sends the one stage move. Use it only after the person
named in --person has said, for this run: the plan is approved, they are at
the E-stop, the arm is clear of the Squid stage (at Home), and the stage path
is clear. Those statements are recorded as theirs in the run folder.

    py -m labfacade.live_squid_return --execute-confirmed --person NAME
"""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from labfacade import Facade, HumanConsole, Signer, load_manifests  # noqa: E402
from labfacade.backends import SquidBackend  # noqa: E402
from labfacade.dataset import ConsoleFrame, squid_sources  # noqa: E402

PLAN = dict(title='Squid stage to the saved loading position', steps=[
    dict(id='s01', machine='squid', operation='return_to_loading', params={})])
CONFIRMATIONS = ('robot is at Home', 'stage path is clear', 'robot at Home within 0.2 mm')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--execute-confirmed', action='store_true')
    parser.add_argument('--person')
    parser.add_argument('--reference', help='squid_stage_reference.json the running Squid extension loaded')
    parser.add_argument('--runs', default=str(HERE.parent / 'runs'))
    parser.add_argument('--squid-software', help='Squid software directory for file-only saving-format reporting.')
    parser.add_argument('--squid-config', help='Explicit active Squid INI.')
    args = parser.parse_args()

    manifests = load_manifests()
    backend = SquidBackend(reference=args.reference, dataset_sources=squid_sources(
        frame=ConsoleFrame(), software_dir=args.squid_software, active_config=args.squid_config))
    signer = Signer.from_file(Path(args.runs) / '.signing_key', create=True)
    facade = Facade.from_manifests({'squid': manifests['squid']}, {'squid': backend}, signer, args.runs)

    report = dict(motion_sent=False, status=facade.status('squid'), plan_problems=facade.validate_plan(PLAN))
    report['squid_saving_format'] = backend.dataset_sources.report()
    try:
        report['preflight'] = backend.preflight()
    except Exception as error:
        report['preflight_error'] = f'{type(error).__name__}: {error}'
    print(json.dumps(report, indent=2), flush=True)
    if not args.execute_confirmed:
        return 0
    if not args.person:
        parser.error('--execute-confirmed needs --person')
    if report['plan_problems'] or 'preflight_error' in report or report['status']['state'] != 'idle':
        print('Not started: the read-only checks above did not pass.')
        return 2

    run = facade.new_run(PLAN, 'squid-return-to-loading')
    person = HumanConsole(run, signer)
    person.approve_plan(args.person)
    person.attest_presence(args.person)
    for text in CONFIRMATIONS:
        person.confirm('s01', text, args.person)
    result = facade.run_step(run, 's01')
    print(json.dumps(dict(result=result, run_folder=str(run.path),
                          events=[f"{e['kind']}:{e['status']}" for e in run.events.read()]), indent=2, default=str))
    return 0 if result['outcome'] == 'completed' else 1


if __name__ == '__main__':
    sys.exit(main())
