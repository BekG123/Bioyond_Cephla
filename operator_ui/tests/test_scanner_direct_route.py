import json
import time
import unittest
from unittest.mock import patch

import test_scanner_plate_workflow as fixtures
from test_trajectory_queue import PARAMS
from autonomy import TransferError, ik, wrap
from scope_compact137 import HoldingService
from trajectory_queue import LuaTrajectory
import scanner_empty_route as scanner
import scanner_plate_workflow as loaded
import scanner_direct_route as direct


class DirectScannerTests(unittest.TestCase):
    def setUp(self):
        fixtures.LoadedScannerTests.setUp(self)
        self.g=direct.geometry()
        start=self.g['start'];q=self.s.q
        q2,q3=ik(start['X'],start['Y'],(q['J2'],q['J3']),PARAMS)
        self.s.q=dict(J1=q['J1']+start['Z']-self.s.pose['Z'],J2=q2,J3=q3,
            J4=q['J4']+wrap(start['Rz']-self.s.pose['Rz'])-(q2+q3-q['J2']-q['J3']))
        self.s.pose=dict(start)
        self.lift=self.folder/'proof.json'
        self.lift_record=dict(status='completed',action='Lift',speed=5,finished_at=time.time(),
            context=dict(cfg=PARAMS,grip_record=str(self.grip),grip_sha256=loaded.digest(self.grip)),
            final=dict(pose_mm=dict(start)))
        self.lift.write_text(json.dumps(self.lift_record))
        self.lift_result=dict(ok=True,record=str(self.lift))

    def execute(self):
        with patch('projected_pickup.load',return_value=({},self.g['profile_sha256'])), \
             patch.object(direct,'geometry',return_value=self.g):
            return loaded.execute_loaded(self.run,self.s,PARAMS,self.result,self.folder,
                self.g['profile_sha256'],True,self.lift_result)

    def test_three_moves_one_queue_no_idle_and_no_release(self):
        result=self.execute()
        self.assertTrue(result['ok'])
        self.assertEqual(len(self.s.robot.calls),3)
        self.assertEqual(self.s.robot.barriers,1)
        self.assertEqual([j[4] for j in self.s.robot.jobs],[6,1,2,3,4])
        for call,expected in zip(self.s.robot.calls,self.g['points']):
            self.assertEqual(call[1],137)
            actual=dict(zip(scanner.KEYS,call[0][:3]+(call[0][5],)))
            for k in scanner.KEYS:self.assertAlmostEqual(actual[k],expected[k],places=4)
            self.assertNotEqual(actual['X'],scanner.START['X'])
        self.assertEqual(self.s.grips,[])
        self.assertEqual(self.s.envelope,scanner.ORIGINAL)
        receipt=json.loads((self.folder/'loaded_scanner.json').read_text())
        self.assertTrue(receipt['result']['direct_from_home'])
        self.assertFalse(receipt['result']['idle_travel'])

    def test_stale_or_unbound_proof_lift_refuses_before_motion(self):
        for change in ({'finished_at':time.time()-61},{'context':dict(cfg=PARAMS,grip_record=str(self.grip),grip_sha256='wrong')}):
            self.lift.write_text(json.dumps(dict(self.lift_record,**change)))
            with self.assertRaises(TransferError):self.execute()
        self.assertEqual(self.s.robot.jobs,[])

    def test_edited_clearance_or_idle_waypoint_refused(self):
        self.s.envelope=dict(scanner.TRIAL)
        holding=HoldingService(self.s,3.9,{k:list(v) for k,v in scanner.TRIAL.items()})
        for points in ([dict(self.g['points'][0],Z=290)]+self.g['points'][1:],
                       self.g['points'][:1]+[scanner.START]+self.g['points'][1:]):
            with self.assertRaises(TransferError):
                LuaTrajectory(holding).execute(self.run,self.s.pose,self.s.q,points,PARAMS,137,
                    lambda *a:None,reviewed=True,scanner_loaded='direct')
        self.assertEqual(self.s.robot.jobs,[])

    def test_transport_only_performs_proof_lift(self):
        self.assertEqual([s[0] for s in loaded.ScannerProofLift.steps],['Lift'])
        self.assertIsNone(loaded.ScannerProofLift.completion_action)


if __name__=='__main__':unittest.main()
