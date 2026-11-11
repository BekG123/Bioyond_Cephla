"""Saved-frame and synthetic negative evaluation. No hardware access."""
import json
import sys
import unittest
from pathlib import Path
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'operator_ui'))
from projected_alignment import perception_at_height,target_from_mark
from plate48_workflow import reference,match_placement
from vision import DetectionError
from autonomy import TransferError


class ImageRobustness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from vision_runtime import verify
        verify()
        cls.p,_,_=perception_at_height()
        cls.raw=reference(require_grip=False)[2]
        cls.rows=json.loads((ROOT/'operator_ui/reports/plate48_diagnosis_20261101/replay.json').read_text())
        cls.pose=cls.rows[0]['pose']
        cls.image=cv2.imread(cls.rows[-1]['image'])

    def check_image(self,image,pose=None):
        self.p.tracker.previous_verified_seed=None
        m=self.p.measure(image,pose or self.pose)
        target=target_from_mark(pose or self.pose,m,self.p.cfg)
        match_placement(target,self.raw)
        return m,target

    def test_saved_successes_and_failures(self):
        for row in self.rows:
            with self.subTest(image=row['image']):
                self.check_image(cv2.imread(row['image']),row['pose'])

    def test_held_out_runs_three_consecutive_measurements(self):
        folder=ROOT/'operator_ui/logs/audit/20261101T085134Z_f92e3c78'
        rows=[]
        for file in folder.glob('*.jsonl'):
            rows.extend(json.loads(line) for line in file.open())
        for run in ('5626ec030b4843898d17df4b54df7178',
                    '1e370a09b2bd4fc4ac06e1bcd979769f',
                    '04b5efda0854494abb9ad2e05e1611ab'):
            frames=[r for r in rows if r.get('run_id')==run and r.get('event')=='plate48_stationary_image_burst'][:3]
            self.assertEqual(len(frames),3)
            self.p.tracker.previous_verified_seed=None
            accepted=[]
            for row in frames:
                with self.subTest(run=run,image=row['median_image']):
                    m=self.p.measure(cv2.imread(row['median_image']),row['pose'])
                    match_placement(target_from_mark(row['pose'],m,self.p.cfg),self.raw)
                    for previous in accepted:
                        self.assertLessEqual(np.linalg.norm(np.array(previous)-m['error_xy_mm']),.25)
                    accepted.append(m['error_xy_mm'])

    def test_brightness_and_sensor_noise(self):
        rng=np.random.default_rng(42)
        for image in [np.clip(self.image.astype(float)*.95+5,0,255).astype(np.uint8),
                      np.clip(self.image.astype(float)+rng.normal(0,1,self.image.shape),0,255).astype(np.uint8)]:
            with self.subTest(kind='photometric'):
                self.check_image(image)

    def test_shifted_and_rotated_plate_rejected(self):
        size=(self.image.shape[1],self.image.shape[0])
        polygon=np.rint(self.p.tracker.anchor.corners*self.image.shape[1]/1200).astype(np.int32)
        mask=np.zeros(self.image.shape[:2],np.uint8)
        cv2.fillConvexPoly(mask,polygon,255)
        mask=cv2.dilate(mask,np.ones((41,41),np.uint8))
        for dx,dy,angle in [(30,0,0),(-30,0,0),(0,30,0),(0,-30,0),(0,0,1),(0,0,-1)]:
            with self.subTest(dx=dx,dy=dy,angle=angle):
                h=cv2.getRotationMatrix2D(tuple(polygon.mean(axis=0)),angle,1)
                h[:,2]+=[dx,dy]
                warped=cv2.warpAffine(self.image,h,size)
                moved=cv2.warpAffine(mask,h,size)
                union=cv2.bitwise_or(mask,moved)>0
                image=self.image.copy();image[union]=warped[union]
                with self.assertRaises((DetectionError,TransferError)):self.check_image(image)

    def test_missing_or_occluded_plate_rejected(self):
        blocked=self.image.copy()
        h,w=blocked.shape[:2]
        blocked[h//4:3*h//4,w//3:]=0
        for image in [np.zeros_like(self.image),blocked]:
            with self.subTest(kind='missing_support'), self.assertRaises((DetectionError,TransferError)):
                self.check_image(image)

    def test_placement_limits_unchanged(self):
        for delta in [dict(x=self.raw['x']+.501),dict(rz=self.raw['rz']+.201)]:
            with self.subTest(delta=delta),self.assertRaises(TransferError):
                match_placement(dict(self.raw,**delta),self.raw)

    def test_alignment_failure_sequence_in_deployed_runtime(self):
        path=ROOT/'operator_ui/reports/projected_alignment/20261101_011711_e2f1c379.jsonl'
        frames=[json.loads(line) for line in path.read_text().splitlines()
                if json.loads(line)['event']=='stationary_image_burst']
        self.assertEqual(len(frames),8)
        self.p.tracker.previous_verified_seed=None
        for row in frames:
            with self.subTest(image=row['median_image']):
                m=self.p.measure(cv2.imread(row['median_image']),row['pose'])
                match_placement(target_from_mark(row['pose'],m,self.p.cfg),self.raw)


if __name__=='__main__':unittest.main()
