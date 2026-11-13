"""Local, read-only viewer of Hamilton journal events. No instrument commands."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import time

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / 'reports' / 'hamilton_api'
POINTER = REPORTS / 'dry_run_viewer.json'


def snapshot():
    if not POINTER.exists():
        return dict(status='Ready for dry run', events=[], completed=0, updated=time.time())
    pointer = json.loads(POINTER.read_text())
    rid = pointer['request_id']
    if len(rid) != 32 or any(c not in '0123456789abcdef' for c in rid):
        raise ValueError('Invalid journal identity')
    events, column, completed, status, updated = [], 1, 0, 'Preparing', 0
    for line in (REPORTS / (rid + '.jsonl')).read_text(encoding='utf-8').splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        updated = entry['at']
        if entry['kind'] == 'event':
            e = entry['data'].get('event', {})
            if not isinstance(e, dict):
                continue
            code = e.get('code', '').lower()
            if code == 'stepstarted':
                d = e.get('data') or '{}'
                if isinstance(d, str):
                    d = json.loads(d)
                column = pointer['step_ids'].index(d['stepId']) + 1
            if code == 'processpipettestarted':
                mode = e.get('mode', '')
                operation = (e.get('operations') or [{}])[0]
                events.append(dict(at=entry['at'], mode=mode, column=column,
                                   site=operation.get('deckPosition'), well=operation.get('wellName')))
                status = mode
            if code == 'stepended':
                completed = max(completed, column)
            if code in ('error', 'failed', 'aborted'):
                status = 'Stopped — check instrument'
        elif entry['kind'] == 'live_progress':
            status = entry['data'].get('label', status)
        elif entry['kind'] == 'outcome':
            status = 'Completed' if entry['data']['status'] == 'completed' else 'Stopped — check instrument'
        elif entry['kind'] == 'reviewed_native_completion':
            status = 'Completed'
            completed = 6
    return dict(status=status, events=events, completed=completed, updated=updated,
                request_id=rid, physical=True, liquid=False)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split('?')[0] == '/data':
            try:
                body = json.dumps(snapshot()).encode()
            except Exception as error:
                body = json.dumps(dict(status='Feedback unavailable', events=[], error=str(error))).encode()
            mime = 'application/json'
        elif self.path in ('/', '/index.html'):
            body = (ROOT / 'static' / 'hamilton-dry-run.html').read_bytes()
            mime = 'text/html; charset=utf-8'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


if __name__ == '__main__':
    print('Hamilton dry-run viewer: http://127.0.0.1:5014', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 5014), Handler).serve_forever()
