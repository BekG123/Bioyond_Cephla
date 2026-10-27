"""Height pilot tests with simulated observations; no hardware access."""
import sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import projected_height_trial as h

class HeightTests(unittest.TestCase):
    def test_height_measurement_cannot_publish_original_disk_mapping(self):
        p=h.HeightPerception()
        image_path=h.ROOT/'operator_ui/reports/projected_disk_pilot/grid_pattern_after_move_20261026/fresh_1.jpg'
        image=h.cv2.imread(str(image_path));pose=dict(X=281.451,Y=44.565,Z=268.02,Rz=-3.88)
        result=p.measure(image,pose)
        self.assertNotIn('error_xy_mm',result)
        self.assertNotIn('virtual_circles',result['tracking'])
        self.assertFalse(result['tracking']['original_disk_mapping_validated'])
        self.assertFalse(result['depth_estimated'])
        with self.assertRaises(h.DetectionError):p.measure(np.full_like(image,128),pose)

    def test_stationary_corner_disagreement_blocks_height_trial(self):
        pose=dict(X=280.,Y=29.,Z=268.008,Rz=-3.889)
        guard=Mock();guard.pose_mm.return_value=pose
        corners=np.array([[0,0],[100,0],[100,70],[0,70]],float)
        observations=[(pose,dict(tracking=dict(corners_px=c.tolist()))) for c in (corners,corners+2)]
        with patch.object(h,'observe',side_effect=observations):
            with self.assertRaisesRegex(h.TransferError,'corners disagree'):
                h.stationary_observation(guard,Mock(),Mock(),Mock())
        guard.move_cartesian.assert_not_called()

    def test_requires_same_support_and_live_supervision(self):
        body=dict(confirm=True,cell_clear=True,empty_gripper=True,same_support=True,
                  expected_start=dict(X=280.,Y=29.,Z=268.008,Rz=-3.889),reference_target_z=289.129)
        for key in ('confirm','cell_clear','empty_gripper','same_support'):
            with self.assertRaises(h.TransferError):h.validate_request(dict(body,**{key:False}))
        self.assertEqual(h.validate_request(body)['reference_target_z'],289.129)

    def test_only_bounded_upward_steps(self):
        for z,expected in ((268.008,270.008),(288.5,289.129)):
            p=dict(X=280.,Y=29.,Z=z,Rz=-3.889)
            target=h.next_target(p,289.129)
            self.assertAlmostEqual(target['Z'],expected)
            self.assertEqual([target[k] for k in ('X','Y','Rz')],[p[k] for k in ('X','Y','Rz')])
        for z in (260.,291.):
            with self.assertRaises(h.TransferError):h.next_target(dict(Z=z),289.129)

    def exercise(self,fail_before=False,wrong_scale=False,drift=False,at_goal=False):
        start=dict(X=280.,Y=29.,Z=289.129 if at_goal else 268.008,Rz=-3.889)
        pose=dict(start);run=SimpleNamespace(target={},state='running',stopped=lambda:False,say=Mock())
        guard=Mock();guard.pose_mm.side_effect=lambda:dict(pose)
        guard.path_envelope={};guard.torque_report.return_value=dict(e1_position=.022,e1_torque=-1)
        def move(x,y,z,rz,*args):pose.update(X=x+(1 if drift else 0),Y=y,Z=z,Rz=rz)
        guard.move_cartesian.side_effect=move
        cam=Mock();cam.snap.return_value=np.zeros((20,30,3),np.uint8)
        p=Mock();p.burst_frames=1
        def measure(frame,position):
            if fail_before:raise h.TransferError('lost image')
            ratio=1+(position['Z']-start['Z'])/184.
            factor=ratio if wrong_scale else 1/ratio
            corners=np.array([[0,0],[100,0],[100,70],[0,70]])*factor
            return dict(error_xy_mm=[.28,-.056],tracking=dict(corners_px=corners.tolist()))
        p.measure.side_effect=measure
        with tempfile.TemporaryDirectory() as folder,patch.object(h,'ROOT',Path(folder)),patch.object(h,'reference',return_value=dict(target_z=289.129)),patch.object(h,'GuardedService',return_value=guard),patch.object(h,'check_path'):
            result=h.pilot(run,Mock(),cam,{},dict(expected_start=start,reference_target_z=289.129),p)
        self.assertIsNone(run.target)
        self.assertFalse(result['calibration_complete'])
        self.assertFalse(result['grasp_target_created'])
        self.assertEqual(guard.move_cartesian.call_count,0 if fail_before or at_goal else 1)
        guard.move_gripper.assert_not_called()
        return result

    def test_known_upward_move_and_shrinking_image_pass(self):
        r=self.exercise();self.assertTrue(r['ok'])
        self.assertAlmostEqual(r['scale_response']['approximate_axial_distance_before_mm'],184.)
        self.assertFalse(r['absolute_depth_verified'])
    def test_lost_vision_blocks_motion(self):self.assertFalse(self.exercise(fail_before=True)['motion_requested'])
    def test_wrong_scale_stops_after_one_move(self):self.assertFalse(self.exercise(wrong_scale=True)['ok'])
    def test_unexpected_lateral_motion_stops(self):self.assertFalse(self.exercise(drift=True)['ok'])
    def test_arrived_height_gets_stationary_checks_only(self):
        r=self.exercise(at_goal=True);self.assertTrue(r['height_reference_reached']);self.assertFalse(r['motion_requested'])

if __name__=='__main__':unittest.main(verbosity=2)
