import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
from cellvis24_image_pipeline import prepare_raw,decode_reference,median5,metadata
from cellvis24_calibration import reference,ROOT,evaluate,capture,OBSERVATION
from build_cellvis24_camera_reference_v2 import build
from autonomy import TransferError

class ImagePipelineTests(unittest.TestCase):
    def test_reproduces_all_commissioned_reference_targets_without_reteaching(self):
        d=build();self.assertEqual(d,json.loads((ROOT/'Pick and Hold/Calibration/plate_profiles/cellvis24_camera_reference_v2.json').read_bytes()))
        for p in d['reference_reproduction']:
            self.assertEqual(p['target_delta'],dict(x=0.,y=0.,rz=0.))

    def test_raw_and_reference_paths_produce_identical_prepared_image(self):
        p=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows/633b3cebf767442ead7dbe91f6366786/calibration_0_0.png'
        raw=cv2.imread(str(p));ok,encoded=cv2.imencode('.jpg',raw,[cv2.IMWRITE_JPEG_QUALITY,82])
        self.assertTrue(ok)
        self.assertTrue(np.array_equal(prepare_raw(raw),decode_reference(encoded.tobytes())))
        self.assertEqual(prepare_raw(raw).shape,(2048,3072,3))

    def test_wrong_input_or_incomplete_burst_rejected(self):
        for f in (np.zeros((100,100,3),np.uint8),np.zeros((2048,3072),np.uint8),None):
            with self.assertRaises(ValueError):prepare_raw(f)
        with self.assertRaises(ValueError):median5([])
        with self.assertRaises(ValueError):decode_reference(b'not a JPEG')

    def accepted(self):
        d=reference();r=json.loads((ROOT/d['files']['observation']['path']).read_bytes())
        return [deepcopy(b['measurement']) for b in r['bursts']]

    def test_one_outside_burst_not_hidden_by_median(self):
        ms=self.accepted();b=reference()['raw_target']
        for m,dx in zip(ms,[.40,.41,.51]):m['target'].update(x=b['x']+dx,y=b['y'])
        r=evaluate(ms)
        self.assertFalse(r['ok']);self.assertTrue(r['xy_limit_straddled'])
        self.assertAlmostEqual(r['max_shift_mm'],.51)
        self.assertEqual(len(r['bursts']),3)

    def test_tool_target_instability_checked_even_with_stable_center(self):
        ms=self.accepted();ms[-1]['target']['x']+=.3
        r=evaluate(ms)
        self.assertFalse(r['ok']);self.assertEqual(r['code'],'unstable_measurements')
        self.assertGreater(r['target_xy_spread_mm'],.25)
        self.assertLess(r['xy_spread_mm'],.25)

    def test_live_capture_saves_prepared_evidence_and_failure_assessment(self):
        folder=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows/633b3cebf767442ead7dbe91f6366786'
        frames=[cv2.imread(str(folder/f'calibration_{i}_{j}.png')) for i in range(3) for j in range(5)]
        class Camera:
            def snap(self):return frames.pop(0)
        snapshots=[]
        with tempfile.TemporaryDirectory() as tmp,patch('cellvis24_calibration.time.sleep'):
            with self.assertRaises(TransferError):
                capture(Camera(),lambda *a:({'pose_mm':OBSERVATION},{}),Path(tmp),lambda r:snapshots.append(deepcopy(r)))
            self.assertEqual(len(list(Path(tmp).glob('calibration_*.png'))),15)
            self.assertEqual(len(list(Path(tmp).glob('prepared_median_*.png'))),3)
        result=snapshots[-1]
        self.assertEqual(result['image_pipeline'],metadata())
        self.assertFalse(result['assessment']['ok'])
        self.assertGreater(result['assessment']['max_shift_mm'],.5)
        self.assertLess(result['assessment']['max_shift_mm'],.7)
        self.assertEqual(result['rim_sample_span'],[.25,.75])
        self.assertEqual(len(result['bursts']),3)

    def test_rejected_rim_keeps_failing_burst_hashes_and_error(self):
        from vision import DetectionError
        folder=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows/7c29ef6a68724ffeb9a4365456a98e33'
        frames=[cv2.imread(str(folder/f'calibration_1_{j}.png')) for j in range(5)]
        class Camera:
            def snap(self):return frames.pop(0)
        snapshots=[]
        with tempfile.TemporaryDirectory() as tmp,patch('cellvis24_calibration.time.sleep'),patch('cellvis24_observation.measure',side_effect=DetectionError('bad rim')):
            with self.assertRaisesRegex(DetectionError,'bad rim'):
                capture(Camera(),lambda *a:({'pose_mm':OBSERVATION},{}),Path(tmp),lambda r:snapshots.append(deepcopy(r)))
            self.assertTrue((Path(tmp)/'prepared_median_0.png').exists())
        burst=snapshots[-1]['bursts'][0]
        self.assertEqual(burst['status'],'rejected')
        self.assertEqual(burst['error'],'bad rim')
        self.assertEqual(len(burst['hashes']),5)
        self.assertEqual(len(burst['prepared_median_sha256']),64)
        self.assertNotIn('measurement',burst)
