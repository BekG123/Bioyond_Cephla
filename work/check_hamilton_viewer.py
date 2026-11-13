"""Offline browser check using synthetic events; never calls Hamilton."""
import asyncio
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
import websockets


async def check(url):
    async with websockets.connect(url, max_size=30000000) as ws:
        serial = 0
        errors = []
        async def call(method, params=None):
            nonlocal serial
            serial += 1
            await ws.send(json.dumps(dict(id=serial, method=method, params=params or {})))
            while True:
                r = json.loads(await ws.recv())
                if r.get('method') == 'Runtime.exceptionThrown': errors.append(r['params'])
                if r.get('id') == serial: return r.get('result', {})
        async def ev(expression):
            r = await call('Runtime.evaluate', dict(expression=expression, returnByValue=True))
            assert not r.get('exceptionDetails'), r
            return r.get('result', {}).get('value')
        async def click(selector):
            point=await ev("(()=>{const e=document.querySelector("+json.dumps(selector)+");e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
            await call('Input.dispatchMouseEvent',dict(type='mousePressed',button='left',clickCount=1,**point))
            await call('Input.dispatchMouseEvent',dict(type='mouseReleased',button='left',clickCount=1,**point))
        async def head():
            return await ev("(()=>{const r=document.querySelector('#pipette').getBoundingClientRect();return [r.x,r.y]})()")
        await call('Page.enable')
        await call('Runtime.enable')
        await call('Emulation.setDeviceMetricsOverride',dict(width=1100,height=950,deviceScaleFactor=1,mobile=False))
        html = Path('work/hamilton-dry-run-replay.html' if '--replay' in sys.argv else 'operator_ui/static/hamilton-dry-run.html').read_text(encoding='utf-8')
        events = [dict(at=100+c*20+j*5, mode=m, column=c+1, site=s, well='A'+str(c+1))
                  for c in range(6) for j,(m,s) in enumerate([('Pick-Up Tips',7),('Aspirate',2),('Dispense',3),('Eject Tips',9)])]
        sample=dict(status='Completed',completed=6,events=events,updated=time.time())
        if '--replay' not in sys.argv:
            html=html.replace('<script>','<script>window.fetch=async()=>({json:async()=>('+json.dumps(sample)+')});',1)
        if '--replay' in sys.argv:
            await call('Page.navigate',dict(url=Path('work/hamilton-dry-run-replay.html').resolve().as_uri()))
        else:
            tree=await call('Page.getFrameTree')
            await call('Page.setDocumentContent',dict(frameId=tree['frameTree']['frame']['id'],html=html))
        await asyncio.sleep(1)
        assert await ev("document.body.dataset.rendered") == 'true'
        assert await ev("document.querySelector('#replay').disabled") is False
        # Restart after a stale animation clock, using actual pointer events.
        await ev('lastFrame=performance.now()-60000')
        await click('#replay')
        before=await head()
        await asyncio.sleep(.3)
        assert 0 < float(await ev("document.querySelector('#scrub').value")) < 1
        assert await head()!=before, 'Timer advanced but visible head did not move'
        await click('#pause')
        v=await ev("document.querySelector('#scrub').value")
        stopped=await head()
        await asyncio.sleep(.2)
        assert await ev("document.querySelector('#scrub').value") == v
        assert await head()==stopped, 'Paused head is still moving'
        await ev("document.querySelector('#scrub').value=14;document.querySelector('#scrub').dispatchEvent(new Event('input'))")
        assert await head()!=stopped, 'Scrubbing did not move head'
        await click('#replay')
        for _ in range(340):
            await asyncio.sleep(.1)
            if await ev('seconds>=30'):break
        assert await ev('seconds')==30, 'Replay did not finish'
        assert await ev("document.querySelector('#count').textContent")=='6 / 6 wells'
        assert await ev("document.querySelectorAll('.well.done').length")==6
        end=await head()
        await click('#replay')
        await asyncio.sleep(.25)
        assert 0<float(await ev('seconds'))<1, 'Second replay did not restart'
        assert await head()!=end, 'Head did not restart after completed playback'
        await click('#pause')
        shot=await call('Page.captureScreenshot',dict(format='png'))
        Path('work/hamilton-viewer-check.png').write_bytes(base64.b64decode(shot['data']))
        await call('Emulation.setDeviceMetricsOverride',dict(width=390,height=840,deviceScaleFactor=1,mobile=True))
        await asyncio.sleep(.2)
        assert await ev('document.documentElement.scrollWidth<=390')
        assert not errors,errors
        print('PASS: real pointer click, visible head motion, stale clock reset, frozen pause, scrub, full 30-second completion, second replay, narrow layout; no JS errors.')


with tempfile.TemporaryDirectory(prefix='hamilton_view_check_',ignore_cleanup_errors=True) as profile:
    process=subprocess.Popen([r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe','--headless=new','--no-first-run','--no-default-browser-check','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        portfile=Path(profile)/'DevToolsActivePort'
        for _ in range(100):
            if portfile.exists():break
            time.sleep(.1)
        port=int(portfile.read_text().splitlines()[0])
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/json',timeout=5) as r:tabs=json.load(r)
        asyncio.run(check(next(t['webSocketDebuggerUrl'] for t in tabs if t['type']=='page')))
    finally:
        process.terminate()
        process.wait(timeout=10)
