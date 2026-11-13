"""Offline phase ordering and failure tests, using real route/IK validation."""
import json
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from autonomy import check_path,TransferError
import cellvis24_station_handling as handling


class HandlingTests(unittest.TestCase):
    def setUp(self):
        self.p=handling.reference();r=self.p['routes']['reverse']
        self.s=dict(pose_mm=deepcopy(r['start']),joints=deepcopy(r['start_joints']))
        self.e1=28;self.moves=[];self.closes=[];self.fail=False
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
        original=handling.FOLDER
        (self.folder/'short_side_grip_lift_trial.json').write_bytes((original/'short_side_grip_lift_trial.json').read_bytes())
        (self.folder/'hamilton_release_trial.json').write_text(json.dumps(dict(status='released_at_hamilton',final=self.s)))
        self.svc=Mock();self.svc.envelope={k:(self.p['global_envelope'][k]['min'],self.p['global_envelope'][k]['max']) for k in ('X','Y','Z')}
        self.svc.move_gripper.side_effect=self.jaw
        self.svc.program.return_value={'ok':True}
        self.run=Mock();self.run.stopped.return_value=False
        patches=[patch.object(handling,'FOLDER',self.folder),patch.object(handling,'preflight',side_effect=lambda svc:deepcopy(self.s)),
                 patch.object(handling,'native',side_effect=lambda svc:dict(moving=False,external_axes={'E1':self.e1,'E2':90.7166})),
                 patch.object(handling,'instrument_ready',return_value={'parked':True}),patch.object(handling,'LuaTrajectory'),patch.object(handling.time,'sleep')]
        for p in patches:p.start();self.addCleanup(p.stop)
        handling.LuaTrajectory.return_value.capability.return_value={'available':True,'version':220109}
        handling.LuaTrajectory.return_value.execute.side_effect=self.queue

    def jaw(self,target,speed):
        self.closes.append((target,speed));self.e1=target
        return {'ok':True}

    def queue(self,run,start,joints,points,cfg,speed,progress,**flags):
        self.moves.append((deepcopy(points),speed))
        if self.fail:raise TransferError('Simulated uncertain motion')
        offset=joints['J1']-start['Z'];q=deepcopy(joints);prev=start
        for point in points:
            q=check_path(prev,point,q,cfg,None);q['J1']=point['Z']+offset;prev=point
        self.s=dict(pose_mm=deepcopy(points[-1]),joints=q);progress('done',1,1)
        return {'ok':True}

    def execute(self,phase):
        p=handling.plan(self.svc,self.p['config'],phase)
        return handling.execute(self.run,self.svc,self.p['config'],p)

    def test_empty_return_then_retrieve_stops_held_without_release(self):
        result=self.execute('hamilton_empty_return');self.assertEqual(result['payload'],'empty')
        self.assertEqual(self.closes,[])
        result=self.execute('hamilton_retrieve')
        self.assertEqual(result['payload'],'held');self.assertTrue(result['support_inspection_required'])
        self.assertEqual(self.closes,[(26,10),(25,5)])
        self.assertAlmostEqual(self.s['pose_mm']['Z'],76.37)

    def test_motion_failure_stops_and_cannot_retry(self):
        self.fail=True
        with self.assertRaises(TransferError):self.execute('hamilton_empty_return')
        self.svc.program.assert_called_once_with('stop')
        self.assertEqual(len(self.moves),1)
        with self.assertRaises(TransferError):handling.plan(self.svc,self.p['config'],'hamilton_empty_return')
        self.assertEqual(len(self.moves),1)

    def test_changed_jaws_and_missing_predecessor_block(self):
        self.e1=25
        with self.assertRaises(TransferError):handling.plan(self.svc,self.p['config'],'hamilton_empty_return')
        with self.assertRaises(FileNotFoundError):handling.plan(self.svc,self.p['config'],'hamilton_retrieve')
        self.assertEqual(self.moves,[])


if __name__=='__main__':unittest.main()
