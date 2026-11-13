"""Read-only vendor evidence export. Never sends a hardware command."""
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from urllib.request import build_opener, ProxyHandler
import xml.etree.ElementTree as ET
import zipfile

from hamilton_prep import HamiltonPrep

def main():
    h = HamiltonPrep()
    state = h.preflight(initialized=True)
    if state['serial'] != 'PRPGJ2494':
        raise RuntimeError('Unexpected Hamilton identity')
    folder = h.folder / ('native_transfer_evidence_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    folder.mkdir()
    opener = build_opener(ProxyHandler({}))
    base = h.settings()['base_url'].rstrip('/') + '/'
    def get(path):
        with opener.open(base + path, timeout=60) as response:
            return response.read()
    raw = get('labware/export/226')
    (folder / 'falcon226_export.zip').write_bytes(raw)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        nested = archive.read('P96w370fn1rjFAL.hamLabware')
    with zipfile.ZipFile(io.BytesIO(nested)) as archive:
        document = json.loads(archive.read('P96w370fn1rjFAL-v1.json'))
    outer = ET.fromstring(document['Content']['Data'])
    xml = outer.find('SerializedLabware').text
    (folder / 'falcon226_labware.xml').write_text(xml, encoding='utf-8')
    root = ET.fromstring(xml)
    ns = {'l': 'Hamilton.XRP2.Labware'}
    report = {'motion_sent': False, 'serial': state['serial'], 'labware_id': 226,
              'document': document['Document']['ViewName'], 'state': state}
    for name in ('LabeledPoints', 'StackedSegments', 'TransportInfo'):
        report[name] = ET.tostring(root.find('l:' + name, ns), encoding='unicode')
    raw = get('diagnostics')
    (folder / 'hamilton_diagnostics.zip').write_bytes(raw)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        report['diagnostic_members'] = archive.namelist()
    traces = json.loads(get('traces?offset=0&limit=1000&sources=MNE'))
    selected = []
    for row in traces.get('items', []):
        if not ('2026-11-08T10:31:37' <= row['date'] <= '2026-11-08T10:31:48'):
            continue
        try:
            message = json.loads(row['message'])
        except (ValueError, TypeError):
            continue
        if isinstance(message, list) and message and message[0] in ('PickUpDCG', 'PickUpPlate', 'DropPlate', 'DropTool'):
            selected.append(dict(date=row['date'], simulation=True, message=message))
    (folder / 'simulation_gripper_commands.json').write_text(json.dumps(selected, indent=2), encoding='utf-8')
    report['simulation_gripper_commands_saved'] = len(selected)
    (folder / 'evidence.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Evidence folder:', folder)
    print('Diagnostic members:', json.dumps(report['diagnostic_members']))

if __name__ == '__main__':
    main()
