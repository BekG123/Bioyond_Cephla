"""Headless Edge UI/WebGL check against fake-robot preview; no arm commands."""
import asyncio
import argparse
import base64
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
import websockets

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT/'operator_ui/reports/realsense_setup_20261012'


async def check(ws_url, console_url, live=False):
    async with websockets.connect(ws_url,max_size=30_000_000) as ws:
        seq = 0
        errors = []
        async def call(method,params=None):
            nonlocal seq
            seq += 1; ident = seq
            await ws.send(json.dumps(dict(id=ident,method=method,params=params or {})))
            while True:
                message = json.loads(await asyncio.wait_for(ws.recv(),30))
                if message.get('method') == 'Runtime.exceptionThrown': errors.append(message['params'])
                if message.get('id') == ident:
                    if 'error' in message: raise RuntimeError(message['error'])
                    return message.get('result',{})
        async def evaluate(expression):
            result = await call('Runtime.evaluate',dict(expression=expression,returnByValue=True,awaitPromise=True))
            if 'exceptionDetails' in result: raise RuntimeError(result['exceptionDetails'])
            return result.get('result',{}).get('value')
        async def until(expression, seconds=20):
            deadline = time.monotonic()+seconds
            while time.monotonic()<deadline:
                if await evaluate(expression): return
                await asyncio.sleep(.2)
            raise AssertionError('UI did not reach: '+expression)
        await call('Page.enable'); await call('Runtime.enable')
        await call('Emulation.setDeviceMetricsOverride',dict(width=1500,height=1100,deviceScaleFactor=1,mobile=False))
        await call('Page.navigate',dict(url=console_url + ('/developer' if ':5002' in console_url else '/')))
        await until("typeof RealSenseUI !== 'undefined'")
        await evaluate("document.getElementById('tabbtn-depth').click()")
        if live:
            await until("document.getElementById('rs-status').textContent.includes('STREAMING') && document.getElementById('rs-depth').naturalWidth > 0")
        else:
            await until("document.getElementById('rs-status').textContent.includes('IDLE')")
            await evaluate("document.getElementById('rs-demo').click()")
            await until("document.getElementById('rs-status').textContent.includes('SYNTHETIC SAMPLE') && document.getElementById('rs-depth').naturalWidth > 0")
        await asyncio.sleep(3)
        # Viser's separate origin has its own page target; inspect its frame via CDP.
        tree = await call('Page.getFrameTree')
        frame = next(f['frame']['id'] for f in tree['frameTree']['childFrames'] if ':8086' in f['frame']['url'])
        world = await call('Page.createIsolatedWorld',dict(frameId=frame,worldName='depth-check'))
        canvas = await call('Runtime.evaluate',dict(contextId=world['executionContextId'],
            expression="({canvas:!!document.querySelector('canvas'),text:document.body.innerText})",returnByValue=True))
        value = canvas['result']['value']
        assert value['canvas'], 'Viser WebGL canvas missing'
        assert ('STREAMING' if live else 'SYNTHETIC') in value['text'], value
        shot = await call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=False))
        (OUTPUT/('depth_tab_live.png' if live else 'depth_tab_sample.png')).write_bytes(base64.b64decode(shot['data']))
        assert await evaluate("!document.getElementById('rs-snapshot').disabled")
        await evaluate("document.getElementById('rs-snapshot').click()")
        await until("document.getElementById('rs-result').textContent.includes('Saved " + ('D405' if live else 'synthetic') + " capture')")
        saved = await evaluate("document.getElementById('rs-result').textContent")
        if live:
            assert not errors, errors
            report = dict(ok=True,source='D405',viser_canvas=True,snapshot=saved,
                browser_errors=errors,hardware_commands=False,stream_left_running=True)
            (OUTPUT/'browser_live_check.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report,indent=2))
            return
        await evaluate("document.getElementById('rs-stop').click()")
        await until("document.getElementById('rs-status').textContent.includes('IDLE') && document.getElementById('rs-depth').hidden")
        assert await evaluate("document.getElementById('rs-snapshot').disabled")
        await evaluate("document.getElementById('tabbtn-console').click()")
        assert await evaluate("document.getElementById('tab-depth').style.display === 'none' && document.getElementById('main').style.display !== 'none'")
        assert not errors, errors
        report = dict(ok=True,viser_canvas=True,synthetic_label=True,snapshot=saved,
            stop_cleared_images=True,tab_switch=True,browser_errors=errors,hardware_commands=False)
        (OUTPUT/'browser_check.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', choices=['http://127.0.0.1:5004','http://127.0.0.1:5002'], default='http://127.0.0.1:5004')
    parser.add_argument('--live', action='store_true', help='Check the already-running D405 stream and leave it running')
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='d405_edge_') as profile:
        process = subprocess.Popen([r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
            '--headless=new','--no-first-run','--no-default-browser-check','--enable-unsafe-swiftshader',
            '--remote-debugging-port=9338','--remote-allow-origins=http://localhost:9338',
            '--user-data-dir='+profile,'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(50):
                try:
                    with urllib.request.urlopen('http://localhost:9338/json',timeout=1) as r: tabs=json.load(r)
                    break
                except OSError: time.sleep(.1)
            else: raise RuntimeError('Headless Edge did not start')
            asyncio.run(check(next(t['webSocketDebuggerUrl'] for t in tabs if t['type']=='page'),args.url,args.live))
        finally:
            process.terminate(); process.wait(timeout=10)
