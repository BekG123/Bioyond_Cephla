"""Deterministic 1080p/30fps export of the local explainer. No hardware access."""
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request

import cv2
import imageio_ffmpeg
from PIL import Image, ImageDraw
import websockets

ROOT=Path(__file__).parent
SOURCE=ROOT/'48-well-calibration-cinematic.html'
OUTPUT=Path.home()/'Downloads/Cephla_48_well_calibration.mp4'
FPS=30
FRAMES=900

async def export(url):
    async with websockets.connect(url,max_size=30000000) as ws:
        count=0;errors=[]
        async def call(method,params=None):
            nonlocal count
            count+=1;ident=count
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
        await call('Page.enable');await call('Runtime.enable')
        await call('Emulation.setDeviceMetricsOverride',dict(width=1920,height=1180,deviceScaleFactor=1,mobile=False))
        tree=await call('Page.getFrameTree')
        html=('<!doctype html><html><head><meta charset="utf-8"><style>'
              'html,body{margin:0;padding:0;background:#111536;font-family:system-ui}'
              '#cephla-film .cf-screen{width:1920px!important;height:1080px!important;min-height:0!important;border-radius:0!important}'
              '</style></head><body>'+SOURCE.read_text(encoding='utf-8')+'</body></html>')
        await call('Page.setDocumentContent',dict(frameId=tree['frameTree']['frame']['id'],html=html))
        await asyncio.sleep(.3)
        assert await ev("document.querySelector('canvas').dataset.rendered")=='true'
        assert await ev("document.querySelector('.cf-title')===null")
        assert await ev("document.querySelector('.cf-caption').textContent.length>20")
        log=ROOT/'calibration-mp4-encoder.log'
        with log.open('w',encoding='utf-8') as stderr:
            encoder=subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','warning','-y',
                '-f','image2pipe','-framerate',str(FPS),'-vcodec','mjpeg','-i','pipe:0','-an',
                '-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p',
                '-movflags','+faststart','-metadata','title=Cephla: 48-well calibration',str(OUTPUT)],
                stdin=subprocess.PIPE,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                for frame in range(FRAMES):
                    await ev(f"(()=>{{const s=document.getElementById('cf-seek');s.value={frame/FPS:.8f};s.dispatchEvent(new Event('input'));}})()")
                    screenshot=await call('Page.captureScreenshot',dict(format='jpeg',quality=95,
                        clip=dict(x=0,y=0,width=1920,height=1080,scale=1),captureBeyondViewport=False))
                    encoder.stdin.write(base64.b64decode(screenshot['data']))
                    if (frame+1)%150==0:print(f'Rendered {frame+1}/{FRAMES} frames ({(frame+1)/FPS:.0f}/30 seconds)',flush=True)
                encoder.stdin.close()
                if encoder.wait(timeout=60)!=0:raise RuntimeError(log.read_text())
            except BaseException:
                encoder.kill();encoder.wait();raise
        if errors:raise RuntimeError(errors)

def verify():
    video=cv2.VideoCapture(str(OUTPUT))
    count=int(video.get(cv2.CAP_PROP_FRAME_COUNT));fps=video.get(cv2.CAP_PROP_FPS)
    width=int(video.get(cv2.CAP_PROP_FRAME_WIDTH));height=int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))
    assert count==FRAMES and abs(fps-FPS)<.01 and (width,height)==(1920,1080),(count,fps,width,height)
    montage=Image.new('RGB',(960,852),'#111536')
    draw=ImageDraw.Draw(montage)
    for i,sec in enumerate([2,7,11.5,17,22,28]):
        video.set(cv2.CAP_PROP_POS_FRAMES,round(sec*FPS));ok,frame=video.read();assert ok
        image=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)).resize((480,270))
        x=(i%2)*480;y=(i//2)*284
        montage.paste(image,(x,y));draw.text((x+8,y+271),f'{sec:g} seconds',fill='white')
    video.release();montage.save(ROOT/'calibration-mp4-contact-sheet.jpg',quality=95)
    result=dict(output=str(OUTPUT),width=width,height=height,fps=fps,frames=count,duration_s=count/fps,
                bytes=OUTPUT.stat().st_size,sha256=hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
                source=str(SOURCE),source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                titles_removed=True,subtitles_retained=True,audio=False,
                created_at=datetime.now(timezone.utc).isoformat(),hardware_access=False)
    (ROOT/'calibration-mp4-export.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)

if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='cephla_video_',ignore_cleanup_errors=True) as profile:
        proc=subprocess.Popen([r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe','--headless=new','--no-first-run','--no-default-browser-check','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            portfile=Path(profile)/'DevToolsActivePort'
            for _ in range(100):
                if portfile.exists():break
                time.sleep(.1)
            port=int(portfile.read_text().splitlines()[0])
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/json',timeout=5) as r:tabs=json.load(r)
            asyncio.run(export(next(x['webSocketDebuggerUrl'] for x in tabs if x['type']=='page')))
        finally:proc.terminate();proc.wait(timeout=10)
    verify()
