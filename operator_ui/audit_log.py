"""Shared UI audit trail. Logs evidence, never dispatches controller commands."""
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4

from flask import g, request, jsonify, Response

_context = ContextVar('cephla_audit_context', default=None)
SECRET = re.compile(r'password|passwd|secret|token|api.?key|authorization|cookie|credential', re.I)


def redact(value):
    if isinstance(value, dict):
        return {str(k): '[REDACTED]' if SECRET.search(str(k)) else redact(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):
        return [redact(v) for v in value]
    if isinstance(value,str):
        return re.sub(r'(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+',r'\1[REDACTED]',value)
    return value


class AuditLog:
    def __init__(self, root, max_bytes=25*1024*1024):
        self.root = Path(root)
        self.session = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8]
        self.max_bytes = max_bytes
        self.lock = threading.RLock()
        self.part = 1
        self.size = 0
        self.events = 0
        self.last_error = None
        self.last_event_at = None

    @property
    def path(self):
        return self.root/self.session/f'events_{self.part:04d}.jsonl'

    def context(self):
        return dict(_context.get() or {})

    def event(self, event, **fields):
        # Logging failures must not swallow emergency stops or change command
        # results. Surface degradation through /audit/status and server stderr.
        with self.lock:
            try:
                stamp = datetime.now(timezone.utc).isoformat()
                row = dict(timestamp=stamp,event=event,session=self.session,**self.context())
                row.update(fields)
                data = (json.dumps(redact(row),allow_nan=False,default=str)+'\n').encode('utf-8')
                if self.size and self.size+len(data)>self.max_bytes:
                    self.part += 1
                    self.size = 0
                self.path.parent.mkdir(parents=True,exist_ok=True)
                with self.path.open('ab') as stream:
                    stream.write(data)
                    stream.flush()
                self.size += len(data)
                self.events += 1
                self.last_error = None
                self.last_event_at = stamp
                return True
            except Exception as error:
                self.last_error = str(error)
                logging.error('Audit log write failed: %s',type(error).__name__)
                return False

    def status(self):
        with self.lock:
            return dict(ok=self.last_error is None,session=self.session,file=str(self.path),
                        events=self.events,last_event_at=self.last_event_at,
                        error=self.last_error,rotation_bytes=self.max_bytes,
                        retention='All parts retained; no automatic deletion')


def install_audit(app, audit):
    """Register before ownership/error hooks so rejected requests are logged too."""
    @app.before_request
    def audit_request():
        origin = request.headers.get('X-Cephla-View')
        if origin not in ('researcher','developer'):
            try:
                ref = urlsplit(request.referrer or '').path
            except ValueError:
                ref = ''
            origin = ('researcher' if request.path.startswith('/researcher') or ref in ('/','/researcher') else
                      'developer' if ref == '/developer' else 'api')
        ident = uuid4().hex
        g.audit_token = _context.set(dict(request_id=ident,view=origin))
        g.audit_started = time.monotonic()
        body = request.get_json(silent=True)
        if body is None and request.content_length:
            body = dict(omitted='Non-JSON body',bytes=request.content_length,content_type=request.content_type)
        audit.event('http_request',method=request.method,path=request.path,
                    query=request.args.to_dict(flat=False),body=body)

    @app.after_request
    def audit_response(response):
        # Do not consume generators, images, or file responses. JSON API values
        # are recorded in full; binary/static content has metadata only.
        details = dict(content_type=response.content_type,content_length=response.content_length)
        if response.is_json and not response.is_streamed and not response.direct_passthrough:
            details['body'] = response.get_json(silent=True)
        else:
            details['body_omitted'] = 'binary, static, or streamed content'
        audit.event('http_response',method=request.method,path=request.path,status=response.status_code,
                    duration_ms=round((time.monotonic()-getattr(g,'audit_started',time.monotonic()))*1000,3),
                    **details)
        response.headers['X-Cephla-Request-ID'] = audit.context().get('request_id','')
        response.headers['X-Cephla-Audit'] = 'error' if audit.last_error else 'recording'
        return response

    @app.teardown_request
    def audit_teardown(error):
        if error is not None:
            audit.event('request_exception',error_type=type(error).__name__,message=str(error))
        token = g.pop('audit_token',None)
        if token is not None:
            _context.reset(token)

    @app.get('/audit/status')
    def audit_status():
        return jsonify(audit.status())

    @app.get('/audit/export')
    def audit_export():
        # Snapshot byte lengths under the writer lock. Export cannot chase an
        # ever-growing file while the browser continues polling.
        with audit.lock:
            files = [(p,p.stat().st_size) for p in sorted((audit.root/audit.session).glob('events_*.jsonl'))]
        def stream():
            yield '{"schema":"cephla.ui-audit.v1","session":'+json.dumps(audit.session)+',"replay_approved":false,"events":['
            comma = False
            for path, size in files:
                with path.open('rb') as handle:
                    while handle.tell() < size:
                        line = handle.readline(size-handle.tell()).strip()
                        if line:
                            if comma:
                                yield ','
                            yield line
                            comma = True
            yield ']}'
        return Response(stream(),mimetype='application/json',headers={
            'Content-Disposition':f'attachment; filename="cephla-audit-{audit.session}.json"',
            'Cache-Control':'no-store'})

    audit.event('audit_started',schema='cephla.ui-audit.v1',
                coverage=['HTTP JSON requests/responses','robot status including external axes',
                          'background sequence lifecycle and progress'],
                exclusions=['Passwords/tokens/authentication headers','binary camera payloads',
                            'commands made through other applications','unobserved motion between samples'],
                replay_approved=False)
