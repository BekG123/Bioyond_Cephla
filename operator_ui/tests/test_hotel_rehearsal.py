"""Fake HTTP service only; these tests never connect to hardware."""
import contextlib
import copy
import io
import json
import math
from pathlib import Path
import sys
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hotel_rehearsal import Rehearsal,ROOT,AXES,split_leg,check_path

RECIPE=ROOT/'mujoco_sim/runs/current_pose_20261009_headless/waypoints.json'

class Fake(Rehearsal):
    def __init__(self):
        self.output=ROOT/'operator_ui/tests/nonexistent_hotel_test_output'
        self.started=time.time();self.moves=0;self.events=[];self.commands=[];self.fail=None
        self.s=json.loads((ROOT/'mujoco_sim/current_pose_snapshot_20261009.json').read_text())
        self.s['sequence']=dict(active=False)
        self.s['robot'].update(control_mode=dict(mode='auto'),program_state=dict(state='running'))
        self.e1=0.;self.params=json.loads((ROOT/'operator_ui/robot_params.json').read_text())
    def record(self,event,**fields):self.events.append(dict(event=event,**fields))
    def request(self,path,body=None):
        if path=='/state':return copy.deepcopy(self.s)
        if path=='/gripper':
            if body['action']=='torque':return dict(ok=True,telemetry_live=True,e1_torque=0,e1_position=self.e1)
            self.commands.append((path,body));self.e1=body['e1']
            return dict(ok=True,gripper=dict(e1_position=self.e1,e1_torque=0))
        self.commands.append((path,body))
        if self.fail:return self.fail
        start=self.s['robot']['pose_mm']
        target=dict(zip(AXES,[body.get(k.lower(),start[k]) for k in AXES]))
        if path=='/jog':target={**start,'Rz':start['Rz']+body['delta']}
        q=check_path(start,target,self.s['robot']['joints'],self.params,self.envelope(self.s))
        self.s['robot'].update(pose_mm=target,joints=q)
        return dict(ok=True,pose_after=target)

class Tests(unittest.TestCase):
    def run_quiet(self,f):
        with contextlib.redirect_stdout(io.StringIO()):return f.run(RECIPE,True)
    def test_route_and_segment_bounds(self):
        f=Fake();result=self.run_quiet(f)
        self.assertTrue(result['ok']);self.assertFalse(result['haiku_execution'])
        previous=f.events[0]['initial']['robot']['pose_mm']
        for row in f.events:
            if row['event']!='motion_command':continue
            target=row['target']
            if row['route']=='/jog':
                self.assertLessEqual(abs(row['body']['delta']),5.0001);self.assertGreaterEqual(previous['Z'],300)
            else:
                self.assertLessEqual(math.hypot(target['X']-previous['X'],target['Y']-previous['Y']),10.001)
                self.assertLessEqual(abs(target['Z']-previous['Z']),5.001)
            previous=target
    def test_uncertain_result_never_retried(self):
        for failure in [dict(ok=False,error='UNKNOWN STATE'),dict(ok=True,recovered='connection lost')]:
            f=Fake();f.fail=failure
            with self.assertRaises(ValueError):self.run_quiet(f)
            self.assertEqual(sum(path in ('/move','/jog') for path,_ in f.commands),1)
    def test_disabled_envelope_and_wrong_start_block_motion(self):
        for modify in [lambda f:f.s['envelope'].update(enabled=False),lambda f:f.s['robot']['pose_mm'].update(X=350)]:
            f=Fake();modify(f)
            with self.assertRaises(ValueError):self.run_quiet(f)
            self.assertEqual(f.commands,[])
    def test_low_or_combined_rotation_rejected(self):
        a=dict(X=300,Y=0,Z=150,Rz=0)
        for b in [{**a,'Rz':10},{**a,'Z':330,'Rz':10}]:
            with self.assertRaises(ValueError):split_leg(a,b)

if __name__=='__main__':unittest.main()
