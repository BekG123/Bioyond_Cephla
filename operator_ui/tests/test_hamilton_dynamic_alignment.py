import unittest
import numpy as np
from hamilton_dynamic_alignment import AlignmentError, fit_registration, controller_points


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.a = np.array([[0,0,0],[100,0,0],[0,100,0],[0,0,50],[100,100,50]],float)
        self.check = np.array([[20,30,10],[80,70,35]],float)
        self.r = np.array([[0,-1,0],[1,0,0],[0,0,1]],float)
        self.t = np.array([200,10,4],float)
        self.kw = dict(serial='fixture',calibration_sha256='a'*64,evidence='synthetic test only')

    def fit(self, check=None):
        return fit_registration(self.a, self.a@self.r.T+self.t, self.check,
            self.check@self.r.T+self.t if check is None else check, **self.kw)

    def test_rotated_translated_frame_and_independent_point(self):
        registration = self.fit()
        registration['physical_validation_complete'] = True
        target = np.array([[35,40,25]],float)
        actual = controller_points(target,registration,serial='fixture',calibration_sha256='a'*64)
        np.testing.assert_allclose(actual,target@self.r.T+self.t,atol=1e-9)

    def test_unvalidated_fit_cannot_supply_targets(self):
        with self.assertRaisesRegex(AlignmentError,'physical validation'):
            controller_points([[1,2,3]],self.fit(),serial='fixture',calibration_sha256='a'*64)

    def test_bad_holdout_is_rejected(self):
        with self.assertRaisesRegex(AlignmentError,'agreement'):
            self.fit(self.check@self.r.T+self.t+[1,0,0])

    def test_different_camera_calibration_is_rejected(self):
        with self.assertRaisesRegex(AlignmentError,'another instrument or camera'):
            controller_points([[1,2,3]],self.fit(),serial='fixture',calibration_sha256='b'*64)

    def test_reflection_cannot_hide_wrong_axis_sign(self):
        with self.assertRaisesRegex(AlignmentError,'handedness'):
            fit_registration(self.a,self.a*[-1,1,1],self.check,self.check*[-1,1,1],**self.kw)

    def test_planar_reference_cannot_verify_z(self):
        with self.assertRaisesRegex(AlignmentError,'span'):
            fit_registration(self.a*[1,1,0],self.a,self.check,self.check,**self.kw)


if __name__ == '__main__':
    unittest.main()
