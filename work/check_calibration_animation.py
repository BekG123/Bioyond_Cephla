"""Offline animation render check; no robot or instrument calls."""
import asyncio
import base64
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
import websockets

ROOT=Path(__file__).parent
CSS=Path('C:/Users/Cephla/.codex/plugins/cache/openai-bundled/visualize/1.0.55/skills/visualize/assets/visualize.css')

async def check(url):
    async with websockets.connect(url,max_size=30000000) as ws:
        count=0
        errors=[]
        async def call(method,params=None):
            nonlocal count
            count+=1
            ident=count
            await ws.send(json.dumps(dict(id=ident,method=method,params=params or {})))
            while True:
                r=json.loads(await ws.recv())
                if r.get('method')=='Runtime.exceptionThrown':errors.append(r['params'])
                if r.get('id')==ident:
                    if 'error' in r:raise RuntimeError(r['error'])
                    return r.get('result',{})
        async def ev(expression):
            r=await call('Runtime.evaluate',dict(expression=expression,returnByValue=True))
            if r.get('exceptionDetails'):raise RuntimeError(r['exceptionDetails'])
            return r.get('result',{}).get('value')
        await call('Page.enable')
        await call('Runtime.enable')
        await call('Emulation.setDeviceMetricsOverride',dict(width=760,height=720,deviceScaleFactor=1,mobile=False))
        tree=await call('Page.getFrameTree')
        fragment=(ROOT/'48-well-calibration-animation.html').read_text(encoding='utf-8')
        html='<html><head><meta charset="utf-8"><style>'+CSS.read_text(encoding='utf-8')+'body{margin:0;padding:16px}</style></head><body>'+fragment+'</body></html>'
        await call('Page.setDocumentContent',dict(frameId=tree['frameTree']['frame']['id'],html=html))
        await asyncio.sleep(.4)
        assert await ev("document.querySelector('canvas').dataset.rendered")=='true'
        await ev("document.querySelector('#well48-play').click()")
        await asyncio.sleep(.3)
        assert float(await ev("document.querySelector('#well48-time').value"))>0
        for i,t in enumerate([2,9,12,18,23,29]):
            await ev(f"(()=>{{const s=document.querySelector('#well48-time');s.value={t};s.dispatchEvent(new Event('input'));return true}})()")
            assert await ev("document.querySelector('canvas').dataset.phase")==str(i)
            image=await call('Page.captureScreenshot',dict(format='png'))
            (ROOT/f'calibration-stage-{i+1}.png').write_bytes(base64.b64decode(image['data']))
        await call('Emulation.setDeviceMetricsOverride',dict(width=360,height=740,deviceScaleFactor=1,mobile=False))
        await asyncio.sleep(.2)
        assert await ev('document.documentElement.scrollWidth<=360')
        image=await call('Page.captureScreenshot',dict(format='png'))
        (ROOT/'calibration-mobile.png').write_bytes(base64.b64decode(image['data']))
        if errors:raise RuntimeError(errors)
        print('PASS: 6 stages, playback, timeline, 360px layout; no JavaScript errors')

if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='calibration_animation_',ignore_cleanup_errors=True) as profile:
        process=subprocess.Popen([r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe','--headless=new','--no-first-run','--no-default-browser-check','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            portfile=Path(profile)/'DevToolsActivePort'
            for _ in range(100):
                if portfile.exists():break
                time.sleep(.1)
            port=int(portfile.read_text().splitlines()[0])
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/json',timeout=5) as r:tabs=json.load(r)
            asyncio.run(check(next(t['webSocketDebuggerUrl'] for t in tabs if t['type']=='page')))
        finally:process.terminate();process.wait(timeout=10)
