"""Read-only camera capture for plate-offset development; no robot commands."""
from datetime import datetime, timezone
import base64
import hashlib
import io
import json
from pathlib import Path
import zipfile
from PIL import Image
from hamilton_prep import HamiltonPrep

def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analyze', action='store_true', help='Also fit the 48-well offset and save annotated previews')
    args = parser.parse_args()
    h = HamiltonPrep()
    state = h.preflight(initialized=True)
    if state['serial'] != 'PRPGJ2494' or not state.get('parked'):
        raise RuntimeError('Expected PRPGJ2494 parked for unobstructed capture')
    folder = h.folder / ('plate_offset_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    folder.mkdir()
    manifest = dict(captured_at=datetime.now(timezone.utc).isoformat(), serial=state['serial'],
                    motion_sent=False, site=4, padding_mm=15, crop_plane_above_site_mm=20.19,
                    plane_height_basis='Falcon 48-well catalog geometry 166', files={}, state=state)
    paths = [('raw.png', 'camera/false'), ('deck.png', 'camera/true'),
             ('reference.png', 'camera/calibration-pattern')]
    paths += [(f'site4_{i}.png', 'camera/position/4/15/20.19') for i in range(3)]
    paths += [('site3.png', 'camera/position/3/15/20.19')]
    for name, endpoint in paths:
        data = h.call('GET', endpoint, binary=True)
        (folder/name).write_bytes(data)
        frame = Image.open(io.BytesIO(data)).convert('RGB')
        manifest['files'][name] = dict(endpoint=endpoint, sha256=hashlib.sha256(data).hexdigest(), size=frame.size)
        frame.thumbnail((1400, 1100))
        frame.save(folder/(Path(name).stem + '_preview.jpg'))
    data = h.call('GET', 'calibration/export', binary=True)
    if not data.startswith(b'PK'):
        metadata = json.loads(data)
        data = base64.b64decode(metadata.get('FileBytes', metadata.get('fileBytes', '')))
    (folder/'calibration_export.zip').write_bytes(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            if not name.lower().endswith('.json'): continue
            try: value = json.loads(archive.read(name))
            except (ValueError, UnicodeError): continue
            if isinstance(value, dict) and all(k in value for k in ('CameraCalibration','Rotation','Translation')):
                (folder/'deck-calibration.json').write_text(json.dumps(value), encoding='utf-8')
    manifest['scan'] = h.call('GET', 'deck/scan/3')
    (folder/'capture.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(folder, flush=True)
    if args.analyze:
        from hamilton_plate_offset import analyze_folder
        result = analyze_folder(folder)
        print(json.dumps({k:v for k,v in result.items() if k!='frames'}, indent=2), flush=True)

if __name__ == '__main__': main()
