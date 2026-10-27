"""Offline geometry/regression tests. No controller, server or camera access."""
import copy
import json
from pathlib import Path
import unittest
import cv2
import numpy as np
from demo import fixtures,render
from vision import analyze,detect_features,estimate_pose,model_points,DetectionError
from alignment_preview import preview
from reference_mapping import map_reference


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.model,self.camera=fixtures()
        self.image,self.truth=render(self.model,self.camera)

    def test_pose_recovers_independent_render_truth(self):
        for angles,noise in [((14,-18,8),0),((19,12,155),2),((-22,20,-24),3)]:
            with self.subTest(angles=angles):
                image,truth=render(self.model,self.camera,angles,noise=noise)
                result,_=analyze(image,self.model,self.camera)
                transform=np.array(result['pose']['T_camera_plate'])
                angle=np.degrees(np.arccos(np.clip((np.trace(transform[:3,:3].T@truth[:3,:3])-1)/2,-1,1)))
                self.assertLess(np.linalg.norm(transform[:3,3]-truth[:3,3]),.3)
                self.assertLess(angle,.2)
                self.assertEqual(result['pose']['matched_wells'],96)
                self.assertLess(result['pose']['reprojection_rmse_px'],.2)
                self.assertFalse(result['motion_authorized'])

    def test_blank_is_not_plate(self):
        with self.assertRaises(DetectionError): analyze(np.zeros_like(self.image),self.model,self.camera)

    def test_symmetric_plate_without_orientation_is_rejected(self):
        image,_=render(self.model,self.camera,chamfer=False)
        with self.assertRaises(DetectionError): analyze(image,self.model,self.camera)

    def test_missing_grid_is_rejected(self):
        image,_=render(self.model,self.camera,missing=25)
        with self.assertRaises(DetectionError): analyze(image,self.model,self.camera)

    def test_resolution_mismatch_rejected(self):
        with self.assertRaises(DetectionError): analyze(self.image[::2,::2],self.model,self.camera)

    def test_invalid_intrinsics_rejected(self):
        self.camera['K'][0][0]=float('nan')
        with self.assertRaises(DetectionError): analyze(self.image,self.model,self.camera)

    def test_grid_outlier_rejected(self):
        features=detect_features(self.image,self.model)
        features['well_px'][40]+=[15.,-20.]
        with self.assertRaises(DetectionError): estimate_pose(features,self.model,np.array(self.camera['K']))

    def test_virtual_circles_cannot_change_pose(self):
        original,_=analyze(self.image,self.model,self.camera)
        self.model['virtual_circles'][0]['center_mm']=[30.,20.]
        self.model['virtual_circles'][0]['radius_mm']=3.
        changed,_=analyze(self.image,self.model,self.camera)
        self.assertEqual(original['pose'],changed['pose'])
        self.assertNotEqual(original['virtual_circles'],changed['virtual_circles'])

    def test_reference_circle_mapping_recovers_geometry_under_perspective(self):
        rim,_=model_points(self.model)
        rvec,_=cv2.Rodrigues(self.truth[:3,:3]);k=np.array(self.camera['K'])
        def project(p): return cv2.projectPoints(np.asarray(p,float),rvec,self.truth[:3,3],k,None)[0].reshape(-1,2)
        outlines={}
        for c in self.model['virtual_circles']:
            a=np.linspace(0,2*np.pi,50,endpoint=False)
            outlines[c['label']]=project(np.column_stack([c['center_mm'][0]+c['radius_mm']*np.cos(a),c['center_mm'][1]+c['radius_mm']*np.sin(a),np.zeros(len(a))]))
        mapped=map_reference(project(rim),rim[:,:2],outlines)
        for found,expected in zip(mapped['virtual_circles'],self.model['virtual_circles']):
            np.testing.assert_allclose(found['center_mm'],expected['center_mm'],atol=.001)
            self.assertAlmostEqual(found['radius_mm'],expected['radius_mm'],places=3)

    def test_template_orientation_branch(self):
        # A unique molded-label-like texture replaces the synthetic chamfer cue.
        model=copy.deepcopy(self.model)
        model['orientation']=dict(kind='template',rectangle_mm=[20.,1.,25.,7.])
        image,truth=render(model,self.camera,chamfer=False)
        texture=np.full((35,125),210,np.uint8)
        cv2.putText(texture,'A1',(2,29),cv2.FONT_HERSHEY_SIMPLEX,1.,30,2)
        plane=np.array([[20,1,0],[45,1,0],[45,8,0],[20,8,0]],float)
        rvec,_=cv2.Rodrigues(truth[:3,:3])
        pixels=cv2.projectPoints(plane,rvec,truth[:3,3],np.array(self.camera['K']),None)[0].reshape(-1,2)
        h=cv2.getPerspectiveTransform(np.array([[0,0],[125,0],[125,35],[0,35]],np.float32),pixels.astype(np.float32))
        warped=cv2.warpPerspective(texture,h,(image.shape[1],image.shape[0]))
        mask=cv2.warpPerspective(np.full_like(texture,255),h,(image.shape[1],image.shape[0]))
        image[mask>250]=warped[mask>250]
        result,_=analyze(image,model,self.camera,texture)
        self.assertEqual(result['pose']['matched_wells'],96)
        with self.assertRaises(DetectionError): analyze(image,model,self.camera,np.full_like(texture,210))

    def context(self):
        # Deliberately manufactured camera/base extrinsic; never a real calibration.
        repo=Path(__file__).resolve().parents[3]
        base_plate=np.eye(4);base_plate[:3,3]=[260.,-80.,75.]
        plate_tcp=np.eye(4);plate_tcp[:3,3]=[40.,40.,0.]
        return dict(synthetic=True,model_id=self.model['id'],calibration_id=self.camera['calibration_id'],
            reference_id='synthetic_grasp_only',T_base_camera=(base_plate@np.linalg.inv(self.truth)).tolist(),T_plate_tcp=plate_tcp.tolist(),
            start_pose=dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88),
            start_joints=dict(J2=84.87686,J3=52.05595,J4=-140.81283),
            robot_params=json.loads((repo/'operator_ui/robot_params.json').read_text()),
            envelope=dict(X=[200,450],Y=[-250,380],Z=[70,400]),hover_z=300.)

    def test_existing_alignment_planner_produces_preview(self):
        result,_=analyze(self.image,self.model,self.camera)
        plan=preview(result,self.context())
        self.assertFalse(plan['motion_authorized'])
        self.assertTrue(plan['alignment_waypoints'])
        self.assertAlmostEqual(plan['alignment_waypoints'][-1]['Z'],300.)
        self.assertAlmostEqual(plan['target_preview']['x'],300.,delta=.2)
        self.assertAlmostEqual(plan['target_preview']['y'],-40.,delta=.2)

    def test_alignment_binding_mismatch_rejected(self):
        result,_=analyze(self.image,self.model,self.camera)
        context=self.context();context['calibration_id']='another_camera'
        with self.assertRaises(DetectionError): preview(result,context)

    def test_alignment_tilt_rejected(self):
        result,_=analyze(self.image,self.model,self.camera)
        context=self.context();context['T_base_camera']=np.eye(4).tolist()
        with self.assertRaises(DetectionError): preview(result,context)

    def test_alignment_workspace_still_checked(self):
        result,_=analyze(self.image,self.model,self.camera)
        context=self.context();context['envelope']['Y']=[0,100]
        with self.assertRaisesRegex(Exception,'envelope'): preview(result,context)

    def test_existing_two_disk_photo_not_misclassified_as_grid(self):
        repo=Path(__file__).resolve().parents[3]
        image=repo/'operator_ui/datasets/depth/plate_xy_20260918_v2/20260919T000613_8ecf3204aa/rgb.png'
        if not image.is_file(): self.skipTest('Optional archived image absent')
        # Feature rejection only. No fabricated metric calibration for this photo.
        gray=cv2.imread(str(image),cv2.IMREAD_GRAYSCALE)
        with self.assertRaises(DetectionError): detect_features(gray,self.model)


if __name__=='__main__': unittest.main(verbosity=2)
