"""Fixture-only browser checks. All HTTP is local fake data; no hardware app import."""
import asyncio
import base64
import json
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import urllib.request

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.serving import make_server
import websockets

UI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UI))
from developer_diagnostics import DeveloperDiagnostics, register_developer_diagnostics


async def check(ws_url, url, output):
    async with websockets.connect(ws_url, max_size=30000000) as ws:
        serial = 0
        errors = []

        async def call(method, params=None):
            nonlocal serial
            serial += 1
            await ws.send(json.dumps(dict(id=serial, method=method, params=params or {})))
            while True:
                message = json.loads(await asyncio.wait_for(ws.recv(), 20))
                if message.get('method') == 'Runtime.exceptionThrown':
                    errors.append(message['params'])
                if message.get('id') == serial:
                    assert 'error' not in message, message
                    return message.get('result', {})

        async def js(expression):
            result = await call('Runtime.evaluate', dict(expression=expression, returnByValue=True, awaitPromise=True))
            assert 'exceptionDetails' not in result, result
            return result.get('result', {}).get('value')

        async def until(expression):
            for _ in range(100):
                if await js(expression):
                    return
                await asyncio.sleep(.1)
            raise AssertionError(expression)

        await call('Runtime.enable')
        await call('Emulation.setDeviceMetricsOverride', dict(width=1440, height=1100, deviceScaleFactor=1, mobile=False))
        await call('Page.navigate', dict(url=url))
        await until("document.readyState==='complete' && window.DeveloperConsole && document.getElementById('dsl-error').textContent.includes('offline fixture')")
        assert await js("!document.getElementById('dev-legacy').open")
        assert await js("document.querySelector('#right > .card h2').textContent==='Connection & state'")
        assert await js("document.getElementById('dev-api-settings').contains(document.getElementById('imitation-key'))")
        assert await js("document.querySelectorAll('#right > div.card').length===3")
        image = await call('Page.captureScreenshot', dict(format='png'))
        (output/'developer_console.png').write_bytes(base64.b64decode(image['data']))
        await js("showTab('3d')")
        await until("document.getElementById('three3d').querySelector('canvas') !== null")
        await js("showTab('dsl'); document.getElementById('dsl-example').click()")
        await until("document.getElementById('dsl-editor').value.includes('count = 0')")
        await js("document.getElementById('dsl-translate').click()")
        await until("document.getElementById('dsl-python').textContent.includes('def decide')")
        assert await js("document.getElementById('dsl-roundtrip').textContent.includes('IF Machine.parked & no.tips')")
        image = await call('Page.captureScreenshot', dict(format='png', captureBeyondViewport=True))
        (output/'developer_dsl.png').write_bytes(base64.b64decode(image['data']))
        await js("document.getElementById('dsl-editor').value += ';'; document.getElementById('dsl-editor').dispatchEvent(new Event('input')); document.getElementById('dsl-translate').click()")
        await until("document.getElementById('dsl-status').textContent.includes('Semicolons')")
        assert await js("!document.getElementById('dsl-python').textContent.includes('def decide')")
        await call('Emulation.setDeviceMetricsOverride', dict(width=390, height=844, deviceScaleFactor=1, mobile=True))
        assert await js("document.documentElement.scrollWidth <= 392")
        await js("showTab('console')")
        assert await js("document.documentElement.scrollWidth <= 392")
        assert not errors, errors
        return dict(ok=True, checks=['essential controls', 'API key retained', 'legacy collapsed',
            '3D canvas', 'DSL compile and roundtrip', 'invalid draft clears preview', 'mobile layout'], browser_errors=errors)


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    output = UI/'reports/developer_ui'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        diagnostics = DeveloperDiagnostics(Path(folder)/'diagnostics')
        diagnostics.observe('sequence_finished', dict(sequence='fixture', result=dict(ok=False,
            error='Delayed parking — offline fixture', failure_context=dict(location=dict(
                path='operator_ui/hamilton_prep.py', line=1, function='fixture_only'), source_start_line=1,
                source='def fixture_only():\n    if not parked:\n        raise RuntimeError("not ready")'))))
        app = Flask(__name__, static_folder=str(UI/'static'))
        seen = []
        register_developer_diagnostics(app, diagnostics,
            lambda: SimpleNamespace(snapshot=lambda: dict(state='idle', result=None)),
            lambda: None, lambda: SimpleNamespace(ready=lambda: False))

        @app.get('/')
        def page():
            return send_from_directory(UI/'static', 'index.html')

        @app.route('/<path:path>', methods=['GET', 'POST', 'OPTIONS'])
        def fake(path):
            if request.method == 'POST':
                seen.append(path)
                return jsonify(ok=False, error='Hardware writes forbidden in browser fixture'), 403
            if path == 'state':
                return jsonify(robot=dict(connected=False), camera=dict(enabled=False),
                    envelope=dict(X=dict(min=200,max=450),Y=dict(min=-250,max=380),Z=dict(min=70,max=400)),
                    envelope_enabled=True)
            if path == 'seq':
                return jsonify(active=False, state='idle', name='', log=[], result=None, target=None)
            if path == 'points':
                return jsonify(points={}, roles={}, motion_order=['z','rz','xy'])
            if path == 'robot_params':
                return jsonify(json.loads((UI/'robot_params.json').read_text()))
            return jsonify(ok=True, active=False, state='idle', items=[], counts={}, configured=False,
                           references=[], proposals=[], log=[], message='Offline fixture')

        server = make_server('127.0.0.1', 0, app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        profile = Path(folder)/'edge'
        browser = subprocess.Popen([r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
            '--headless=new','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',
            '--user-data-dir='+str(profile),'about:blank'], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            portfile = profile/'DevToolsActivePort'
            for _ in range(100):
                if portfile.exists(): break
                time.sleep(.1)
            port = int(portfile.read_text().splitlines()[0])
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/json') as response:
                tabs = json.load(response)
            result = asyncio.run(check(next(t['webSocketDebuggerUrl'] for t in tabs if t['type']=='page'),
                                       f'http://127.0.0.1:{server.server_port}', output))
            assert not seen, seen
            (output/'check.json').write_text(json.dumps(result, indent=2))
            print(json.dumps(result))
        finally:
            browser.terminate()
            browser.wait(timeout=10)
            server.shutdown()


if __name__ == '__main__':
    main()
