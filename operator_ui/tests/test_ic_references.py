"""Reference persistence/ownership regressions, using fake camera and pose only."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import cv2
from test_ic import fixture
from pick_and_hold.Align.ic import ICError, similarity
from pick_and_hold.Align.references import ICReferences, disk_initial
from sequences import Runner

MODULE='pick_and_hold.Align.references'


class FakeCamera:
    def __init__(self):
        self.frame=fixture()
        self.calls=0
        self.serial='offline-camera'
    def snap(self):
        self.calls+=1
        return self.frame.copy()
    def info(self):
        return dict(device=dict(serial=self.serial,model='synthetic'))


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=ICReferences(Path(self.temp.name)/'references')
        self.camera=FakeCamera()
        self.run=Runner()
        self.run.state='running'
        self.pose=dict(X=300.,Y=0.,Z=300.,Rz=0.)
        self.options=self.store.options(dict(label='Offline test only',count=3,roi=[120,110,390,260],
            aligned_confirmed=True,plate_only_roi=True))
        self.detector=patch(MODULE+'.circles',return_value=None)
        self.detector.start()
        self.addCleanup(self.detector.stop)

    def capture(self):
        return self.store.capture(self.run,self.camera,lambda:dict(self.pose),self.options)

    def test_batch_persists_raw_images_pose_and_reference(self):
        result=self.capture()
        self.assertTrue(result['ok'],result)
        folder=self.store.folder(result['id'])
        meta=json.loads((folder/'manifest.json').read_text())
        self.assertEqual(meta['status'],'ready')
        self.assertEqual(len(meta['frames']),3)
        self.assertEqual(meta['pose_mm'],self.pose)
        self.assertFalse(meta['motion_commanded'])
        self.assertTrue(all((folder/f['image']).is_file() for f in meta['frames']))
        restarted=ICReferences(self.store.root)
        self.assertEqual(restarted.active_id(),result['id'])
        self.assertEqual(len(restarted.public()['references']),1)
        self.assertTrue(restarted.load()[1].align(fixture())['ok'])

    def test_preview_known_offset_preserves_robot_target(self):
        self.assertTrue(self.capture()['ok'])
        m=similarity(4,-3,1.,1.01,(315,240))
        self.camera.frame=cv2.warpAffine(fixture(),m[:2],(640,480),borderValue=175)
        self.run.target={'existing_vendor_target':True}
        r=self.store.preview(self.run,self.camera,lambda:dict(self.pose))
        self.assertTrue(r['ok'],r)
        self.assertAlmostEqual(r['shift_x_px'],4,delta=.3)
        self.assertFalse(r['motion_commanded'])
        self.assertFalse(r['robot_alignment_verified'])
        self.assertEqual(self.run.target,{'existing_vendor_target':True})
        self.assertTrue(self.store.preview_path.is_file())

    def test_motion_during_batch_rejected_without_changing_active(self):
        good=self.capture()['id']
        snap=self.camera.snap
        def moving():
            self.pose['X']+=.2
            return snap()
        self.camera.snap=moving
        r=self.capture()
        self.assertFalse(r['ok'])
        self.assertIn('Arm moved',r['error'])
        self.assertEqual(self.store.active_id(),good)
        self.assertEqual(len(self.store.public()['references']),1)

    def test_plate_motion_despite_stationary_arm_rejects_batch(self):
        snap=self.camera.snap
        def moving_plate():
            a=snap()
            if self.camera.calls>1:
                a=cv2.warpAffine(a,similarity(3,0)[:2],(640,480),borderValue=175)
            return a
        self.camera.snap=moving_plate
        r=self.capture()
        self.assertFalse(r['ok'],r)
        self.assertIsNone(self.store.active_id())

    def test_cancel_does_not_activate_partial_reference(self):
        snap=self.camera.snap
        def cancelling():
            a=snap()
            self.run.request_stop()
            return a
        self.camera.snap=cancelling
        r=self.capture()
        self.assertFalse(r['ok'])
        self.assertEqual(self.run.state,'stopped')
        self.assertIsNone(self.store.active_id())

    def test_bad_options_and_path_traversal_rejected(self):
        for update in [dict(count=True),dict(count=31),dict(aligned_confirmed=False),
                       dict(roi=[0,0,63,200]),dict(roi=[0,0,200.2,200])]:
            body=dict(count=3,aligned_confirmed=True,plate_only_roi=True)
            body.update(update)
            with self.assertRaises(ICError): self.store.options(body)
        for identifier in ['../escape','C:/escape','',None]:
            with self.assertRaises(ICError): self.store.folder(identifier)

    def test_reference_hash_or_calibration_change_rejected(self):
        result=self.capture()
        with patch(MODULE+'.setup_signature',return_value={'different':'calibration'}):
            with self.assertRaisesRegex(ICError,'calibration changed'): self.store.load()
        path=self.store.folder(result['id'])/'reference.png'
        path.write_bytes(path.read_bytes()+b'changed')
        with self.assertRaisesRegex(ICError,'hash mismatch'): self.store.load()

    def test_camera_identity_change_rejected(self):
        self.assertTrue(self.capture()['ok'])
        self.camera.serial='other-camera'
        r=self.store.preview(self.run,self.camera,lambda:dict(self.pose))
        self.assertFalse(r['ok'])
        self.assertIn('identity',r['error'])

    def test_dark_preview_is_rejected(self):
        self.assertTrue(self.capture()['ok'])
        self.camera.frame[:]=3
        r=self.store.preview(self.run,self.camera,lambda:dict(self.pose))
        self.assertFalse(r['ok'])
        self.assertIsNone(self.store.preview_path)

    def test_disk_initial_direction(self):
        a=dict(mark=[100,100,0],big_c=[50,100],small_c=[150,100])
        b=dict(mark=[110,90,90],big_c=[110,40],small_c=[110,140])
        warp=disk_initial(a,b)
        self.assertAlmostEqual((warp@[100,100,1])[0],110)
        self.assertAlmostEqual((warp@[50,100,1])[1],40)

    def test_flask_routes_validate_before_start_and_respect_ownership(self):
        import app as console
        with patch.object(console,'ic_references',self.store), patch.object(console.runner,'start',return_value={'ok':True}) as start:
            client=console.app.test_client()
            self.assertEqual(client.get('/ic/state').status_code,200)
            self.assertEqual(client.post('/ic/reference/capture',json={}).status_code,400)
            self.assertEqual(client.post('/ic/preview',json={}).status_code,400)
            start.assert_not_called()
            body=dict(count=3,roi=self.options['roi'],aligned_confirmed=True,plate_only_roi=True)
            with patch.object(console.svc,'status',return_value={'connected':True}):
                self.assertEqual(client.post('/ic/reference/capture',json=body).status_code,200)
            self.assertEqual(start.call_args.args[0],'ic_reference')
            self.assertEqual(start.call_args.args[3],console.svc.pose_mm)
            with patch.object(console.runner,'_thread',SimpleNamespace(is_alive=lambda:True)):
                self.assertEqual(client.post('/ic/preview',json={}).status_code,409)
            self.assertEqual(client.get('/ic/image?id=../escape').status_code,404)


if __name__=='__main__': unittest.main()
