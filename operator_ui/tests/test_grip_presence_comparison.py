"""Offline reference-label checks; no robot imports."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compare_grip_presence import compare


class Tests(unittest.TestCase):
    def test_corrected_plate_record_cannot_be_an_empty_reference(self):
        common = dict(ok=True, finished_utc='recorded', speed=5, targets_mm=[3.8],
            sampling_mode='test', start_pose_mm=dict(X=300, Y=0, Z=70, Rz=90),
            positions=[dict(target_mm=3.8, samples=[dict(raw_torque=10)])])
        plate = dict(common, kind='plate_present_closing_measurement', plate_present=True,
                     eligible_as_empty_reference=False)
        empty = dict(deepcopy(common), kind='empty_claw_baseline', operator_confirmed_empty=True)
        empty['positions'][0]['samples'][0]['raw_torque'] = 2
        with tempfile.TemporaryDirectory() as directory:
            p, e = Path(directory)/'plate.json', Path(directory)/'empty.json'
            p.write_text(json.dumps(plate))
            e.write_text(json.dumps(empty))
            self.assertEqual(compare(p, e)['comparisons'][0]['plate_minus_empty'], 8)
            with self.assertRaisesRegex(ValueError, 'mislabeled or excluded'):
                compare(p, p)
            empty['eligible_as_empty_reference'] = False
            e.write_text(json.dumps(empty))
            with self.assertRaisesRegex(ValueError, 'mislabeled or excluded'):
                compare(p, e)
            empty.pop('eligible_as_empty_reference')
            empty['start_pose_mm']['Z'] += 1
            e.write_text(json.dumps(empty))
            with self.assertRaisesRegex(ValueError, 'Different arm poses'):
                compare(p, e)


if __name__ == '__main__':
    unittest.main()
