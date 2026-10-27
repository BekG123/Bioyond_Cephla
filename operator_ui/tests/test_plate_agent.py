"""Camera-only pipeline and dataset tests. No physical hardware or API calls."""
import ast
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import cv2
import numpy as np

UI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UI))
from plate_agent import PlateAgent, VisionClient, AgentError, parse_request
from depth_scene import capture_sample
from depth_dataset import label_sample, prepare, load_pair
from train_depth import reject_leakage
from sequences import Runner


class Client:
    model = 'fake'
    def ready(self): return True
    def describe(self, frame, preview, context):
        return dict(summary='Plate visible; relative depth only.', usage={})


class Depth:
    def public(self): return dict(installed=True)
    def infer(self, frame):
        return np.ones(frame.shape[:2], np.float32), frame.copy(), dict(
            interpretation='Relative depth only', units='arbitrary', kind='relative_inverse_depth')


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.frame = np.zeros((32, 48, 3), np.uint8)
        self.cam = SimpleNamespace(snap=lambda:self.frame.copy(), info=lambda:dict(open=True))
        self.agent = PlateAgent(Client(), Depth(), self.root)
        self.run = Runner()
        self.run.state = 'running'

    def execute(self, mode='analyze'):
        return self.agent.execute(self.run, self.cam, lambda:dict(connected=False),
            parse_request(dict(message='Find plate', mode=mode, session='test')))

    def test_removed_robot_commands(self):
        for word in ('Align', 'Descend', 'Grip', 'Move', 'Enable', 'Jog'):
            with self.assertRaises(AgentError): parse_request(dict(message=word))
        for mode in ('calibrate', 'align', 'grip', 'shell'):
            with self.assertRaises(AgentError): parse_request(dict(mode=mode))
        self.assertEqual(self.agent.public()['robot_tools'], [])

    def test_no_robot_module_or_executor(self):
        tree = ast.parse((UI / 'plate_agent.py').read_text(encoding='utf-8'))
        modules = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        self.assertFalse(set(modules) & {'sequences', 'robot_service', 'autonomy'})
        self.assertFalse(hasattr(self.agent, 'record'))

    def test_session_path_traversal_rejected(self):
        for session in ('../escape', 'C:/temp', '', 'a/b', 'a'*49):
            with self.assertRaises(AgentError): parse_request(dict(session=session))

    def test_lossless_capture_without_model_or_key(self):
        self.agent.depth.infer = lambda f: self.fail('Depth must not run')
        self.agent.client.describe = lambda *a: self.fail('API must not run')
        result = self.execute('capture')
        self.assertTrue(result['ok'], result)
        self.assertFalse(result['robot_motion'])
        folder = Path(result['sample_path'])
        self.assertTrue(np.array_equal(cv2.imread(str(folder/'rgb.png')), self.frame))
        metadata = json.loads((folder/'metadata.json').read_text())
        self.assertIsNone(metadata['ground_truth'])
        self.assertFalse(metadata['pose_synchronized'])
        self.assertFalse((folder/'prediction.npy').exists())

    def test_local_depth_has_no_api_request(self):
        self.agent.client.describe = lambda *a: self.fail('API must not run')
        result = self.execute('depth')
        self.assertTrue(result['ok'], result)
        self.assertTrue(Path(self.agent.depth_path).exists())
        metadata = json.loads((self.agent.sample_path/'metadata.json').read_text())
        self.assertEqual(metadata['prediction']['units'], 'arbitrary')
        self.assertFalse(metadata['prediction_is_ground_truth'])

    def test_haiku_receives_depth_and_returns_text_only(self):
        result = self.execute()
        self.assertTrue(result['ok'], result)
        self.assertTrue((self.agent.sample_path/'haiku.json').exists())
        self.assertFalse(result['robot_motion'])

    def test_api_failure_preserves_capture_and_depth(self):
        def fail(*args): raise AgentError('API unavailable')
        self.agent.client.describe = fail
        result = self.execute()
        self.assertFalse(result['ok'])
        self.assertTrue((Path(result['sample_path'])/'prediction.npy').exists())

    def test_stop_prevents_capture(self):
        self.run.request_stop()
        self.cam.snap = lambda:self.fail('No camera call after stop')
        self.assertFalse(self.execute()['ok'])

    def test_stop_after_inference_prevents_haiku(self):
        original = self.agent.depth.infer
        def infer(frame):
            self.run.request_stop()
            return original(frame)
        self.agent.depth.infer = infer
        self.agent.client.describe = lambda *a:self.fail('No API call after stop')
        self.assertFalse(self.execute()['ok'])

    def test_anthropic_payload_has_no_tools(self):
        client = VisionClient()
        client.set_key('test-secret-key')
        response = dict(stop_reason='end_turn', content=[dict(type='text', text='A plate.')], usage={})
        with patch('plate_agent.urllib.request.urlopen', return_value=BytesIO(json.dumps(response).encode())) as call:
            result = client.describe(self.frame, self.frame, {'instruction':'Find plate'})
        payload = json.loads(call.call_args.args[0].data)
        self.assertNotIn('tools', payload)
        self.assertNotIn('tool_choice', payload)
        self.assertNotIn('test-secret-key', json.dumps(payload))
        self.assertEqual(sum(b['type']=='image' for b in payload['messages'][0]['content']), 2)
        self.assertEqual(result['summary'], 'A plate.')

    def test_tool_response_rejected(self):
        client = VisionClient()
        client.set_key('test-secret-key')
        response = dict(stop_reason='tool_use', content=[dict(type='tool_use', name='grip')])
        with patch('plate_agent.urllib.request.urlopen', return_value=BytesIO(json.dumps(response).encode())):
            with self.assertRaises(AgentError): client.describe(self.frame, self.frame, {})

    def test_label_provenance_and_session_splits(self):
        measured = self.root/'measured.npy'
        np.save(measured, np.full(self.frame.shape[:2], .3, np.float32))
        for session in ('train', 'val', 'test'):
            folder, _ = capture_sample(self.frame, session, None, None, {}, self.root/'data')
            label_sample(folder, measured, 'rgbd_registered')
        counts = prepare(self.root/'data', self.root/'manifests', ['val'], ['test'])
        self.assertEqual(counts, dict(train=1, val=1, test=1))
        with self.assertRaises(ValueError): prepare(self.root/'data', self.root/'other', ['val'], ['val'])

    def test_wrong_shape_integer_labels_and_pseudolabels_rejected(self):
        folder, _ = capture_sample(self.frame, 'scene', None, None, {}, self.root/'data')
        for data in (np.ones((10,10), np.float32), np.ones((32,48), np.uint16), np.zeros((32,48), np.float32)):
            p = self.root/'measured.npy'
            np.save(p, data)
            with self.assertRaises(ValueError): load_pair(folder/'rgb.png', p)
        np.save(folder/'prediction.npy', np.ones((32,48), np.float32))
        with self.assertRaises(ValueError): label_sample(folder, folder/'prediction.npy', 'measured_plane')

    def test_missing_labels_and_training_leakage(self):
        capture_sample(self.frame, 'scene', None, None, {}, self.root/'data')
        with self.assertRaises(ValueError): prepare(self.root/'data', self.root/'out', ['val'], ['test'])
        with self.assertRaises(ValueError):
            reject_leakage([dict(session='same', rgb='a')], [dict(session='same', rgb='b')])

    def test_routes_local_mode_and_key_is_private(self):
        with patch.dict('os.environ', {'CEPHLA_AUDIT_DIR': str(self.root / 'audit')}):
            import app as console
        with patch.object(console, 'plate_agent', self.agent), \
                patch.object(console, 'draggo', SimpleNamespace(blocks_motion=False)), \
                patch.object(console.audit, 'event'), patch.dict('os.environ', {}, clear=True):
            self.agent.client = VisionClient()
            client = console.app.test_client()
            self.assertEqual(client.post('/agent/run', json={'mode':'analyze'}).status_code, 400)
            with patch.object(console.runner, 'start', return_value={'ok':True}) as start:
                self.assertEqual(client.post('/agent/run', json={'mode':'depth'}).status_code, 200)
                self.assertEqual(start.call_args.args[2], console.cam)
                self.assertEqual(start.call_args.args[3], console.svc.status)
            with patch.object(console.runner, '_thread', SimpleNamespace(is_alive=lambda:True)):
                self.assertEqual(client.post('/agent/run', json={'mode':'capture'}).status_code, 409)
                self.assertEqual(client.post('/seq/stop', json={}).status_code, 200)
            self.agent.client.set_key('test-secret-key')
            self.assertNotIn('test-secret-key', client.get('/agent/state').get_data(as_text=True))
            self.assertEqual(client.get('/agent/training').status_code, 200)


if __name__ == '__main__': unittest.main()
