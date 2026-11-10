"""Offline regression for the measured Nov 7 preparation shift."""
import json
from pathlib import Path
import sys
import unittest

UI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UI))
from researcher_home import queued_station_stages, settled_home_stages
from autonomy import TransferError
from straight_transfer import validate_home_transit


class PreparationSettleTests(unittest.TestCase):
    def setUp(self):
        self.start = dict(X=279.303, Y=26.358, Z=289.129, Rz=-3.88)
        self.settled = dict(X=279.331, Y=26.380, Z=289.121, Rz=-3.884)
        self.target = dict(X=289.97, Y=62.63, Z=248.02, Rz=-3.88)
        self.joints = dict(J1=250.530, J2=76.8708, J3=45.7698, J4=-126.5205)
        self.cfg = json.loads((UI / 'robot_params.json').read_text())
        self.env = dict(X=(200, 450), Y=(-250, 380), Z=(70, 400))
        self.reviewed = queued_station_stages(self.start, self.target, self.joints, self.cfg, self.env)

    def rebuild(self, settled=None, env=None):
        return settled_home_stages(self.start, settled or self.settled, self.target,
                                   self.joints, self.cfg, env or self.env, self.reviewed)

    def test_observed_shift_preserves_vertical_lift_and_final_home(self):
        with self.assertRaises(TransferError):
            validate_home_transit(self.settled, self.reviewed[0]['points'])
        stages = self.rebuild()
        validate_home_transit(self.settled, stages[0]['points'])
        self.assertAlmostEqual(stages[0]['points'][0]['X'], self.settled['X'], places=2)
        self.assertAlmostEqual(stages[0]['points'][0]['Y'], self.settled['Y'], places=2)
        self.assertEqual(stages[-1]['points'][-1], self.target)

    def test_large_shift_still_rejected(self):
        with self.assertRaises(TransferError):
            self.rebuild({**self.settled, 'X': self.start['X'] + .051})

    def test_workspace_still_checked(self):
        with self.assertRaises(TransferError):
            self.rebuild(env={**self.env, 'Z': (70, 299)})

    def test_nonfinite_shift_rejected(self):
        with self.assertRaises(TransferError):
            self.rebuild({**self.settled, 'X': float('nan')})


if __name__ == '__main__':
    unittest.main()
