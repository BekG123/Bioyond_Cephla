"""Check the local 3D visualization in an isolated headless browser. No devices."""
import asyncio
import base64
import functools
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import urllib.request
import websockets

OUTPUT=Path(__file__).parent/'demo_output'


async def inspect(ws_url,url):
    async with websockets.connect(ws_url,max_size=30000000) as ws:
        seq=0;contexts=[];errors=[]
        async def call(method,params=None):
            nonlocal seq
            seq+=1;mid=seq
            await ws.send(json.dumps(dict(id=mid,method=method,params=params or {})))
            while True:
                r=json.loads(await ws.recv())
                if r.get('method')=='Runtime.executionContextCreated':contexts.append(r['params']['context']['id'])
                if r.get('method')=='Runtime.exceptionThrown':errors.append(r['params'])
                if r.get('id')==mid:
                    if 'error' in r:raise RuntimeError(r['error'])
                    return r.get('result',{})
        await call('Runtime.enable');await call('Page.enable')
        await call('Emulation.setDeviceMetricsOverride',dict(width=900,height=820,deviceScaleFactor=1,mobile=False))
        await call('Emulation.setEmulatedMedia',dict(features=[dict(name='prefers-color-scheme',value='light')]))
        await call('Page.navigate',dict(url=url))
        await asyncio.sleep(1)
        await call('Runtime.evaluate',dict(expression='1'))
        frame=None
        for cid in contexts:
            try:
                r=await call('Runtime.evaluate',dict(contextId=cid,expression="!!document.getElementById('plate-canvas')",returnByValue=True))
                if r.get('result',{}).get('value'):frame=cid;break
            except RuntimeError:pass
        if frame is None:raise RuntimeError('3D frame not found')
        async def evaluate(expression):
            r=await call('Runtime.evaluate',dict(contextId=frame,expression=expression,returnByValue=True))
            if r.get('exceptionDetails'):raise RuntimeError(r['exceptionDetails'])
            return r.get('result',{}).get('value')
        assert await evaluate("document.getElementById('plate-canvas').dataset.rendered")=='true'
        for mode in ('plate','scene'):
            await evaluate("(()=>{const s=document.getElementById('plate-view');s.value="+json.dumps(mode)+";s.dispatchEvent(new Event('change'));return s.value})()")
            await asyncio.sleep(.15)
            screenshot=await call('Page.captureScreenshot',dict(format='png'))
            (OUTPUT/('3d_'+mode+'.png')).write_bytes(base64.b64decode(screenshot['data']))
        await evaluate("(()=>{const s=document.getElementById('plate-orbit');s.value=80;s.dispatchEvent(new Event('input'));const p=document.getElementById('plate-pose');p.value=2;p.dispatchEvent(new Event('input'));return document.getElementById('plate-detail').textContent})()")
        assert 'Tilted' in await evaluate("document.getElementById('plate-detail').textContent")
        await call('Emulation.setDeviceMetricsOverride',dict(width=360,height=820,deviceScaleFactor=1,mobile=False))
        await asyncio.sleep(.15)
        assert await evaluate('document.documentElement.scrollWidth<=360')
        if errors:raise RuntimeError(errors)
        print('3D render passed: both views, orbit, pose switch, 360px layout; no JavaScript exceptions.')


if __name__=='__main__':
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if self.path!='/preview':return super().do_GET()
            css=Path('C:/Users/Cephla/.codex/plugins/cache/openai-bundled/visualize/1.0.37/skills/visualize/assets/visualize.css').read_text(encoding='utf-8')
            fragment=(OUTPUT/'plate-scene-3d.html').read_text(encoding='utf-8')
            body=('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>'+css+'body{padding:20px;margin:0}</style>'+fragment).encode('utf-8')
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(OUTPUT)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='plate_3d_',ignore_cleanup_errors=True) as profile:
            process=subprocess.Popen([r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                '--headless=new','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',
                '--user-data-dir='+profile,'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                portfile=Path(profile)/'DevToolsActivePort'
                for _ in range(100):
                    if portfile.exists():break
                    time.sleep(.1)
                port=int(portfile.read_text().splitlines()[0])
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/json',timeout=5) as response:tabs=json.load(response)
                asyncio.run(inspect(next(t['webSocketDebuggerUrl'] for t in tabs if t['type']=='page'),
                    f'http://127.0.0.1:{server.server_port}/preview'))
            finally:process.terminate();process.wait(timeout=10)
    finally:server.shutdown()
