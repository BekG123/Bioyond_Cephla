"""Send one authorized dry-pickup diagnostic request, then record events.

Requires an explicit --start-confirmed argument. Never retries a start request.
Does not acknowledge dialogs or change labware/calibration automatically.
"""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

import websockets

BASE = 'http://192.168.100.101/NimbusLite/api/v1/'
WS = 'ws://192.168.100.101/NimbusLite/'
PAYLOAD = {
    'channelSelection': 'OneChannel',
    'tipLabwareId': 273,
    'deckPosition': 3,
    'ejectToWaste': True,
}
OPENER = build_opener(ProxyHandler({}))
JOURNAL = Path(__file__).with_name(
    'core_pickup_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.jsonl'
)


def record(kind, data):
    line = json.dumps({'time': datetime.now(timezone.utc).isoformat(),
                       'kind': kind, 'data': data}, ensure_ascii=True)
    with JOURNAL.open('a', encoding='utf-8') as stream:
        stream.write(line + '\n')
    print(line, flush=True)


def request(endpoint, method='GET', payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = Request(BASE + endpoint, data=body, method=method,
                  headers={'Content-Type': 'application/json'})
    with OPENER.open(req, timeout=20) as response:
        raw = response.read().decode()
        try:
            value = json.loads(raw) if raw else None
        except ValueError:
            value = raw
        return {'status': response.status, 'body': value}


async def listen(socket, name):
    async for message in socket:
        try:
            message = json.loads(message)
        except (TypeError, ValueError):
            pass
        record(name, message)


async def main():
    state = await asyncio.to_thread(request, 'instruments/global-run-state')
    errors = await asyncio.to_thread(request, 'errors/check-for-pending-errors')
    tips = await asyncio.to_thread(request, 'service-software-api/has-tips')
    sensors = await asyncio.to_thread(request, 'service-software-api/sensor-status')
    info = await asyncio.to_thread(request, 'instruments/connection-info')
    run = await asyncio.to_thread(request, 'protocol-run')
    verification = await asyncio.to_thread(request, 'verification/status')
    record('preflight', {'state': state, 'errors': errors, 'has_tips': tips,
                        'sensors': sensors, 'info': info, 'run': run,
                        'verification': verification})
    if (sensors['body'].get('isDoorClosed') is not True
            or sensors['body'].get('isEnclosurePresent') is not True
            or 'Initialization Status: Initialized' not in info['body']
            or 'Serial Number: PRPGD2427' not in info['body']
            or run['body'].get('isRunInProgress')
            or any(verification['body'].get(key) for key in
                   ('isWorkflowInProgress', 'isRunInProgress', 'isServiceRoutineInProgress'))):
        raise RuntimeError('Door, initialization, identity or workflow preflight failed; no start sent.')
    if state['body'] != 'Idle' or errors['body'] or tips['body'] is not False:
        raise RuntimeError('Preflight changed; no start request sent.')
    async with websockets.connect(WS + 'instinctevents', open_timeout=10, proxy=None) as events:
        async with websockets.connect(WS + 'instincterrors', open_timeout=10, proxy=None) as errors_ws:
            listeners = [asyncio.create_task(listen(events, 'instinctevents')),
                         asyncio.create_task(listen(errors_ws, 'instincterrors'))]
            await asyncio.sleep(0.5)
            record('start_request', PAYLOAD)
            try:
                result = await asyncio.to_thread(request,
                    'diagnostics/instrument/tip-pickup', 'PUT', PAYLOAD)
                record('start_response', result)
            except Exception as error:
                record('start_outcome_uncertain_do_not_retry', str(error))
            for _ in range(9):
                await asyncio.sleep(4)
                for endpoint in ['instruments/global-run-state',
                                 'errors/check-for-pending-errors',
                                 'service-software-api/sensor-status']:
                    try:
                        record(endpoint, await asyncio.to_thread(request, endpoint))
                    except Exception as error:
                        record('monitor_error', str(error))
            for task in listeners:
                task.cancel()
            await asyncio.gather(*listeners, return_exceptions=True)
    for endpoint in ['traces?offset=0&limit=20&sources=RTE,SDE',
                     'errors?offset=0&limit=5', 'service-software-api/has-tips']:
        record(endpoint, await asyncio.to_thread(request, endpoint))
    print('JOURNAL ' + str(JOURNAL.resolve()), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--start-confirmed', action='store_true', required=True)
    parser.parse_args()
    asyncio.run(main())
