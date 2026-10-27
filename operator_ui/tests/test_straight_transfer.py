"""Straight-transfer candidates remain offline and are checked throughout IK."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from straight_transfer import plan_straight_transfer
from autonomy import TransferError


class StraightTests(unittest.TestCase):
    def setUp(self):
        here=Path(__file__).resolve().parents[1]
        source=here/'demonstrations/return_home_20261016_130748/return_path.json'
        if not source.exists():self.skipTest('Local recording unavailable')
        d=json.loads(source.read_text());self.home,self.ham=d['trajectory'][-1],d['trajectory'][0]
        self.cfg=json.loads((here/'robot_params.json').read_text())

    def test_three_segments_both_directions_preserve_station_xy_and_no_runtime_permission(self):
        for a,b in ((self.home,self.ham),(self.ham,self.home)):
            r=plan_straight_transfer(a['pose_mm'],b['pose_mm'],a['joints'],self.cfg,253.8)
            self.assertEqual(len(r['points']),3)
            self.assertTrue(r['ik_passed']);self.assertFalse(r['execution_authorized'])
            for k in ('X','Y','Rz'):
                self.assertAlmostEqual(r['points'][0][k],a['pose_mm'][k],delta=.0051)
                self.assertEqual(r['points'][1][k],r['points'][2][k])
            self.assertEqual(r['points'][0]['Z'],r['points'][1]['Z'])

    def test_bad_height_nonfinite_or_unreachable_target_is_rejected(self):
        for height in (100,float('nan'),True):
            with self.assertRaises(TransferError):plan_straight_transfer(self.home['pose_mm'],self.ham['pose_mm'],self.home['joints'],self.cfg,height)
        with self.assertRaises(TransferError):plan_straight_transfer(self.home['pose_mm'],{**self.ham['pose_mm'],'X':900},self.home['joints'],self.cfg,253.8)


if __name__=='__main__':unittest.main()
