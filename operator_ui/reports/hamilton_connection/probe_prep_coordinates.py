"""Read-only Prep TCP discovery and camera capture. No motion entry point.

Uses a pinned local PyLabRobot checkout, never PrepDriver.setup/stop (which
can move). Only the transport handshake, introspection and listed status
requests are allowed. No reconnect or retry after an ambiguous response.
"""
import argparse
import asyncio
import base64
import io
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from urllib.request import ProxyHandler, build_opener
import zipfile

WORKSPACE = Path(__file__).resolve().parents[2]
SOURCE = WORKSPACE / 'tmp/prep-jog-audit'
PIN = 'fc5ae129c39ef645a2a11234dce97f933a317a9c'
BASE = 'http://192.168.100.101/NimbusLite/api/v1/'
QUERY_NAMES = (
    'PrepGetIsInitialized', 'PrepGetPositions', 'PrepGetChannelBounds',
    'PrepGetPresentChannels', 'PrepGetIsEnclosurePresent',
    'PrepGetSafeSpeedsEnabled', 'PrepGetDefaultTraverseHeight',
    'PrepGetDeckBounds', 'PrepGetDeckSiteDefinitions',
    'PrepGetCalibrationSiteDefinitions',
    'PrepGetTipAndNeedleDefinitions',
)


def http_snapshot(output, capture):
    opener = build_opener(ProxyHandler({}))
    def get(path):
        with opener.open(BASE + path, timeout=12) as response:
            return response.read()
    snapshot = {}
    for path in ('instruments/connection-info', 'instruments/global-run-state',
                 'service-software-api/sensor-status', 'service-software-api/is-parked',
                 'service-software-api/has-tips', 'errors/check-for-pending-errors'):
        value = get(path)
        snapshot[path] = json.loads(value) if value else None
    if 'Serial Number: PRPGD2427' not in snapshot['instruments/connection-info']:
        raise RuntimeError('Unexpected instrument identity; no TCP connection attempted.')
    if snapshot['instruments/global-run-state'] != 'Idle':
        raise RuntimeError('Instrument is not Idle; no TCP connection attempted.')
    if capture:
        for filename, path in (
            ('raw_current.png', 'camera/false'),
            ('crop_current75.png', 'camera/position/4/0/75'),
        ):
            (output / filename).write_bytes(get(path))
        exported = get('calibration/export')
        if exported.startswith(b'PK'):
            payload = exported
        else:
            metadata = json.loads(exported)
            payload = base64.b64decode(metadata.get('FileBytes', metadata.get('fileBytes', '')))
        (output / 'calibration_export.zip').write_bytes(payload)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            snapshot['calibration_members'] = archive.namelist()
            for member in archive.namelist():
                if member.lower().endswith('.json'):
                    try:
                        data = json.loads(archive.read(member))
                    except (ValueError, UnicodeError):
                        continue
                    if isinstance(data, dict) and all(k in data for k in ('CameraCalibration', 'Rotation', 'Translation')):
                        (output / 'deck-calibration.json').write_text(json.dumps(data), encoding='utf-8')
    return snapshot


async def probe(report, save):
    revision = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != PIN:
        raise RuntimeError('PyLabRobot revision changed; review it before probing.')
    sys.path.insert(0, str(SOURCE))
    from pylabrobot.hamilton.prep.driver.master import PrepDriver
    from pylabrobot.hamilton.prep.driver import prep_commands as commands
    from pylabrobot.hamilton.prep.driver.configuration import to_jsonable
    from pylabrobot.hamilton.transport.tcp.tcp import HamiltonTCPClient
    from pylabrobot.resources.deck import Deck

    allowed = {getattr(commands, name) for name in QUERY_NAMES}
    class ReadOnlyDriver(PrepDriver):
        async def send_command(self, command, **kwargs):
            if type(command) not in allowed or not isinstance(command, commands.PrepStatusRequest):
                raise RuntimeError('Command is not in the read-only allowlist.')
            return await super().send_command(command, **kwargs)

        async def setup(self, **kwargs):
            raise RuntimeError('High-level setup is disabled for the read-only probe.')

        async def stop(self, **kwargs):
            raise RuntimeError('Use transport-only close; high-level stop can move.')

    client = HamiltonTCPClient(host='192.168.100.102', port=2000, read_timeout=8, write_timeout=5)
    driver = ReadOnlyDriver(deck=Deck(name='probe_deck', size_x=300, size_y=400, size_z=200), io=client)
    driver.default_read_timeout = 8
    report['pylabrobot_commit'] = revision
    report['tcp_queries'] = {}
    try:
        await asyncio.wait_for(driver._open(), timeout=30)
        report['tcp_connected'] = True
        save()
        for name in QUERY_NAMES:
            response = await asyncio.wait_for(driver.send_command(getattr(commands, name)()), timeout=20)
            report['tcp_queries'][name] = to_jsonable(response)
            print(name + ': ' + json.dumps(to_jsonable(response))[:1800], flush=True)
            save()
    finally:
        await driver._close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true')
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    output = Path(__file__).parent / ('coordinate_probe_' + now.strftime('%Y%m%dT%H%M%SZ'))
    output.mkdir()
    report = {'time_utc': now.isoformat(), 'read_only': True, 'motion_sent': False,
              'tip_rack_site': 4, 'plate_site': 8, 'output_directory': str(output)}
    def save():
        (output / 'probe.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    try:
        report['http_before'] = http_snapshot(output, args.capture)
        save()
        asyncio.run(probe(report, save))
        report['http_after'] = http_snapshot(output, False)
    except Exception as error:
        report['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        save()
        print('Report: ' + str(output / 'probe.json'), flush=True)
    return output


if __name__ == '__main__':
    main()
