"""Flask adapter for an isolated RealSense/Viser worker. No robot API access."""
from pathlib import Path
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def worker_python(root=None, platform=None):
    root = ROOT if root is None else Path(root)
    platform = os.name if platform is None else platform
    return root / '.venv-realsense' / ('Scripts/python.exe' if platform == 'nt' else 'bin/python')


class RealSenseService:
    def __init__(self, port=5056, viser_port=8086):
        self.port, self.viser_port = port, viser_port
        self.process = None
        self.lock = threading.Lock()

    def request(self, path, body=None, timeout=5):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}',
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read(), response.headers.get('Content-Type', 'application/json'), response.status
        except urllib.error.HTTPError as ex:
            return ex.read(), ex.headers.get('Content-Type', 'application/json'), ex.code

    def status(self):
        try:
            result = json.loads(self.request('/status', timeout=1)[0])
            if result.get('service') != 'bioyond-realsense':
                raise ValueError('Depth worker port is used by another service')
            return result
        except Exception as ex:
            return dict(ok=False, service='bioyond-realsense', state='offline',
                error=str(ex), installed=worker_python().exists())

    def launch(self):
        with self.lock:
            current = self.status()
            if current.get('ok'):
                return current
            python = worker_python()
            if not python.exists():
                raise RuntimeError('Create .venv-realsense using the Windows or Linux setup in operator_ui/REALSENSE.md first')
            if self.process is None or self.process.poll() is not None:
                log = ROOT/'operator_ui/realsense_worker.log'
                with log.open('ab') as output:
                    self.process = subprocess.Popen([str(python), '-B', '-u',
                        str(ROOT/'operator_ui/realsense_worker.py'), '--port', str(self.port),
                        '--viser-port', str(self.viser_port)], cwd=str(ROOT),
                        stdout=output, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            for _ in range(80):
                current = self.status()
                if current.get('ok'):
                    return current
                if self.process.poll() is not None:
                    break
                time.sleep(.1)
            raise RuntimeError('Depth viewer did not start; see operator_ui/realsense_worker.log')


def register_realsense(app, service=None):
    from flask import Response, jsonify, request
    service = service or RealSenseService()

    @app.get('/realsense/status')
    def rs_status():
        response = jsonify(service.status())
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/realsense/viewer')
    def rs_viewer():
        try:
            return jsonify(service.launch())
        except Exception as ex:
            return jsonify(ok=False, error=str(ex)), 503

    @app.route('/realsense/<path:action>', methods=['GET', 'POST'])
    def rs_proxy(action):
        permitted = {'GET': {'image/color', 'image/depth', 'cloud.ply'},
                     'POST': {'start', 'stop', 'snapshot'}}
        if action not in permitted.get(request.method, set()):
            return jsonify(ok=False, error='Unknown depth action'), 404
        try:
            if request.method == 'POST' and action == 'start':
                service.launch()
            content, mime, code = service.request('/'+action,
                (request.get_json(silent=True) or {}) if request.method == 'POST' else None,
                timeout=15 if action == 'snapshot' else 5)
            response = Response(content, status=code, content_type=mime)
            response.headers['Cache-Control'] = 'no-store'
            if action == 'cloud.ply' and code == 200:
                response.headers['Content-Disposition'] = 'attachment; filename="d405_cloud_meters.ply"'
            return response
        except Exception as ex:
            return jsonify(ok=False, error=str(ex)), 503

    return service
