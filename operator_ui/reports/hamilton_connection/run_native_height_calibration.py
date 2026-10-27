"""One native channel-height/squeeze calibration; no retries or guessed prompts."""
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import websockets
from run_camera_hover_trial import preflight, get
from run_core_pickup_test import request, WS

LOG = Path(__file__).with_name('height_squeeze_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.jsonl')

def record(kind, data):
    row = {'time': datetime.now(timezone.utc).isoformat(), 'kind': kind, 'data': data}
    with LOG.open('a') as f:
        f.write(json.dumps(row) + '\n')
    print(json.dumps(row), flush=True)

async def main():
    record('preflight', await asyncio.to_thread(preflight))
    queue = asyncio.Queue()
    async def listen(socket, name):
        try:
            async for raw in socket:
                try: event = json.loads(raw)
                except ValueError: event = raw
                record(name, event)
                await queue.put((name, event))
        except Exception as e:
            await queue.put(('connection_lost', str(e)))
    async with websockets.connect(WS+'instinctevents', proxy=None) as events, websockets.connect(WS+'instincterrors', proxy=None) as errors:
        listeners = [asyncio.create_task(listen(events,'event')), asyncio.create_task(listen(errors,'error'))]
        attempted = False
        terminal_abort = False
        try:
            record('start_request', {'tipLabwareId':273,'tipLabwareSite':4})
            attempted = True
            record('start_response', await asyncio.to_thread(request,'calibration/channel-height-squeeze','POST',{'tipLabwareId':273,'tipLabwareSite':4}))
            deadline = time.monotonic()+180
            activity = False
            answered = set()
            while time.monotonic()<deadline:
                while not queue.empty():
                    kind,event = queue.get_nowait()
                    if kind=='connection_lost' or (kind=='error' and isinstance(event,dict) and event.get('handled') is not True):
                        raise RuntimeError(str(event))
                    if isinstance(event,dict) and event.get('code','').lower() in ('failed','error','aborted'):
                        terminal_abort = event.get('code','').lower()=='aborted'
                        raise RuntimeError(str(event))
                    if isinstance(event,dict) and event.get('code')=='calibrationdata':
                        view = event.get('data')
                        if isinstance(view,str): view=json.loads(view)
                        if isinstance(view,dict) and view.get('id') not in answered and not view.get('spinnerShown',True):
                            message=' '.join(str(x or '') for row in view.get('textSections',[]) for x in row)
                            if view.get('inputType')=='tiprack' and message.strip()=='Select tip labware and place on the deck.':
                                # Exported catalog 273's ReferenceLabwareId is the string 235903,
                                # distinct from its database ID. Operator confirmed site 4.
                                body={'viewId':view['id'],'viewResult':'Ok','labwareId':'235903','labwarePosition':4}
                                answered.add(view['id'])
                                record('rack_selection',body)
                                record('rack_selection_response',await asyncio.to_thread(request,'calibration/close-labware-view','POST',body))
                            elif 'close' in message.lower() and 'door' in message.lower():
                                sensors=await asyncio.to_thread(get,'service-software-api/sensor-status')
                                if sensors.get('isDoorClosed') is not True or sensors.get('isEnclosurePresent') is not True:
                                    raise RuntimeError('Door/enclosure not confirmed for calibration prompt.')
                                answered.add(view['id'])
                                record('door_acknowledgment',await asyncio.to_thread(request,'calibration/close-view','POST',{'viewId':view['id'],'viewResult':'Ok','viewInput':None}))
                            elif 'success' in message.lower() and 'fail' not in message.lower():
                                answered.add(view['id'])
                                record('success_display',view)
                                record('success_acknowledgment',await asyncio.to_thread(request,'calibration/close-view','POST',{'viewId':view['id'],'viewResult':'Ok','viewInput':None}))
                state = await asyncio.to_thread(get,'instruments/global-run-state')
                activity |= state!='Idle'
                record('state',state)
                if activity and state=='Idle':
                    record('ended_requires_result_verification',await asyncio.to_thread(get,'calibration/channel-results'))
                    return
                await asyncio.sleep(3)
            raise TimeoutError('Calibration did not finish within observation deadline.')
        except BaseException as e:
            record('stopped',str(e))
            if attempted and not terminal_abort:
                state=await asyncio.to_thread(get,'instruments/global-run-state')
                if state!='Idle':
                    record('abort_response',await asyncio.to_thread(request,'calibration/abort','POST'))
            raise
        finally:
            for task in listeners: task.cancel()
            await asyncio.gather(*listeners,return_exceptions=True)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--execute-authorized',action='store_true',required=True)
    parser.parse_args()
    asyncio.run(main())
