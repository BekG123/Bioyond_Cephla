"""Read-only HTTP pose logger; never opens a controller connection or sends POST.

Run independently of Flask so teaching can continue without a console restart.
Write STOP in the session directory to stop. Samples are not replay approval.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import urllib.request


def now():
    return datetime.now(timezone.utc).isoformat()


def update_status(folder, status):
    # Windows readers can briefly lock status.json. Status is advisory;
    # a failed replacement must never terminate the append-only sample stream.
    try:
        temp = folder/'status.tmp'
        temp.write_text(json.dumps(status,indent=2),encoding='utf-8')
        temp.replace(folder/'status.json')
        return True
    except OSError:
        return False


def record(folder, url, interval=.2):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    metadata = dict(started_at=now(), source=url+'/state', target_interval_s=interval,
        replay_approved=False,
        limitations=['Polling is not synchronized servo telemetry; request times and gaps are recorded.',
                      'No past movement reconstruction. No automatic replay or learned controller.',
                      'Records arm pose/joints and external-axis feedback when supplied; no contact forces.',
                      'Every segment needs review; collision/contact segments must not be replayed.'])
    (folder/'metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    samples = failures = 0
    started = time.monotonic()
    try:
        with (folder/'samples.jsonl').open('x',encoding='utf-8',buffering=1) as stream:
            while not (folder/'STOP').exists():
                began = time.monotonic()
                sample = dict(index=samples, requested_at=now(), elapsed_s=round(began-started,4))
                try:
                    # Only the existing console talks to the robot; GET is read-only.
                    with urllib.request.urlopen(url+'/state',timeout=3) as response:
                        state = json.load(response)
                    robot = state.get('robot',{})
                    sample.update(valid=bool(robot.get('connected') and robot.get('ok') and not robot.get('errors')),
                        robot=robot, sequence=state.get('sequence'), server_timestamp=state.get('ts'))
                except Exception as error:
                    failures += 1
                    sample.update(valid=False,error=str(error))
                sample.update(received_at=now(),read_duration_s=round(time.monotonic()-began,4))
                stream.write(json.dumps(sample,allow_nan=False)+'\n')
                samples += 1
                status = dict(recording=True,samples=samples,failures=failures,
                              last_sample=sample['received_at'],last_valid=sample['valid'],
                              elapsed_s=round(time.monotonic()-started,2))
                update_status(folder, status)
                time.sleep(max(0,interval-(time.monotonic()-began)))
    finally:
        update_status(folder, dict(recording=False,samples=samples,
            failures=failures,ended_at=now()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session',required=True)
    parser.add_argument('--url',default='http://127.0.0.1:5002')
    args = parser.parse_args()
    record(args.session,args.url.rstrip('/'))
