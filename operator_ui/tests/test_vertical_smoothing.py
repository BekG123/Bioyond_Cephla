"""Prevent hidden corners/reversals/unsafe long travel in vertical coalescing."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from trajectory_smoothing import coalesce_vertical_runs,vertical_span
from trajectory_queue import prepare_points
from autonomy import TransferError
from test_transfer import FakeService,PARAMS


class VerticalTests(unittest.TestCase):
    def setUp(self):
        self.s=FakeService();self.start=dict(X=250.,Y=0.,Z=100.,Rz=0.)
        self.points=[{**self.start,'Z':z} for z in (105,110,150,190,230,270,275,280)]

    def test_monotonic_run_merges_but_end_detail_is_preserved(self):
        with patch('trajectory_smoothing.check_path',side_effect=lambda a,b,q,*_:q):
            points,_,report=coalesce_vertical_runs(self.start,self.s.q,self.points,PARAMS)
        self.assertEqual([p['Z'] for p in points],[105,110,270,275,280])
        self.assertEqual(report['merges'][0]['commands_before'],4)
        self.assertEqual(self.points[3]['Z'],190)

    def test_z_reversal_lateral_corner_and_wrist_change_are_not_hidden(self):
        a=self.start
        for b,c in (({**a,'Z':150},{**a,'Z':140}),
                    ({**a,'Z':150,'X':251},{**a,'Z':190}),
                    ({**a,'Z':150,'Rz':1},{**a,'Z':190})):
            self.assertIsNone(vertical_span([a,b,c],0,2))

    def test_ik_failure_keeps_original_short_segments(self):
        def guard(a,b,q,*_):
            if abs(b['Z']-a['Z'])>45:raise TransferError('synthetic interior limit')
            return q
        with patch('trajectory_smoothing.check_path',side_effect=guard):
            points,_,_=coalesce_vertical_runs(self.start,self.s.q,self.points,PARAMS)
        self.assertEqual(points,self.points)

    def test_long_vertical_permission_never_allows_horizontal_or_rotational_shortcut(self):
        for end in ({**self.start,'Z':301}, {**self.start,'Z':200,'X':251},
                    {**self.start,'Z':200,'Rz':.2},{**self.start,'X':350}):
            with self.assertRaises(TransferError):
                prepare_points(self.start,self.s.q,[end],PARAMS,reviewed=True,vertical_runs=True)
        with self.assertRaises(TransferError):
            prepare_points(self.start,self.s.q,[{**self.start,'Z':200}],PARAMS,reviewed=True)

    def test_nonfinite_feedback_is_rejected(self):
        with self.assertRaises(TransferError):
            coalesce_vertical_runs(self.start,self.s.q,[{**self.start,'Z':float('nan')}],PARAMS)


if __name__=='__main__':unittest.main()
