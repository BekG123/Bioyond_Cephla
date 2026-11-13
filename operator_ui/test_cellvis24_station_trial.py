"""Offline tests: no controller or instrument connections."""
import json
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import cellvis24_station_trial as trial


class CellvisStationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.profile = root/'profile.json'; self.source = root/'finish.json'; self.output = root/'trial.json'
        self.start = dict(X=312.495,Y=-66.304,Z=105.718,Rz=89.842)
        self.h = dict(descent_pose_mm=dict(self.start,Z=75.718),proof_lift_accepted=True,
                      candidate_proof_lift={'operator_retention_acceptance':{'accepted':True}})
        self.profile.write_text(json.dumps(dict(id='cellvis_p24_1_5h_n',handling=self.h)))
        self.source.write_text(json.dumps(dict(status='calibration_finish_completed_plate_released_in_HOME',after={'robot':{'pose_mm':self.start}})))
        self.short = dict(descent_endpoint=dict(X=306.2,Y=-62.88,Z=74.37,Rz=87.88),holder_e2_degrees=90.7166122918)
        self.service = Mock(envelope={'X':[200,450],'Y':[-250,380],'Z':[70,400]})
        self.native = dict(moving=False,external_axes={'E1':28,'E2':1.77})
        self.state = dict(pose_mm=self.start,joints={'J1':1,'J2':2,'J3':3,'J4':4})
        self.stack = []
        for name,value in [('PROFILE',self.profile),('SOURCE',self.source),('OUTPUT',self.output)]:
            p=patch.object(trial,name,value); p.start(); self.addCleanup(p.stop)
        for name,value in [('reference',({'config':{}},{},self.short)),('preflight',self.state),('native',self.native),('check_path',self.state['joints'])]:
            p=patch.object(trial,name,return_value=value); p.start(); self.addCleanup(p.stop)
        p=patch.object(trial,'LuaTrajectory'); self.lua=p.start(); self.addCleanup(p.stop)
        self.lua.return_value.capability.return_value={'available':True}

    def test_height_hypothesis_does_not_grant_grip_or_transfer(self):
        p=trial.plan(self.service,{})
        self.assertAlmostEqual(p['geometry']['seat']['Z'],76.37)
        self.assertFalse(p['grip']); self.assertFalse(p['transfer'])
        self.assertTrue(p['stop_before_grip'])
        self.service._hostpoint.assert_not_called()

    def test_refuses_closed_jaws_wrong_angle_and_changed_pose(self):
        for change in ('jaw','holder','pose'):
            with self.subTest(change=change):
                n=deepcopy(self.native); s=deepcopy(self.state)
                if change=='jaw':n['external_axes']['E1']=25
                if change=='holder':n['external_axes']['E2']=90
                if change=='pose':s['pose_mm']['X']+=1
                with patch.object(trial,'native',return_value=n),patch.object(trial,'preflight',return_value=s):
                    with self.assertRaises(trial.TransferError):trial.plan(self.service,{})
        self.service._hostpoint.assert_not_called()

    def test_refuses_repeat_and_unaccepted_grip(self):
        self.output.write_text('{}')
        with self.assertRaises(trial.TransferError):trial.plan(self.service,{})
        self.output.unlink()
        self.h['proof_lift_accepted']=False
        self.profile.write_text(json.dumps(dict(id='cellvis_p24_1_5h_n',handling=self.h)))
        with self.assertRaises(trial.TransferError):trial.plan(self.service,{})

    def test_changed_plan_cannot_dispatch_rotation(self):
        p=trial.plan(self.service,{})
        p['geometry']['seat']['Z']-=2
        with self.assertRaises(trial.TransferError):trial.execute(Mock(),self.service,{},p)
        self.service._hostpoint.assert_not_called()
        self.assertFalse(self.output.exists())


if __name__=='__main__':unittest.main()
