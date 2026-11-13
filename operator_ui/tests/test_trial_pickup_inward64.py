"""Offline geometry checks; never contacts hardware."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from trial_pickup_inward64 import shifted_endpoint, positive_y_endpoint


class InwardCorrectionTests(unittest.TestCase):
    def test_additional_two_mm_uses_original_reference(self):
        source=dict(X=312.0124178577057,Y=-75.87790542678249,Z=73.718,Rz=89.7652192188176)
        previous=positive_y_endpoint(source)
        goal=positive_y_endpoint(source,8.4)
        self.assertAlmostEqual(goal['Y']-previous['Y'],2.)
        self.assertAlmostEqual(goal['Y'],-67.47790542678249)
        self.assertEqual(goal['X'],source['X'])
        with self.assertRaises(ValueError):positive_y_endpoint(source,14.8)

    def test_positive_y_changes_only_y_from_absolute_baseline(self):
        source=dict(X=312.0124178577057,Y=-75.87790542678249,Z=73.718,Rz=89.7652192188176)
        goal=positive_y_endpoint(source)
        self.assertAlmostEqual(goal['Y'],-69.47790542678249)
        self.assertEqual({k:v for k,v in source.items() if k!='Y'}, {k:v for k,v in goal.items() if k!='Y'})
        self.assertEqual(positive_y_endpoint(source),goal)
        self.assertEqual(source['Y'],-75.87790542678249)

    def test_fixed_distance_toward_base_preserves_height_yaw_and_source(self):
        source=dict(X=312.0124178577057,Y=-75.87790542678249,Z=73.718,Rz=89.7652192188176)
        before=dict(source)
        cfg=dict(base_x_mm=126.,base_y_mm=0.)
        goal=shifted_endpoint(source,cfg)
        self.assertEqual(source,before)
        self.assertAlmostEqual(math.hypot(goal['X']-source['X'],goal['Y']-source['Y']),6.4)
        old_radius=math.hypot(source['X']-126,source['Y'])
        self.assertAlmostEqual(old_radius-math.hypot(goal['X']-126,goal['Y']),6.4)
        self.assertEqual((goal['Z'],goal['Rz']),(source['Z'],source['Rz']))

    def test_invalid_direction_refused(self):
        for x in (126.,float('nan')):
            with self.assertRaises(ValueError):
                shifted_endpoint(dict(X=x,Y=0.,Z=73.718,Rz=90.),dict(base_x_mm=126.,base_y_mm=0.))


if __name__=='__main__':unittest.main()
