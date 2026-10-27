"""Logging TCP relay for learning the Hamilton port-2000 protocol.

A sniffer cannot work from the console PC: the vendor software lives on the
Hamilton PC (192.168.100.101) and its traffic to the instrument
(192.168.100.102:2000) is switched unicast we never see. This sits IN the path
instead -- the vendor software connects here, we forward to the instrument and
record both directions verbatim. No admin rights and no capture driver needed.

Deploy either way:
  * on THIS PC   -- point the vendor software at 192.168.100.15:2000
  * on the HL PC -- run it there and point the vendor software at 127.0.0.1:2000

This relay NEVER synthesises, drops or rewrites bytes. It forwards exactly what
each side sends, so the instrument sees precisely the vendor software's own
traffic. It only observes.

Run:  py -B -u operator_ui/hamilton_tap.py [--listen HOST] [--port N]
      py -B -u operator_ui/hamilton_tap.py --self-test
"""
import argparse
from datetime import datetime, timezone
import json
import socket
import threading

INSTRUMENT_HOST, INSTRUMENT_PORT = '192.168.100.102', 2000
LISTEN_HOST, LISTEN_PORT = '192.168.100.15', 2000


def stamp():
    return datetime.now(timezone.utc).isoformat()


def printable(data):
    return ''.join(chr(b) if 32 <= b < 127 else '.' for b in data)


class Transcript:
    """Append-only JSONL record, flushed per chunk so a crash keeps the data."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.stream = open(path, 'a', encoding='utf-8')

    def write(self, conn_id, direction, data):
        row = dict(t=stamp(), conn=conn_id, dir=direction, length=len(data),
                   hex=data.hex(), ascii=printable(data))
        with self.lock:
            self.stream.write(json.dumps(row) + '\n')
            self.stream.flush()
        arrow = '-->' if direction == 'client_to_instrument' else '<--'
        print('[%s] #%d %s %4d B | %s' % (row['t'][11:23], conn_id, arrow,
                                          len(data), printable(data)[:100]),
              flush=True)

    def close(self):
        with self.lock:
            if not self.stream.closed:
                self.stream.close()


def pump(conn_id, src, dst, direction, transcript, stop):
    """Copy src->dst verbatim, recording every chunk."""
    try:
        while not stop.is_set():
            data = src.recv(65536)
            if not data:
                break
            transcript.write(conn_id, direction, data)
            dst.sendall(data)
    except OSError:
        pass
    finally:
        stop.set()
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def handle(conn_id, client, peer, instrument, transcript):
    print('[conn %d] open from %s:%d' % (conn_id, peer[0], peer[1]), flush=True)
    try:
        upstream = socket.create_connection(instrument, timeout=10)
    except OSError as error:
        print('[conn %d] instrument unreachable: %s' % (conn_id, error), flush=True)
        client.close()
        return
    stop = threading.Event()
    threads = [
        threading.Thread(target=pump, args=(conn_id, client, upstream,
                                            'client_to_instrument', transcript, stop)),
        threading.Thread(target=pump, args=(conn_id, upstream, client,
                                            'instrument_to_client', transcript, stop)),
    ]
    for t in threads:
        t.daemon = True
        t.start()
    for t in threads:
        t.join()
    client.close()
    upstream.close()
    print('[conn %d] closed' % conn_id, flush=True)


def serve(listen, instrument, transcript_path):
    transcript = Transcript(transcript_path)
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    server.bind(listen)
    server.listen(8)
    actual = server.getsockname()
    print('tap listening on %s:%d -> instrument %s:%d' %
          (actual[0], actual[1], instrument[0], instrument[1]))
    print('transcript: %s' % transcript_path)
    counter = 0
    try:
        while True:
            client, peer = server.accept()
            counter += 1
            threading.Thread(target=handle, daemon=True,
                             args=(counter, client, peer, instrument, transcript)).start()
    except KeyboardInterrupt:
        print('\nstopped')
    finally:
        server.close()
        transcript.close()


def self_test():
    """Prove the relay is byte-exact against a local echo stand-in."""
    import os
    import tempfile

    fake = socket.socket()
    fake.bind(('127.0.0.1', 0))
    fake.listen(1)
    fake_addr = fake.getsockname()

    def instrument():
        sock, _ = fake.accept()
        got = sock.recv(65536)
        sock.sendall(b'ACK:' + got)
        sock.close()

    threading.Thread(target=instrument, daemon=True).start()

    path = os.path.join(tempfile.gettempdir(), 'hamilton_tap_selftest.jsonl')
    open(path, 'w').close()
    probe = socket.socket()
    probe.bind(('127.0.0.1', 0))
    tap_addr = probe.getsockname()
    probe.close()
    threading.Thread(target=serve, daemon=True,
                     args=(tap_addr, fake_addr, path)).start()

    import time
    time.sleep(.4)
    client = socket.create_connection(tap_addr, timeout=5)
    client.sendall(b'PING\r')
    reply = client.recv(65536)
    client.close()
    time.sleep(.4)

    rows = [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]
    print()
    print('reply received      :', reply)
    print('expected            :', b'ACK:PING\r')
    print('byte-exact relay    :', reply == b'ACK:PING\r')
    print('transcript rows     :', len(rows))
    for r in rows:
        print('  %-22s %r' % (r['dir'], bytes.fromhex(r['hex'])))
    ok = (reply == b'ACK:PING\r' and len(rows) == 2
          and bytes.fromhex(rows[0]['hex']) == b'PING\r'
          and bytes.fromhex(rows[1]['hex']) == b'ACK:PING\r')
    print()
    print('SELF-TEST', 'PASS' if ok else 'FAIL')
    try:
        os.remove(path)
    except OSError:
        pass  # the daemon serve thread may still hold it; harmless in a temp dir
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--listen', default=LISTEN_HOST)
    parser.add_argument('--port', type=int, default=LISTEN_PORT)
    parser.add_argument('--instrument', default=INSTRUMENT_HOST)
    parser.add_argument('--instrument-port', type=int, default=INSTRUMENT_PORT)
    parser.add_argument('--transcript',
                        default='reports/hamilton/tap_%s.jsonl'
                                % datetime.now().strftime('%Y%m%dT%H%M%SZ'))
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()

    if args.self_test:
        raise SystemExit(0 if self_test() else 1)

    import os
    os.makedirs(os.path.dirname(args.transcript) or '.', exist_ok=True)
    serve((args.listen, args.port), (args.instrument, args.instrument_port),
          args.transcript)


if __name__ == '__main__':
    main()
