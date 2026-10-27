"""Offline matched-pose comparison. Does not commission a force/contact limit."""
import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean


def compare(plate_path, empty_path):
    plate_raw, empty_raw = Path(plate_path).read_bytes(), Path(empty_path).read_bytes()
    plate, empty = json.loads(plate_raw), json.loads(empty_raw)
    if (plate.get('kind') != 'plate_present_closing_measurement'
            or plate.get('plate_present') is not True
            or plate.get('eligible_as_empty_reference') is not False):
        raise ValueError('Require the explicitly corrected plate-present record.')
    if (empty.get('kind') != 'empty_claw_baseline'
            or empty.get('operator_confirmed_empty') is not True
            or empty.get('plate_present') is True
            or empty.get('eligible_as_empty_reference') is False):
        raise ValueError('Empty reference is mislabeled or excluded.')
    for record in (plate, empty):
        if record.get('ok') is not True or not record.get('finished_utc'):
            raise ValueError('Both recordings must be completed successfully.')
    for key in ('X', 'Y', 'Z', 'Rz'):
        delta = plate['start_pose_mm'][key] - empty['start_pose_mm'][key]
        if key == 'Rz':
            delta = (delta + 180) % 360 - 180
        if abs(delta) > .05:
            raise ValueError('Different arm poses; no matched comparison.')
    for key in ('speed', 'targets_mm', 'sampling_mode'):
        if plate[key] != empty[key]:
            raise ValueError('Different measurement protocol: ' + key)
    reference = {p['target_mm']: p for p in empty['positions']}
    rows = []
    for position in plate['positions']:
        target = position['target_mm']
        loaded = [p['raw_torque'] for p in position['samples']]
        unloaded = [p['raw_torque'] for p in reference[target]['samples']]
        rows.append(dict(e1_mm=target, plate_mean=mean(loaded), empty_mean=mean(unloaded),
            plate_minus_empty=mean(loaded)-mean(unloaded),
            plate_range=[min(loaded), max(loaded)], empty_range=[min(unloaded), max(unloaded)]))
    return dict(schema='cephla.grip-presence-comparison.v1',
        plate_record=str(plate_path), plate_sha256=hashlib.sha256(plate_raw).hexdigest(),
        empty_record=str(empty_path), empty_sha256=hashlib.sha256(empty_raw).hexdigest(),
        pose_mm=empty['start_pose_mm'], speed=empty['speed'], comparisons=rows,
        contact_threshold_commissioned=False, grasp_verified=False,
        limitations=['One plate-present and one empty run; order and friction can affect torque.',
                     'Raw torque readings are not calibrated gripping force.',
                     'No independent contact annotation or load-bearing test.',
                     'Sparse samples above 7 mm; do not extrapolate a contact threshold.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plate')
    parser.add_argument('empty')
    parser.add_argument('output')
    args = parser.parse_args()
    report = compare(args.plate, args.empty)
    with Path(args.output).open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    print(json.dumps(dict(output=args.output, positions=len(report['comparisons']),
        selected=[r for r in report['comparisons'] if r['e1_mm'] in (28., 7., 5., 4.2, 3.8)],
        contact_threshold_commissioned=False), indent=2))
