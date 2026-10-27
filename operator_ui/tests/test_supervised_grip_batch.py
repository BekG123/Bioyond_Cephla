from copy import deepcopy
import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import supervised_grip_batch as batch


class Run:
    state='running'
    cancelled=False
    def stopped(self): return self.cancelled
    def say(self,*args): pass


class Service:
    def __init__(self):
        self.e1=5.3;self.moves=[];self.stops=[];self.anomaly=False;self.recovered=False;self.bias=0
    def pose_mm(self): return dict(X=300,Y=0,Z=70,Rz=90)
    def external_axes(self): return dict(E1=self.e1)
    def _preflight(self): return None
    def move_gripper(self,target,**kwargs):
        self.moves.append(target);self.e1=target
        return dict(ok=True,recovered=self.recovered)
    def torque_report(self,**kwargs):
        return dict(ok=True,telemetry_live=True,e1_position=self.e1,
            e1_torque=(120 if self.anomaly and self.moves else 100)+self.bias,
            joints=dict(J1=50,J2=50,J3=50,J4=50))
    def program(self,action): self.stops.append(action);return dict(ok=True)


class Tests(unittest.TestCase):
    def test_explicit_reference_selection_rejects_tampering_and_path_escape(self):
        baseline=dict(kind='empty_claw_baseline',ok=True,operator_confirmed_empty=True,speed=5,
                      positions=[dict(target_mm=5.3,samples=[dict(raw_torque=99),dict(raw_torque=101)])])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            folder=root/'demonstrations/empty_grip_baseline'
            folder.mkdir(parents=True)
            p=folder/('a'*32+'.json')
            raw=json.dumps(baseline).encode()
            p.write_bytes(raw)
            selected=root/'demonstrations/grip_baseline_selection.json'
            choice=dict(path='empty_grip_baseline/'+p.name,sha256=hashlib.sha256(raw).hexdigest())
            selected.write_text(json.dumps(choice))
            with patch.object(batch,'ROOT',root):
                self.assertEqual(batch.selected_reference(),(p.resolve(),raw))
                p.write_bytes(raw+b' ')
                with self.assertRaisesRegex(ValueError,'changed'):
                    batch.selected_reference()
                p.write_bytes(raw)
                selected.write_text(json.dumps({**choice,'path':'../'+p.name}))
                with self.assertRaisesRegex(ValueError,'outside'):
                    batch.selected_reference()
                baseline['ok']=False
                raw=json.dumps(baseline).encode()
                p.write_bytes(raw)
                selected.write_text(json.dumps({**choice,'sha256':hashlib.sha256(raw).hexdigest()}))
                with self.assertRaisesRegex(ValueError,'completed'):
                    batch.selected_reference()

    def test_sparse_bracketing_is_not_a_local_reference(self):
        with self.assertRaisesRegex(ValueError,'exact empty measurement'):
            batch.reference_band(10.1,[(8.,105.,108.),(12.,110.,114.)],5.6)

    def execute(self,svc,run=None,tare=False):
        baseline=dict(kind='empty_claw_baseline',ok=True,operator_confirmed_empty=True,speed=5,
            start_pose_mm=svc.pose_mm(),positions=[
                dict(target_mm=x,samples=[dict(raw_torque=99),dict(raw_torque=101)])
                for x in (5.,5.1,5.2,5.3)])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/'baseline.json';p.write_text(json.dumps(baseline))
            with patch.object(batch,'ROOT',root),patch.object(batch,'BASELINE',p),patch.object(
                    batch,'labeled_offset',return_value=dict(offset=6,observed_range=[106,106])):
                return batch.run_batch(run or Run(),svc,5.3,66,tare)

    def test_fixed_noncontact_bias_does_not_hide_new_departure(self):
        s=Service();s.bias=6
        self.assertTrue(self.execute(s,tare=True)['ok'])
        self.assertEqual(s.moves,[5.2,5.1,5.])
        s=Service();s.bias=6;s.anomaly=True
        self.assertIn('Torque differs',self.execute(s,tare=True)['reason'])
        self.assertEqual(s.moves,[5.2])
        s=Service();s.bias=20
        self.assertIn('no longer match',self.execute(s,tare=True)['reason'])
        self.assertEqual(s.moves,[])

    def test_label_requires_exact_opening_and_matching_baseline(self):
        baseline=dict(start_pose_mm=dict(X=300,Y=0,Z=70,Rz=90),
                      positions=[dict(target_mm=9.8,samples=[dict(raw_torque=100)])])
        raw=json.dumps(baseline).encode()
        trial=dict(baseline_sha256=hashlib.sha256(raw).hexdigest(),
                   start_pose_mm=baseline['start_pose_mm'],status='stopped_for_review',
                   ok=True,final_e1_mm=9.8)
        review=dict(operator_confirmed_no_contact=True,contact_label='no_contact_operator_confirmed',
                    e1_mm=9.8,batch_id='a'*32,
                    fresh_stationary_reports=[dict(ok=True,telemetry_live=True,
                        e1_position=9.8,e1_torque=106)]*3)
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);p=folder/'review.json';p.write_text(json.dumps(review))
            (folder/('a'*32+'.json')).write_text(json.dumps(trial))
            with patch.object(batch,'NONCONTACT_REVIEW',p):
                self.assertEqual(batch.labeled_offset(baseline,raw,9.8)['offset'],6)
                with self.assertRaises(ValueError):
                    batch.labeled_offset(baseline,raw,9.7)
                with self.assertRaises(ValueError):
                    batch.labeled_offset(baseline,b'changed',9.8)
                review['operator_confirmed_no_contact']=False
                p.write_text(json.dumps(review))
                with self.assertRaises(ValueError):
                    batch.labeled_offset(baseline,raw,9.8)

    def test_batch_ends_at_precontact_stop(self):
        s=Service();r=self.execute(s)
        self.assertTrue(r['ok']);self.assertEqual(s.moves,[5.2,5.1,5.0])
        self.assertFalse(r['grasp_verified']);self.assertEqual(s.stops,[])

    def test_torque_departure_stops_before_next_increment(self):
        s=Service();s.anomaly=True;r=self.execute(s)
        self.assertEqual(s.moves,[5.2]);self.assertIn('Torque differs',r['reason'])

    def test_uncertain_command_never_retries(self):
        s=Service();s.recovered=True;r=self.execute(s)
        self.assertFalse(r['ok']);self.assertEqual(s.moves,[5.2]);self.assertEqual(s.stops,['stop'])

    def test_stop_prevents_motion(self):
        s=Service();run=Run();run.cancelled=True
        self.assertFalse(self.execute(s,run)['ok']);self.assertEqual(s.moves,[])

    def test_plate_present_reference_is_rejected(self):
        with self.assertRaises(ValueError):
            batch.references(dict(kind='plate_present_closing_measurement',ok=True))


if __name__=='__main__': unittest.main()
