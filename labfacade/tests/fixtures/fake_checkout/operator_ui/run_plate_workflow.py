"""Stand-in for the real plate workflow CLI. Prints the same kind of lines; moves nothing.

Behaviour is chosen with FAKE_WORKFLOW = ok | fail | hang.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--cycles', type=int, default=1)
parser.add_argument('--full-calibration', action='store_true')
parser.add_argument('--home-to-hamilton-roundtrip', action='store_true')
parser.add_argument('--home-to-squid-roundtrip', action='store_true')
parser.add_argument('--execute', action='store_true')
args = parser.parse_args()
mode = os.environ.get('FAKE_WORKFLOW', 'ok')


def say(**value):
    print(json.dumps(value), flush=True)


if not args.execute:
    print(json.dumps(dict(motion_started=False, handling_cycles=args.cycles), indent=2))
    sys.exit(0)

folder = Path(__file__).resolve().parent / 'reports' / 'plate_session' / f'continuous_grip_handling_{os.getpid()}'
folder.mkdir(parents=True)
path = folder / 'run.json'
handling = args.home_to_hamilton_roundtrip or args.home_to_squid_roundtrip
record = dict(status='checking', planned_cycles=args.cycles if handling else 0, completed_cycles=0, argv=sys.argv[1:])
path.write_text(json.dumps(record))
say(record=str(path))
say(phase='Hamilton delivery', status='starting')
print('a line that is not JSON', flush=True)
if mode == 'hang':
    time.sleep(30)
if mode == 'fail':
    record.update(status='stopped_or_uncertain', error='Sequence failed: torque band breached')
    path.write_text(json.dumps(record))
    say(status='stopped_or_uncertain', completed_cycles=0, record=str(path))
    raise RuntimeError('Sequence failed: torque band breached')
say(phase='Hamilton delivery', status='completed', pose=dict(X=1.0, Y=2.0, Z=3.0, Rz=4.0))
record.update(status='controller_completed_pending_operator_assessment', completed_cycles=record['planned_cycles'],
              final_receipt='final.json')
path.write_text(json.dumps(record))
say(status=record['status'], completed_cycles=record['completed_cycles'], record=str(path))
