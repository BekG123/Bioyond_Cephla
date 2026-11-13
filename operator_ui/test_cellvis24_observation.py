"""Offline commissioning checks; no network or robot commands."""
from copy import deepcopy
import unittest
from cellvis24_observation import summarize


class StationaryChecks(unittest.TestCase):
    def samples(self):
        base=dict(error_xy_mm=[.1,.2],corners_preview_px=[[100,100],[700,100],[700,500],[100,500]],target={'x':300,'y':-70,'rz':89.8})
        return [deepcopy(base) for _ in range(3)]

    def test_stable_measurements_do_not_authorize_motion(self):
        r=summarize(self.samples())
        self.assertTrue(r['stationary_checks_passed'])
        self.assertFalse(r['motion_authorized'])
        self.assertFalse(r['full_calibration_complete'])

    def test_each_independent_instability_is_rejected(self):
        for key in ('xy','target_xy','rim','yaw','nan'):
            with self.subTest(key=key):
                s=self.samples()
                if key=='xy':s[-1]['error_xy_mm'][0]+=.3
                if key=='target_xy':s[-1]['target']['x']+=.3
                if key=='rim':s[-1]['corners_preview_px'][0][0]+=1
                if key=='yaw':s[-1]['target']['rz']+=.3
                if key=='nan':s[-1]['error_xy_mm'][0]=float('nan')
                self.assertFalse(summarize(s)['stationary_checks_passed'])

    def test_three_bursts_required(self):
        with self.assertRaises(ValueError):summarize(self.samples()[:2])

    def test_yaw_wrap_is_not_a_jump(self):
        s=self.samples()
        for x,yaw in zip(s,[179.99,-179.99,180.]):x['target']['rz']=yaw
        self.assertTrue(summarize(s)['stationary_checks_passed'])


if __name__=='__main__':unittest.main()
