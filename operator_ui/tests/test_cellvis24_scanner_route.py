import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import cellvis24_scanner_route as c
import test_scanner_direct_route as fixtures
from test_trajectory_queue import PARAMS
from autonomy import TransferError,ik,wrap
from trajectory_queue import LuaTrajectory


class CellvisScannerTests(unittest.TestCase):
    def setUp(self):
        fixtures.DirectScannerTests.setUp(self)
        old=dict(self.s.pose);q=self.s.q
        start=dict(X=312.8,Y=-65.98,Z=80.72,Rz=90.12)
        q2,q3=ik(start['X'],start['Y'],(q['J2'],q['J3']),PARAMS)
        self.s.q=dict(J1=q['J1']+start['Z']-old['Z'],J2=q2,J3=q3,
                      J4=q['J4']+wrap(start['Rz']-old['Rz'])-(q2+q3-q['J2']-q['J3']))
        self.s.pose=start
        self.g=dict(id='a'*32,start=start,points=[dict(start,Z=300),dict(c.TARGET,Z=300),dict(c.TARGET)],cfg=PARAMS,sources={'fixture':'pinned'})
        p=patch.object(c,'geometry',return_value=self.g);p.start();self.addCleanup(p.stop)
        p=patch.object(c,'RUNS',self.folder);p.start();self.addCleanup(p.stop)
        (self.folder/self.g['id']/'supervised_grip/proof_lift').mkdir(parents=True)

    def test_three_points_one_queue_at137_grip_and_original_workspace_preserved(self):
        approved=json.loads(json.dumps(c.plan(self.s,PARAMS,self.g['id'])))
        result=c.execute(self.run,self.s,PARAMS,approved)
        self.assertTrue(result['ok']);self.assertEqual(len(self.s.robot.calls),3)
        self.assertTrue(all(call[1]==137 for call in self.s.robot.calls))
        self.assertEqual(self.s.robot.barriers,1);self.assertEqual(self.s.grips,[])
        self.assertEqual(self.s.envelope,c.ORIGINAL)
        d=json.loads(Path(result['record']).read_bytes())
        self.assertFalse(d['release_sent']);self.assertEqual(d['status'],'completed')

    def test_changed_route_receipt_or_unmonitored_service_rejected(self):
        self.s.envelope=dict(c.TRIAL)
        holding=c.CellvisHoldingService(self.s,deepcopy(self.g))
        bad=deepcopy(self.g['points']);bad[0]['Z']=290
        with self.assertRaises(TransferError):
            LuaTrajectory(holding).execute(self.run,self.s.pose,self.s.q,bad,PARAMS,137,lambda *a:None,reviewed=True,scanner_loaded='cellvis_direct')
        with self.assertRaises(TransferError):
            LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,self.g['points'],PARAMS,137,lambda *a:None,reviewed=True,scanner_loaded='cellvis_direct')
        holding.scanner_binding['sources']['fixture']='changed'
        with self.assertRaises(TransferError):c.prepare_for_service(holding,self.s.pose,self.s.q,self.g['points'],PARAMS,c.TRIAL)
        self.assertEqual(self.s.robot.jobs,[])

    def test_lost_grip_stops_no_retry_and_restores_workspace(self):
        approved=c.plan(self.s,PARAMS,self.g['id'])
        self.s.robot.block_motion=True
        self.s.external_axes=lambda:{'E1':4.2 if self.s.robot.started.is_set() else 3.9}
        def stop(action):
            self.s.robot.program_state='stopped';self.s.robot.released.set();return dict(ok=True)
        self.s.program=stop
        with self.assertRaisesRegex(TransferError,'Gripper feedback changed'):
            c.execute(self.run,self.s,PARAMS,approved)
        self.assertEqual(sum(j[4]==4 for j in self.s.robot.jobs),1)
        self.assertEqual(self.s.envelope,c.ORIGINAL)

    def test_approved_endpoint_edit_blocks_before_dispatch(self):
        approved=c.plan(self.s,PARAMS,self.g['id']);approved=deepcopy(approved)
        approved['binding']['points'][-1]['X']+=1
        with self.assertRaises(TransferError):c.execute(self.run,self.s,PARAMS,approved)
        self.assertEqual(self.s.robot.jobs,[])


if __name__=='__main__':unittest.main()
