"""The taught endpoint does not expand the prior vision acceptance band."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from autonomy import TransferError
from pick_and_hold.Descend import correction


class AcceptedDescentTests(unittest.TestCase):
    def plan(self, depth, **kwargs):
        target=dict(config='Wide',x=312.575,y=-66.2,rz=89.865,z_calibrated=depth)
        start=dict(X=312.575,Y=-66.2,Z=300.,Rz=89.865)
        with patch.object(correction,'make_plan'), patch.object(correction,'alignment_plan',return_value=[]):
            return correction.corrected_plan(start,{},target,{}, {},66,**kwargs)

    def test_old_vision_band_and_new_taught_endpoint(self):
        plan=self.plan(69.5745)
        self.assertEqual(plan['endpoint']['Z'],73.718)
        self.assertEqual(plan['target']['z_calibrated'],73.718)

    def test_height_band_not_widened_to_fit_taught_endpoint(self):
        with self.assertRaisesRegex(TransferError,'outside the taught'):
            self.plan(73.718)

    def test_unreviewed_reference_height_rejected(self):
        profile=json.loads(correction.PROFILE.read_bytes())
        profile['vision_reference_z_mm']+=1
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'profile.json'
            file.write_text(json.dumps(profile))
            with self.assertRaisesRegex(TransferError,'reviewed evidence'):
                self.plan(70.461,profile_path=file)


if __name__=='__main__':
    unittest.main()
