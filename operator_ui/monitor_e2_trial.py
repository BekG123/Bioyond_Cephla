"""Run an authorized existing trial helper while recording passive E2 feedback.

No E2 movement, error clearing, startup, or automatic retry. A failed read or
departure from the reference stops the controller and the child helper.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from draggo import DragGoRPC

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / 'operator_ui/e2_reference.json'

def check(info, ref):
    value = info['external_axes'].get('E2')
    if info['external_units'].get('E2') != 'degrees' or value is None:
        raise ValueError('E2 angular feedback unavailable')
    if not abs(value - ref['target_degrees']) <= ref['tolerance_degrees']:
        raise ValueError(f"E2 changed: {value:.4f} degrees; expected approximately 1.77")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('script')
    parser.add_argument('args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    ref = json.loads(REFERENCE.read_text())
    rpc = DragGoRPC('192.168.201.220')
    check(rpc.info(), ref)
    output = ROOT / f'operator_ui/reports/projected_alignment/e2_monitor_{time.time_ns()}.jsonl'
    with output.open('x', encoding='utf-8') as log:
        child = subprocess.Popen([sys.executable, '-B', args.script, *args.args], cwd=ROOT)
        try:
            while True:
                info = rpc.info()
                log.write(json.dumps(dict(at=time.time(), info=info, script=args.script))+'\n'); log.flush()
                check(info, ref)
                code = child.poll()
                if code is not None:
                    print(json.dumps(dict(e2_monitor=str(output),exit_code=code)), flush=True)
                    raise SystemExit(code)
                time.sleep(.2)
        except Exception as exc:
            stopped = {}
            for endpoint, body in [('seq/stop', {}), ('program', {'action':'stop'})]:
                try:
                    with urlopen(Request('http://127.0.0.1:5002/'+endpoint, data=json.dumps(body).encode(), headers={'Content-Type':'application/json'}),timeout=10) as response:
                        stopped[endpoint] = json.load(response)
                except Exception as stop_error:
                    stopped[endpoint] = {'error':str(stop_error), 'confirmed':False}
            log.write(json.dumps(dict(at=time.time(),error=str(exc),stop=stopped))+'\n'); log.flush()
            if child.poll() is None:
                child.terminate()
            raise

if __name__ == '__main__':
    main()
