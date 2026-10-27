import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import empty_grip_baseline as baseline


class Service:
    def __init__(self):self.e1=28.;self.moves=[];self.stops=[];self.fail=False;self.recovered=False
    def pose_mm(self):return dict(X=300.,Y=0.,Z=200.,Rz=0.)
    def external_axes(self):return {'E1':self.e1}
    def _preflight(self):return None
    def move_gripper(self,target,**kwargs):
        self.moves.append(target);self.e1=target
        return {'ok':True,'recovered':self.recovered}
    def torque_report(self,**kwargs):
        return dict(ok=not self.fail,telemetry_live=True,e1_position=self.e1,e1_torque=1.,joints={})
    def program(self,action):self.stops.append(action);return {'ok':True}


class Run:
    state='running'
    def stopped(self):return False
    def say(self,*args):pass


class Tests(unittest.TestCase):
    def test_dense_local_baseline_uses_exact_start_and_small_steps(self):
        s=Service();s.e1=4.1
        with tempfile.TemporaryDirectory() as folder,patch.object(baseline.time,'sleep'):
            result=baseline.run_empty_baseline(Run(),s,folder,start_mm=4.1)
        self.assertTrue(result['ok'])
        self.assertEqual(s.moves,[4.,3.9,3.8])
        self.assertEqual(result['positions'],4)

    def test_short_targets_cover_contact_region_without_exceeding_floor(self):
        self.assertEqual(baseline.SHORT_TARGETS[:4],(20.,12.,8.,7.))
        self.assertEqual(baseline.SHORT_TARGETS[-1],3.8)
        for previous,target in zip(baseline.SHORT_TARGETS[3:],baseline.SHORT_TARGETS[4:]):
            self.assertAlmostEqual(previous-target,.1)

    def test_targets_are_bounded_monotone_increments(self):
        self.assertEqual(len(baseline.TARGETS),242)
        self.assertEqual(baseline.TARGETS[-1],3.8)
        previous=28.
        for target in baseline.TARGETS:
            self.assertAlmostEqual(previous-target,.1);previous=target

    def execute(self,s,run=None):
        with tempfile.TemporaryDirectory() as folder,patch.object(baseline,'TARGETS',(27.9,)),patch.object(baseline,'FLOOR',27.9),patch.object(baseline.time,'sleep'):
            return baseline.run_empty_baseline(run or Run(),s,folder)

    def test_success_records_without_grasp_claim(self):
        s=Service();r=self.execute(s)
        self.assertTrue(r['ok']);self.assertFalse(r['grasp_verified'])
        self.assertEqual(s.moves,[27.9]);self.assertEqual(s.stops,[])

    def test_report_failure_prevents_closing(self):
        s=Service();s.fail=True
        self.assertFalse(self.execute(s)['ok']);self.assertEqual(s.moves,[])

    def test_uncertain_completion_never_retries(self):
        s=Service();s.recovered=True
        self.assertFalse(self.execute(s)['ok']);self.assertEqual(s.moves,[27.9])
        self.assertEqual(s.stops,['stop'])

    def test_operator_stop_or_wrong_start_prevents_closing(self):
        s=Service();r=Run();r.stopped=lambda:True
        self.assertFalse(self.execute(s,r)['ok']);self.assertEqual(s.moves,[])
        s=Service();s.e1=0.
        self.assertFalse(self.execute(s)['ok']);self.assertEqual(s.moves,[])


if __name__=='__main__':unittest.main()
