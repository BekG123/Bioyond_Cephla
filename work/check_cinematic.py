"""Test the actual exported Edge page, including its sandbox and host bridge."""
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
async def check(url):
    async with websockets.connect(url,max_size=30000000) as ws:
        count=0;errors=[];contexts=[];frame=None
        async def call(method,params=None):
            nonlocal count
            count+=1;ident=count
            await ws.send(json.dumps(dict(id=ident,method=method,params=params or {})))
            while True:
                r=json.loads(await ws.recv())
                if r.get('method')=='Runtime.executionContextCreated':contexts.append(r['params']['context']['id'])
                if r.get('method')=='Runtime.exceptionThrown':errors.append(r['params'])
                if r.get('id')==ident:
                    if 'error' in r:raise RuntimeError(r['error'])
                    return r.get('result',{})
        async def ev(expression):
            r=await call('Runtime.evaluate',dict(expression=expression,returnByValue=True,contextId=frame))
            if r.get('exceptionDetails'):raise RuntimeError(r['exceptionDetails'])
            return r.get('result',{}).get('value')
        await call('Page.enable');await call('Runtime.enable')
        await call('Emulation.setDeviceMetricsOverride',dict(width=1280,height=900,deviceScaleFactor=1,mobile=False))
        await call('Page.navigate',dict(url=(ROOT/'48-well-calibration-edge.html').as_uri()))
        await asyncio.sleep(2)
        await call('Runtime.evaluate',dict(expression='1'))
        for cid in contexts:
            try:
                r=await call('Runtime.evaluate',dict(expression="!!document.getElementById('cf-play')",contextId=cid,returnByValue=True))
                if r.get('result',{}).get('value'):frame=cid;break
            except RuntimeError:pass
        if frame is None:
            shot=await call('Page.captureScreenshot',dict(format='png'))
            (ROOT/'cinematic-load-error.png').write_bytes(base64.b64decode(shot['data']))
            print('contexts',contexts,'errors',errors)
            print(await call('Runtime.evaluate',dict(expression='document.body.innerText',returnByValue=True)))
            print(await call('Page.getFrameTree'))
            raise AssertionError('Animation frame not loaded')
        assert await ev("document.querySelector('canvas').dataset.rendered")=='true'
        await ev("document.querySelector('#cf-play').click()")
        await asyncio.sleep(1.2)
        first=float(await ev("document.querySelector('#cf-seek').value"))
        assert first>.7,first
        await asyncio.sleep(1)
        second=float(await ev("document.querySelector('#cf-seek').value"))
        assert second>first+.5,(first,second)
        await ev("document.querySelector('#cf-play').click()")
        paused=float(await ev("document.querySelector('#cf-seek').value"))
        await asyncio.sleep(.3)
        assert abs(float(await ev("document.querySelector('#cf-seek').value"))-paused)<.01
        angles=[]
        for i,t in enumerate([2,7,11.5,17,22,28]):
            await ev(f"(()=>{{const s=document.querySelector('#cf-seek');s.value={t};s.dispatchEvent(new Event('input'));}})()")
            assert await ev("document.querySelector('canvas').dataset.phase")==str(i)
            angles.append(await ev("document.querySelector('canvas').dataset.elevation"))
            shot=await call('Page.captureScreenshot',dict(format='png'))
            (ROOT/f'cinematic-stage-{i+1}.png').write_bytes(base64.b64decode(shot['data']))
        assert max(map(float,angles))-min(map(float,angles))>.8
        await ev("(()=>{const s=document.querySelector('#cf-seek');s.value=29.5;s.dispatchEvent(new Event('input'));document.querySelector('#cf-play').click();})()")
        await asyncio.sleep(.8)
        assert await ev("document.querySelector('#cf-play').textContent")=='Play again'
        await ev("document.querySelector('#cf-replay').click()")
        await asyncio.sleep(.2)
        assert float(await ev("document.querySelector('#cf-seek').value"))<1
        await call('Emulation.setDeviceMetricsOverride',dict(width=360,height=850,deviceScaleFactor=1,mobile=False))
        await asyncio.sleep(.3)
        shot=await call('Page.captureScreenshot',dict(format='png'))
        (ROOT/'cinematic-mobile.png').write_bytes(base64.b64decode(shot['data']))
        print('mobile',await ev('JSON.stringify({inner:innerWidth,scroll:document.documentElement.scrollWidth,root:document.getElementById("cephla-film").getBoundingClientRect().width,screen:document.querySelector(".cf-screen").getBoundingClientRect().width})'))
        assert await ev('document.documentElement.scrollWidth<=360')
        if errors:raise RuntimeError(errors)
        print('PASS actual exported page: sustained Play, Pause, Replay, end stop, 6 scenes, moving viewpoints, mobile layout; no JS exceptions.')

if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='cephla_film_',ignore_cleanup_errors=True) as profile:
        proc=subprocess.Popen([r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe','--headless=new','--disable-site-isolation-trials','--no-first-run','--no-default-browser-check','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            f=Path(profile)/'DevToolsActivePort'
            for _ in range(100):
                if f.exists():break
                time.sleep(.1)
            port=int(f.read_text().splitlines()[0])
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/json',timeout=5) as r:tabs=json.load(r)
            asyncio.run(check(next(x['webSocketDebuggerUrl'] for x in tabs if x['type']=='page')))
        finally:proc.terminate();proc.wait(timeout=10)
