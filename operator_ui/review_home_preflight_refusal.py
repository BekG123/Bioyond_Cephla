"""Review the exact known Home preflight rejection, preserving its evidence."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
NAME = '1792503633276607400_20ae8fad5fa046efaeff5bd6d667d1b3.json'
DIGEST = '702d2cb501a6ad5514dfaeadd73f2a7bd8840d0a9d3d776996c8820af86a874f'


def main():
    path = ROOT/'reports/ik_home'/NAME
    original = path.read_bytes()
    if hashlib.sha256(original).hexdigest() != DIGEST:
        raise RuntimeError('Record changed; review cannot be applied.')
    record = json.loads(original)
    if (record['status'] != 'failed_to_start' or record.get('sequence') is not None
            or record['error'] != 'Hand-guiding status needs attention. Resolve it before returning Home.'):
        raise RuntimeError('Unexpected failure; requires separate review.')
    with urlopen('http://127.0.0.1:5002/state', timeout=5) as reply:
        state = json.load(reply)
    if state['sequence']['active'] or not state['robot']['ok']:
        raise RuntimeError('Review deferred: active run or unavailable robot.')
    evidence = dict(schema=1, reason='home_preflight_rejected',
        runner_start_called=False, home_travel_dispatched=False,
        original_sha256=DIGEST, diagnostic=record['error'],
        basis='Exact HomeReturn.start readiness rejection before Runner.start; '
              'no sequence was created. Current robot state recorded with review.')
    folder = ROOT/'reports/home_attempt_reviews'/'preflight_refusal_1792503633276607400'
    folder.mkdir(parents=True, exist_ok=True)
    backup = folder/NAME
    if backup.exists() and backup.read_bytes() != original:
        raise RuntimeError('Original backup differs.')
    backup.write_bytes(original)
    (folder/'review.json').write_text(json.dumps(dict(evidence=evidence,
        robot=state['robot'], sequence=state['sequence']), indent=2), encoding='utf-8')
    record['home_preflight_refusal'] = evidence
    tmp = path.with_suffix('.review.tmp')
    tmp.write_text(json.dumps(record, indent=2), encoding='utf-8')
    tmp.replace(path)
    print(json.dumps(dict(review=str(folder/'review.json'), hardware_commands=0)))


if __name__ == '__main__':
    main()
