"""Replay one plan end to end on fake machines. No hardware, no sockets.

    py -m labfacade.replay_fake_plan [output folder]

Approve once, attest once, then run. Step s03 has an injected fault, so the
run pauses there and s04 is refused until a person resumes.
"""
import json
from pathlib import Path
import sys
import tempfile

from labfacade import Facade, HumanConsole, Signer, load_manifests
from labfacade.fakes import FakeMachine

HERE = Path(__file__).resolve().parent
PLAN = dict(title='plate to Squid, image, park Hamilton', plates={'P1': 'gripper'}, steps=[
    dict(id='s01', machine='squid', operation='return_to_loading', params={}),
    dict(id='s02', machine='bioyond_s4', operation='place_plate', params={'station': 'squid'},
         transfer={'plate': 'P1', 'from': 'gripper', 'to': 'squid stage'}),
    dict(id='s03', machine='squid', operation='run_imaging', params={}),
    dict(id='s04', machine='hamilton_prep', operation='park', params={}),
])


def main(root):
    manifests = load_manifests(HERE / 'tests' / 'fixtures' / 'machines', HERE.parent / 'machines' / 'manifest.schema.json')
    fakes = dict(
        hamilton_prep=FakeMachine(sensors={'door_closed': True}, conditions={'initialized': True, 'parked': True}),
        bioyond_s4=FakeMachine(conditions={'plate released': True}),
        squid=FakeMachine(conditions={'no scan running': True, 'at loading position': True,
                                      'acquisition complete': False}))       # the injected fault
    signer = Signer(b'replay-only-key-0123456789')
    facade = Facade.from_manifests(manifests, fakes, signer, root)

    print('plan problems before approval:', facade.validate_plan(PLAN) or 'none')
    run = facade.new_run(PLAN, 'fake-replay')
    person = HumanConsole(run, signer)
    person.approve_plan('researcher')            # the one approval
    person.attest_presence('researcher')         # at the E-stop for this run

    for step in PLAN['steps']:
        result = facade.run_step(run, step['id'])
        print(f"{step['id']}  {step['machine']:14} {step['operation']:18} -> {result['outcome']}"
              + (f"  ({result['code']}: {result['reason']})" if 'code' in result else ''))

    print('\ncommands the fake machines received:')
    for name, fake in fakes.items():
        print(f'  {name:14} {[c["name"] for c in fake.commands]}')
    print('\nledger:', json.dumps(run.read_json('ledger.json')['plates']))
    print(f'\n{run.path}')
    for path in sorted(run.path.rglob('*')):
        depth = len(path.relative_to(run.path).parts)
        print('  ' * depth + path.name + ('/' if path.is_dir() else ''))
    events = run.events.read()
    print(f'\n{len(events)} events:', ' '.join(f"{e['kind']}:{e['status']}" for e in events))


if __name__ == '__main__':
    sys.path.insert(0, str(HERE.parent))
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix='labfacade_replay_')))
