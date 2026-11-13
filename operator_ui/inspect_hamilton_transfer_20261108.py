"""Read-only native geometry inspection for PRPGJ2494; no motion commands."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from hamilton_prep import HamiltonPrep

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'tmp/prep-jog-audit'
PIN = 'fc5ae129c39ef645a2a11234dce97f933a317a9c'
SERIAL = 'PRPGJ2494'
QUERIES = ('PrepGetIsInitialized', 'PrepGetPositions', 'PrepGetChannelBounds',
           'PrepGetDeckSiteDefinitions', 'PrepGetCalibrationSiteDefinitions',
           'PrepGetTipAndNeedleDefinitions', 'PrepGetPlateHeld')

async def inspect(report):
    revision = subprocess.check_output(
        ['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != PIN:
        raise RuntimeError('Review changed toolkit before connecting')
    sys.path.insert(0, str(SOURCE))
    from pylabrobot.hamilton.prep.driver.master import PrepDriver, MLPREP_CPU_OBJECT_PATH
    from pylabrobot.hamilton.prep.driver import prep_commands as C
    from pylabrobot.hamilton.prep.driver.configuration import to_jsonable
    from pylabrobot.hamilton.transport.tcp.tcp import HamiltonTCPClient
    from pylabrobot.resources.deck import Deck
    allowed = {getattr(C, n) for n in QUERIES}

    class ReadOnly(PrepDriver):
        serial_address = None

        async def send_command(self, command, **kwargs):
            serial_read = (type(command) is C.PrepProbeRequest
                           and self.serial_address is not None
                           and command.dest == self.serial_address
                           and command.command_id == 9 and command.interface_id == 3)
            if not serial_read and (type(command) not in allowed or not isinstance(command, C.PrepStatusRequest)):
                raise RuntimeError('Non-allowlisted command blocked')
            return await super().send_command(command, **kwargs)

        async def setup(self, **kwargs):
            raise RuntimeError('Setup disabled: inspection only')

        async def stop(self, **kwargs):
            raise RuntimeError('Use transport close only')

    driver = ReadOnly(deck=Deck(name='inspection', size_x=300, size_y=400, size_z=200),
        io=HamiltonTCPClient(host='192.168.100.102', port=2000,
                             read_timeout=8, write_timeout=5))
    try:
        await asyncio.wait_for(driver._open(), 20)
        driver.serial_address = await driver._resolve_optional(MLPREP_CPU_OBJECT_PATH)
        serial = await asyncio.wait_for(driver.request_device_serial_number(), 15)
        report['native_serial'] = serial
        print('Native serial:', serial, flush=True)
        if serial != SERIAL:
            raise RuntimeError('Native identity does not match intended Hamilton')
        report['gripper_method_signatures'] = {}
        for path in ('MLPrepRoot.PipettorRoot.Pipettor', 'MLPrepRoot.MLPrep'):
            table = await driver.io.introspection.ensure_method_table(path)
            print('Methods', path, [m.name for m in table], flush=True)
            for method in table:
                if any(s in method.name.lower() for s in ('dcg', 'grip', 'plate', 'tool')):
                    report['gripper_method_signatures'][path + '.' + method.name] = to_jsonable(method)
                    print('Method', method.name, json.dumps(to_jsonable(method))[:3500], flush=True)
        pip = await driver.resolve_path('MLPrepRoot.PipettorRoot.Pipettor')
        report['pipettor_enums'] = to_jsonable(await driver.io.introspection.get_enums(pip, 1))
        print('Pipettor enums:', json.dumps(report['pipettor_enums'])[:5000], flush=True)
        pool = await driver.io.introspection.ensure_global_type_pool()
        report['dcg_channel_enum'] = to_jsonable(pool.resolve_enum(5))
        print('DCG channel enum:', json.dumps(report['dcg_channel_enum']), flush=True)
        report['queries'] = {}
        for name in QUERIES:
            value = to_jsonable(await asyncio.wait_for(
                driver.send_command(getattr(C, name)()), 15))
            report['queries'][name] = value
            print(name, json.dumps(value)[:2200], flush=True)
    finally:
        await driver._close()

def main():
    h = HamiltonPrep()
    state = h.preflight(initialized=True)
    if state['serial'] != SERIAL:
        raise RuntimeError('Unexpected REST identity')
    report = {'time_utc': datetime.now(timezone.utc).isoformat(),
              'motion_sent': False, 'rest_state': state,
              'purpose': 'Inspect native transfer feasibility; never execute movement'}
    path = ROOT / 'reports/hamilton_api' / ('transfer_inspection_' +
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    # Prove the journal is writable before opening any native connection.
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    try:
        asyncio.run(inspect(report))
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print('Report:', path, flush=True)

if __name__ == '__main__':
    main()
