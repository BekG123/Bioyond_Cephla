"""Offline rigid placement adaptation; no controller access."""
import math
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare_adapted_descent import adapt_endpoint, verify_parent
from autonomy import TransferError, wrap


class AdaptedDescentTests(unittest.TestCase):
    def setUp(self):
        self.raw=dict(x=297.837,y=-68.918,rz=86.1091,z_calibrated=70.1495,
                      config='Wide',converged=True)
        self.taught=dict(X=298.78,Y=-65.683,Z=70.461,Rz=85.671)

    def test_identical_placement_recovers_successful_endpoint(self):
        actual=adapt_endpoint(self.raw,self.taught,self.raw)
        for key in self.taught:
            self.assertAlmostEqual(actual[key],self.taught[key])

    def test_rotated_translated_placement_transforms_contact_geometry(self):
        current={**self.raw,'x':320.,'y':-70.,'rz':self.raw['rz']+90}
        actual=adapt_endpoint(self.raw,self.taught,current)
        self.assertAlmostEqual(actual['X'],320-3.235)
        self.assertAlmostEqual(actual['Y'],-70+.943)
        self.assertAlmostEqual(actual['Rz'],self.taught['Rz']+90)
        # Independent tool-center check with the real long-claw lever.
        def center(x,y,yaw):
            a=math.radians(yaw)
            return x+191.6*math.cos(a)-5.43*math.sin(a),y+191.6*math.sin(a)+5.43*math.cos(a)
        old_raw=center(self.raw['x'],self.raw['y'],self.raw['rz'])
        old_goal=center(self.taught['X'],self.taught['Y'],self.taught['Rz'])
        new_raw=center(current['x'],current['y'],current['rz'])
        new_goal=center(actual['X'],actual['Y'],actual['Rz'])
        self.assertAlmostEqual(new_goal[0]-new_raw[0],-(old_goal[1]-old_raw[1]))
        self.assertAlmostEqual(new_goal[1]-new_raw[1],old_goal[0]-old_raw[0])

    def test_preserves_height_and_does_not_accumulate(self):
        current={**self.raw,'x':318.5205,'y':-69.6465,'rz':92.3735,'z_calibrated':71.174}
        first=adapt_endpoint(self.raw,self.taught,current)
        self.assertEqual(first,adapt_endpoint(self.raw,self.taught,current))
        self.assertEqual(first['Z'],70.461)
        self.assertAlmostEqual(wrap(first['Rz']-current['rz']),-.4381)
        self.assertAlmostEqual(math.hypot(first['X']-current['x'],first['Y']-current['y']),math.hypot(.943,3.235))
        self.assertEqual(self.taught['X'],298.78)

    def test_wrap_crossing_preserves_small_correction(self):
        raw={**self.raw,'rz':179}
        taught={**self.taught,'Rz':179.5}
        actual=adapt_endpoint(raw,taught,{**raw,'rz':-179})
        self.assertAlmostEqual(actual['Rz'],-178.5)

    def test_rejects_bad_reference(self):
        for change in ({'converged':False},{'config':'Long'},{'x':float('nan')}):
            with self.subTest(change=change),self.assertRaises(TransferError):
                adapt_endpoint(self.raw,self.taught,{**self.raw,**change})

    def test_accepted_parent_provenance_and_tampering(self):
        baseline=b'original demonstration'
        recorded=dict(original_target=self.raw,endpoint=self.taught)
        current={**self.raw,'x':310}
        endpoint=adapt_endpoint(self.raw,self.taught,current)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            folder=root/'trial'
            folder.mkdir()
            trial=json.dumps(dict(status='completed_awaiting_visual_inspection',
                                  result=dict(ok=True))).encode()
            (folder/'trial.json').write_bytes(trial)
            evidence=dict(baseline_sha256=hashlib.sha256(baseline).hexdigest(),
                          original_target=self.raw,original_endpoint=self.taught,
                          current_target=current)
            (folder/'evidence.json').write_text(json.dumps(evidence))
            acceptance=json.dumps(dict(visually_accepted=True,controller_descent_verified=True,
                endpoint=endpoint,trial='trial/trial.json',
                trial_sha256=hashlib.sha256(trial).hexdigest())).encode()
            (folder/'acceptance.json').write_bytes(acceptance)
            profile=dict(endpoint=endpoint,evidence='trial/acceptance.json',
                         evidence_sha256=hashlib.sha256(acceptance).hexdigest())
            with patch('prepare_adapted_descent.ROOT',root):
                verify_parent(profile,recorded,baseline)
                with self.assertRaises(TransferError):
                    verify_parent(profile,recorded,b'changed demonstration')
                (folder/'trial.json').write_bytes(b'{}')
                with self.assertRaises(TransferError):
                    verify_parent(profile,recorded,baseline)


if __name__=='__main__':unittest.main()
