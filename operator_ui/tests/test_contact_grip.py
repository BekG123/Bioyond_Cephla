"""Synthetic signals only; never connects hardware or supplies live settings."""
import importlib.util
from pathlib import Path
import sys
import unittest

PATH=Path(__file__).resolve().parents[2]/'Pick and Hold/Grip/contact_grip.py'
SPEC=importlib.util.spec_from_file_location('contact_grip_candidate', PATH)
MODULE=importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name]=MODULE
SPEC.loader.exec_module(MODULE)


class Tests(unittest.TestCase):
    def make(self):
        return MODULE.ContactGrip([MODULE.Reference(x, 10, 5) for x in (3.8,3.9,4.,4.1)],
                                  source='synthetic test only', commissioned=True)

    def sample(self, sequence=1, e1=4.1, torque=10, **changes):
        s=dict(sequence=sequence,age_s=.01,e1_mm=e1,torque=torque,healthy=True,
               stationary=True,pose_unchanged=True,other_axes_unchanged=True,recovered=False)
        s.update(changes)
        return s

    def test_unreviewed_or_missing_reference_rejected(self):
        with self.assertRaises(ValueError):MODULE.ContactGrip([],source='')
        c=self.make()
        self.assertEqual(c.observe(self.sample(e1=20))['state'],'stopped')

    def test_one_proposal_per_fresh_acknowledgement(self):
        c=self.make();c.observe(self.sample())
        with self.assertRaises(ValueError):c.propose_increment()
        self.assertEqual(c.propose_increment(confirmed=True)['e1_mm'],4.)
        with self.assertRaises(ValueError):c.propose_increment(confirmed=True)
        c.observe(self.sample(2,4.))
        self.assertEqual(c.propose_increment(confirmed=True)['e1_mm'],3.9)

    def test_contact_stops_closing_on_first_sample_both_signs(self):
        for torque in (16,-2):
            c=self.make();c.observe(self.sample(torque=torque))
            with self.assertRaises(ValueError):c.propose_increment(confirmed=True)
            c.observe(self.sample(2,torque=torque))
            result=c.observe(self.sample(3,torque=torque))
            self.assertEqual(result['state'],'contact_candidate')
            self.assertFalse(result['grasp_verified'])

    def test_transient_contact_requires_inspection_no_resume(self):
        c=self.make();c.observe(self.sample(torque=16))
        self.assertEqual(c.observe(self.sample(2))['state'],'stopped')
        with self.assertRaises(ValueError):c.propose_increment(confirmed=True)

    def test_fault_stale_nan_changed_pose_and_recovery_stop(self):
        for changes in ({'healthy':False},{'age_s':1},{'torque':float('nan')},
                        {'pose_unchanged':False},{'other_axes_unchanged':False},
                        {'recovered':True},{'stationary':False}):
            c=self.make()
            self.assertEqual(c.observe(self.sample(**changes))['state'],'stopped')
        c=self.make();c.observe(self.sample())
        self.assertEqual(c.observe(self.sample())['state'],'stopped')

    def test_stall_does_not_mean_secure_grasp(self):
        c=self.make();c.observe(self.sample());c.propose_increment(confirmed=True)
        result=c.observe(self.sample(2,4.1,30))
        self.assertEqual(result['state'],'stopped')
        self.assertFalse(result['grasp_verified'])

    def test_floor_is_not_grip_success(self):
        c=self.make();result=c.observe(self.sample(e1=3.8))
        self.assertEqual(result['state'],'floor_reached')
        self.assertFalse(result['grasp_verified'])
        with self.assertRaises(ValueError):c.propose_increment(confirmed=True)

    def test_uncommanded_motion_or_missing_next_reference(self):
        c=self.make();c.observe(self.sample())
        self.assertEqual(c.observe(self.sample(2,3.9))['state'],'stopped')
        c=MODULE.ContactGrip([MODULE.Reference(4.1,10,5)],
                             source='synthetic only',commissioned=True)
        c.observe(self.sample())
        with self.assertRaises(ValueError):c.propose_increment(confirmed=True)


if __name__=='__main__':unittest.main()
