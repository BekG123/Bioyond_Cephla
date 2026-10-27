"""Offline loop proposals: preserve approach, branch and original recording."""
import json
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from trajectory_pruning import prune_middle
from autonomy import TransferError


class PruningTests(unittest.TestCase):
    def setUp(self):
        self.q=dict(J2=0,J3=0,J4=0)
        self.start=dict(X=0,Y=0,Z=0,Rz=0)
        self.points=[dict(X=x,Y=y,Z=z,Rz=0) for x,y,z in
                     [(0,0,10),(20,0,10),(20,20,10),(1,0,10),(10,0,10),(10,0,0)]]

    def test_removes_loop_preserves_vertical_approaches_and_input(self):
        before=json.dumps(self.points)
        with patch('trajectory_pruning.check_path',side_effect=lambda a,b,q,*_:dict(q)):
            points,report=prune_middle(self.start,self.q,self.points,{})
        self.assertEqual(json.dumps(self.points),before)
        self.assertEqual(points[0],self.points[0])
        self.assertEqual(points[-2:],self.points[-2:])
        self.assertEqual(len(report['bridges']),1)
        self.assertFalse(report['execution_authorized'])
        self.assertGreater(report['saved_mm'],60)

    def test_unsafe_connector_does_not_remove_loop(self):
        def check(a,b,q,*_):
            if a['X']==0 and b['X']==1:raise TransferError('interior joint limit')
            return dict(q)
        with patch('trajectory_pruning.check_path',side_effect=check):
            points,report=prune_middle(self.start,self.q,self.points,{})
        self.assertEqual(points,self.points)
        self.assertEqual(report['bridges'],[])

    def test_wrong_branch_and_wrong_yaw_do_not_form_bridge(self):
        def check(a,b,q,*_):
            return {**q,'J4':10} if a['X']==0 and b['X']==1 else dict(q)
        with patch('trajectory_pruning.check_path',side_effect=check):
            points,_=prune_middle(self.start,self.q,self.points,{})
        self.assertEqual(points,self.points)
        self.points[3]['Rz']=10
        with patch('trajectory_pruning.check_path',side_effect=lambda a,b,q,*_:dict(q)):
            points,_=prune_middle(self.start,self.q,self.points,{})
        self.assertEqual(points,self.points)

    def test_repeated_xy_at_different_height_is_not_deleted(self):
        self.points[3]['Z']=8
        with patch('trajectory_pruning.check_path',side_effect=lambda a,b,q,*_:dict(q)):
            points,report=prune_middle(self.start,self.q,self.points,{})
        self.assertEqual(points,self.points)
        self.assertEqual(report['bridges'],[])

    def test_actual_recording_keeps_approaches_and_passes_reverse_ik(self):
        from recorded_return import RecordedReturn
        from trajectory_queue import prepare_points
        from trajectory_smoothing import group_points
        from autonomy import check_path
        here=Path(__file__).resolve().parents[1]
        source=here/'demonstrations/return_home_20261016_130748/return_path.json'
        if not source.exists():self.skipTest('Local recording unavailable')
        original=source.read_bytes();data=json.loads(original)
        cfg=json.loads((here/'robot_params.json').read_text())
        directed=RecordedReturn.directed(data,'to_hamilton')
        first=directed['trajectory'][0]
        replay=RecordedReturn('.',None,None,lambda:cfg,None,None)
        legs,_=replay.plan(directed)
        points,_=prepare_points(first['pose_mm'],first['joints'],legs,cfg)
        pruned,report=prune_middle(first['pose_mm'],first['joints'],points,cfg)
        lo,hi=report['plateau_indices']
        self.assertEqual(pruned[:lo],points[:lo])
        self.assertEqual(pruned[-(len(points)-hi):],points[hi:])
        self.assertEqual(len(report['bridges']),2)
        self.assertGreater(report['saved_percent'],40)
        grouped,_,grouping=group_points(first['pose_mm'],first['joints'],pruned,cfg)
        self.assertEqual(len(grouped),78)
        self.assertLessEqual(grouping['max_position_error_mm'],.25)
        self.assertLessEqual(grouping['max_yaw_error_deg'],.1)
        q=data['trajectory'][0]['joints']
        reverse=list(reversed([first['pose_mm']]+pruned))
        for a,b in zip(reverse,reverse[1:]):q=check_path(a,b,q,cfg,None)
        self.assertEqual(source.read_bytes(),original)


if __name__=='__main__':unittest.main()
