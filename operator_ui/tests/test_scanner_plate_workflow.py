import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import test_scanner_empty_route as fixtures
from test_trajectory_queue import PARAMS
from autonomy import TransferError
from trajectory_queue import LuaTrajectory
from scope_compact137 import HoldingService
import scanner_empty_route as scanner
import scanner_plate_workflow as loaded


class LoadedScannerTests(unittest.TestCase):
    def setUp(self):
        fixtures.ScannerTests.setUp(self)
        self.s.e1=3.9
        self.s.external_axes=lambda:{'E1':self.s.e1}
        old_status=self.s.status
        self.s.status=lambda:dict(old_status(),external_axes=self.s.external_axes())
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.grip=self.folder/'grip.json'
        self.grip.write_text(json.dumps(dict(ok=True,target_e1_mm=3.9,at=time.time())))
        self.result=dict(ok=True,target_e1_mm=3.9,executor='staged_reference_position',record=str(self.grip))

    def execute(self):
        with patch('projected_pickup.load',return_value=({},'accepted-profile')):
            return loaded.execute_loaded(self.run,self.s,PARAMS,self.result,self.folder,'accepted-profile')

    def test_loaded_scanner_one_move_and_grip_preserved(self):
        result=self.execute()
        self.assertTrue(result['ok'])
        self.assertEqual(result['payload'],'48well_plate')
        self.assertEqual(len(self.s.robot.calls),1)
        self.assertEqual(self.s.robot.calls[0][1],137)
        self.assertEqual(self.s.robot.barriers,1)
        self.assertEqual(self.s.grips,[])
        self.assertEqual(self.s.envelope,scanner.ORIGINAL)
        record=json.loads(Path(result['record']).read_text())
        self.assertEqual(record['grip']['sha256'],loaded.digest(self.grip))
        self.assertEqual(record['status'],'completed')

    def test_stale_grip_or_wrong_jaw_blocks_before_writes(self):
        self.s.e1=4.355
        with self.assertRaises(TransferError):self.execute()
        self.s.e1=3.9
        self.grip.write_text(json.dumps(dict(ok=True,target_e1_mm=3.9,at=time.time()-601)))
        with self.assertRaises(TransferError):self.execute()
        self.assertEqual(self.s.robot.jobs,[])

    def test_unmonitored_or_mixed_loaded_profile_refused(self):
        self.s.envelope=dict(scanner.TRIAL)
        for options in ({'scanner_loaded':True},{'scanner_loaded':True,'scanner_empty':'continuous'}):
            with self.assertRaises(TransferError):
                LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,scanner.points(),PARAMS,137,
                    lambda *a:None,reviewed=True,**options)
        self.assertEqual(self.s.robot.jobs,[])

    def test_lost_grip_during_motion_stops_and_restores(self):
        self.s.robot.block_motion=True
        self.s.external_axes=lambda:{'E1':4.2 if self.s.robot.started.is_set() else 3.9}
        def stop(action):
            self.s.robot.program_state='stopped';self.s.robot.released.set();return dict(ok=True)
        self.s.program=stop
        with self.assertRaisesRegex(TransferError,'Gripper feedback changed'):self.execute()
        self.assertTrue(self.s.robot.released.is_set())
        self.assertEqual(sum(j[4]==4 for j in self.s.robot.jobs),1)
        self.assertEqual(self.s.envelope,scanner.ORIGINAL)
        self.assertEqual(json.loads((self.folder/'loaded_scanner.json').read_text())['status'],'stopped_or_uncertain')


if __name__=='__main__':unittest.main()
