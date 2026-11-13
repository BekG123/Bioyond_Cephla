import sys,json,unittest
from pathlib import Path
from copy import deepcopy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hamilton_stopped_return as m
class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.cfg=m.taught.reference()['cfg']
        self.env={k:tuple(v) for k,v in m.taught.reference()['parent']['envelope'].items()}
        self.state=dict(pose_mm=dict(X=187.466,Y=-364.797,Z=84.588,Rz=.173),joints=dict(J1=45.989,J2=-58.08116,J3=135.29014,J4=-77.03632),external_axes=dict(E1=4.36353))
    def test_preserves_jaw_and_vertical_exit(self):
        p=m.plan(self.state,self.cfg,self.env)
        self.assertEqual(p['e1'],4.36353)
        self.assertEqual([g['speed'] for g in p['groups']],[5,5,40,40])
        from trajectory_queue import prepare_points
        start=p['start'];q=p['joints']
        for g in p['groups']:
            points,q=prepare_points(start,q,g['points'],self.cfg,reviewed=True)
            start=points[-1]
        self.assertEqual(p['vertices'][1],{**p['start'],'Z':212})
        self.assertGreater(p['dense_samples'],500)
    def test_other_starts_or_limits_rejected(self):
        for key,value in [('X',180),('Z',40),('Rz',8)]:
            s=deepcopy(self.state);s['pose_mm'][key]=value
            with self.subTest(key=key),self.assertRaises(m.TransferError):m.plan(s,self.cfg,self.env)
        cfg={**self.cfg,'j4_hard_abs_deg':280}
        with self.assertRaises(m.TransferError):m.plan(self.state,cfg,self.env)
if __name__=='__main__':unittest.main()
