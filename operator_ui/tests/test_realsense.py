"""Offline data/API/Viser integration tests. No physical camera or robot calls."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from realsense_processing import select_cloud, ply_bytes, depth_preview
from realsense_service import register_realsense
from realsense_worker import DepthView, make_app


class ProcessingTests(unittest.TestCase):
    def test_invalid_depth_and_texture_do_not_make_false_points(self):
        vertices = [[0,0,.1],[0,0,0],[0,0,float('nan')],[0,0,2],[0,0,.2]]
        uv = [[0,0],[0,0],[0,0],[0,0],[float('nan'),0]]
        rgb = np.array([[[10,20,30]]],dtype=np.uint8)
        points, colors = select_cloud(vertices,uv,rgb,stride=1)
        self.assertEqual(points.shape,(2,3))
        np.testing.assert_array_equal(colors,[[10,20,30],[160,160,160]])
        np.testing.assert_allclose(points[:,2],[.1,.2])

    def test_export_coordinates_remain_meters(self):
        blob = ply_bytes([[.01,.02,.30]],[[1,2,3]])
        header, body = blob.split(b'end_header\n',1)
        self.assertIn(b'units meters',header)
        np.testing.assert_allclose(np.frombuffer(body[:12],dtype='<f4'),[.01,.02,.30])
        self.assertEqual(body[12:],bytes([1,2,3]))

    def test_invalid_depth_preview_is_black(self):
        image = depth_preview(np.array([[0.,float('nan'),.2]]))
        np.testing.assert_array_equal(image[0,:2],0)
        self.assertTrue(image[0,2].any())


class WorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.view = DepthView(8097,cls.folder.name)
        cls.client = make_app(cls.view).test_client()

    @classmethod
    def tearDownClass(cls):
        cls.view.stop(); cls.view.server.stop(); cls.folder.cleanup()

    def tearDown(self): self.view.stop()

    def wait_for(self, predicate):
        deadline = time.monotonic()+4
        while time.monotonic()<deadline:
            if predicate(): return
            time.sleep(.05)
        self.fail('Capture state did not arrive')

    def test_demo_stream_mjviser_snapshot_and_full_cloud(self):
        self.assertEqual(self.client.post('/start',json={'mode':'demo'}).status_code,200)
        self.wait_for(lambda:self.view.status()['streaming'])
        s = self.client.get('/status').get_json()
        self.assertEqual(s['state'],'demo')
        self.assertEqual(s['center_depth_mm'],240.)
        self.assertEqual(s['robot_registration'],'not calibrated')
        self.assertIsNotNone(self.view.mjscene)
        self.assertLess(s['points'],320*240)
        response = self.client.get('/image/depth')
        self.assertEqual(response.mimetype,'image/jpeg')
        capture = self.client.post('/snapshot',json={}).get_json()
        self.assertEqual(capture['source'],'synthetic')
        folder = Path(capture['path'])
        depth = np.load(folder/'depth_m.npy')
        self.assertEqual(depth.shape,(240,320))
        self.assertAlmostEqual(float(depth[120,160]),.24,places=6)
        self.assertEqual(json.loads((folder/'metadata.json').read_text())['source'],'synthetic')
        self.assertIn(b'element vertex 76800',self.client.get('/cloud.ply').data)
        self.client.post('/stop',json={})
        self.assertFalse(self.view.cloud.visible)
        self.assertEqual(self.client.get('/image/color').status_code,409)

    def test_missing_d405_waits_and_releases_without_stale_data(self):
        class EmptyContext:
            def query_devices(self): return []
        with patch('realsense_worker.rs.context',return_value=EmptyContext()):
            self.client.post('/start',json={'mode':'camera'})
            self.wait_for(lambda:self.view.status()['state']=='waiting')
            s = self.view.status()
            self.assertFalse(s['streaming'])
            self.assertIn('No D405',s['error'])
            self.assertEqual(self.client.post('/snapshot',json={}).status_code,409)
            self.client.post('/stop',json={})
        self.assertEqual(self.view.status()['state'],'idle')

    def test_reject_invalid_mode_and_stale_capture(self):
        self.assertEqual(self.client.post('/start',json={'mode':'unknown'}).status_code,400)
        self.client.post('/start',json={'mode':'demo'})
        self.wait_for(lambda:self.view.status()['streaming'])
        self.view.stop_event.set(); self.view.thread.join(2)
        with self.view.lock: self.view.frame['ts'] = time.time()-3
        self.assertFalse(self.view.status()['streaming'])
        self.assertEqual(self.client.get('/cloud.ply').status_code,409)


class AdapterTests(unittest.TestCase):
    def test_routes_proxy_only_depth_actions(self):
        class Fake:
            def status(self): return dict(ok=True,state='idle')
            def launch(self): return self.status()
            def request(self,path,body=None,timeout=5):
                return json.dumps(dict(ok=True,path=path)).encode(),'application/json',200
        app = Flask(__name__); register_realsense(app,Fake()); client = app.test_client()
        self.assertEqual(client.post('/realsense/start',json={}).get_json()['path'],'/start')
        self.assertEqual(client.post('/realsense/move',json={}).status_code,404)
        self.assertEqual(client.get('/realsense/start').status_code,404)
        self.assertEqual(client.get('/realsense/status').get_json()['state'],'idle')


if __name__ == '__main__': unittest.main()
