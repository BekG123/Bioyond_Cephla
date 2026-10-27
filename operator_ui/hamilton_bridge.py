"""Local Hamilton bridge: the 127.0.0.1:5055 service HamiltonAdapter expects.

Implements exactly the three endpoints in hamilton_adapter.py -- GET /status,
POST /jobs, GET /jobs/<job_id> -- and nothing else. Binds to loopback only.

The instrument transport is deliberately NOT implemented. The device at
192.168.100.102:2000 is a silent raw socket (no banner, accepts concurrent
clients, Dallas Semiconductor OUI); its command grammar is unknown and is not
guessed here. Until a real transport is supplied this reports simulation=true,
which HamiltonAdapter.status() correctly rejects -- so the console keeps saying
"not connected" rather than pretending. That is the intended safe default.

Run:  py -B -u operator_ui/hamilton_bridge.py
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from uuid import uuid4

HOST, PORT = '127.0.0.1', 5055

# Instrument endpoint, for the transport that still has to be written.
INSTRUMENT_HOST, INSTRUMENT_PORT = '192.168.100.102', 2000


class Transport:
    """What a real instrument transport must provide.

    Implementations own the instrument socket EXCLUSIVELY. The device accepts
    concurrent TCP clients, so nothing else may hold it: two writers would
    interleave bytes on one serial line.
    """
    simulation = True

    def protocols(self):
        raise NotImplementedError

    def state(self):
        """-> (state, ready_for_robot) with state in idle/running/completed/fault."""
        raise NotImplementedError

    def start(self, protocol, plate_id):
        raise NotImplementedError

    def poll(self, job_id):
        """-> (status, success, ready_for_robot)."""
        raise NotImplementedError


class SimulatedTransport(Transport):
    """Shape-accurate stand-in. simulation=True, so the adapter refuses it."""
    simulation = True
    RUN_SECONDS = 8.0

    def __init__(self):
        self._started = None

    def protocols(self):
        return ['demo_protocol']

    def state(self):
        if self._started is None:
            return 'idle', True
        if time.monotonic() - self._started < self.RUN_SECONDS:
            return 'running', False
        return 'completed', True

    def start(self, protocol, plate_id):
        self._started = time.monotonic()

    def poll(self, job_id):
        state, ready = self.state()
        return ('completed' if state == 'completed' else 'running',
                state == 'completed', ready)


class RawSocketTransport(Transport):
    """TODO: the real thing, once the port-2000 grammar is known.

    Needed before this can be used:
      * the command/response framing the instrument speaks on :2000
      * how to enumerate protocols/methods
      * how to start a run and get back an instrument-side job identifier
      * how to read run state, success, and the "safe for robot access" signal
      * fault reporting, and what a timeout means physically

    Set simulation=False ONLY when every one of those is answered against the
    real instrument. That flag is what tells the console a physical connection
    is in place; a wrong value here is how a simulated run gets mistaken for a
    real one.
    """
    simulation = False

    def __init__(self, host=INSTRUMENT_HOST, port=INSTRUMENT_PORT):
        self.host, self.port = host, port
        raise NotImplementedError(
            'Hamilton port-2000 protocol is not known yet. Capture the real '
            'exchange from the vendor software before enabling this transport.')


class Bridge:
    def __init__(self, transport):
        self.transport = transport
        self.session_id = uuid4().hex   # new identity each process start
        self.lock = threading.Lock()
        self.jobs = {}                  # job_id -> ticket dict
        self.by_request = {}            # request_id -> job_id (idempotency)
        self.last_job_id = None

    def status(self):
        state, ready = self.transport.state()
        return dict(ok=True, session_id=self.session_id,
                    simulation=bool(self.transport.simulation),
                    state=state, ready_for_robot=bool(ready),
                    protocols=list(self.transport.protocols()),
                    job_id=self.last_job_id)

    def create_job(self, body):
        required = ('request_id', 'plate_id', 'protocol', 'session_id')
        if not all(isinstance(body.get(k), str) and body[k] for k in required):
            return dict(ok=False, error='request_id, plate_id, protocol and session_id are required')
        if body['session_id'] != self.session_id:
            return dict(ok=False, error='session_id does not match this bridge session')
        if body['protocol'] not in self.transport.protocols():
            return dict(ok=False, error='unknown protocol')
        with self.lock:
            # Re-posting the same request_id must not start a second run; the
            # adapter marks a ticket 'uncertain' if a start times out.
            existing = self.by_request.get(body['request_id'])
            if existing:
                return dict(self.jobs[existing], ok=True)
            state, _ = self.transport.state()
            if state not in ('idle', 'completed'):
                return dict(ok=False, error='instrument is ' + state + '; no start sent')
            job_id = uuid4().hex
            self.transport.start(body['protocol'], body['plate_id'])
            ticket = dict(ok=True, job_id=job_id, request_id=body['request_id'],
                          plate_id=body['plate_id'], protocol=body['protocol'],
                          session_id=self.session_id, status='running',
                          success=False, ready_for_robot=False)
            self.jobs[job_id] = ticket
            self.by_request[body['request_id']] = job_id
            self.last_job_id = job_id
            return dict(ticket)

    def job(self, job_id):
        with self.lock:
            ticket = self.jobs.get(job_id)
            if not ticket:
                return dict(ok=False, error='unknown job_id')
            status, success, ready = self.transport.poll(job_id)
            ticket.update(status=status, success=bool(success), ready_for_robot=bool(ready))
            return dict(ticket)


class Handler(BaseHTTPRequestHandler):
    bridge = None
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        print('[bridge] ' + self.address_string() + ' ' + (fmt % args), flush=True)

    def _send(self, payload, code=200):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == '/status':
            return self._send(self.bridge.status())
        if self.path.startswith('/jobs/'):
            result = self.bridge.job(self.path[len('/jobs/'):])
            return self._send(result, 200 if result['ok'] else 404)
        self._send(dict(ok=False, error='not found'), 404)

    def do_POST(self):
        if self.path != '/jobs':
            return self._send(dict(ok=False, error='not found'), 404)
        try:
            length = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(body, dict):
                raise ValueError
        except Exception:
            return self._send(dict(ok=False, error='invalid JSON body'), 400)
        result = self.bridge.create_job(body)
        self._send(result, 200 if result['ok'] else 409)


def main():
    transport = SimulatedTransport()
    Handler.bridge = Bridge(transport)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print('Hamilton bridge -> http://' + HOST + ':' + str(PORT))
    print('session_id=' + Handler.bridge.session_id +
          '  simulation=' + str(transport.simulation))
    if transport.simulation:
        print('SIMULATION: HamiltonAdapter will refuse this. Write a real '
              'transport before any physical workflow.')
    server.serve_forever()


if __name__ == '__main__':
    main()
