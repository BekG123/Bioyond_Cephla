"""Real route/IK validation with simulated actuators, never live hardware."""
import json
from pathlib import Path
import time
from unittest import TestCase,main
from unittest.mock import patch
import test_home_squid_transfer as fixtures
import home_squid_handling as handling


class HandlingTests(TestCase):
    def setUp(self):
        self.base=fixtures.HomeSquidTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.f=self.base.f;self.g=self.base.g
        p=patch.object(handling,'LuaTrajectory',fixtures.hs.LuaTrajectory);p.start();self.addCleanup(p.stop)
        self.forward=fixtures.hs.execute(self.f.run,self.f.svc,self.g['cfg'],self.base.planned(),self.base.gripper)
        self.moves_after_forward=len(self.f.moves)

    def phase(self,phase,source):
        p=handling.plan(self.f.svc,self.g['cfg'],source,phase)
        return handling.execute(self.f.run,self.f.svc,self.g['cfg'],p)

    def test_release_empty_return_retrieve_and_home_release(self):
        r=self.phase('release_squid',self.forward['record'])
        self.assertEqual(self.f.jaws,[7])
        self.assertEqual(len(self.f.moves),self.moves_after_forward)
        r=self.phase('empty_return',r['record'])
        self.assertEqual(self.f.state['pose_mm'],self.g['clearance'])
        self.assertEqual(self.f.jaws,[7])
        r=self.phase('retrieve',r['record'])
        self.assertEqual(self.f.jaws,[7,4.9,3.9])
        self.assertEqual(self.f.state['pose_mm'],fixtures.hs.seating_plan(self.g['seat'])['pose'])
        self.assertEqual(self.f.moves[-1],[fixtures.hs.seating_plan(self.g['seat'])['pose']])
        p=fixtures.hs.plan_return(self.f.svc,self.g['cfg'],r['record'],'release_home')
        r=fixtures.hs.execute_return(self.f.run,self.f.svc,self.g['cfg'],p)
        self.assertEqual(self.f.jaws,[7,4.9,3.9,28])
        self.assertEqual(self.f.state['pose_mm'],self.g['clearance'])

    def test_failed_release_cannot_retreat_or_repeat(self):
        self.f.svc.move_gripper.side_effect=lambda *args:{'ok':False}
        with self.assertRaisesRegex(handling.TransferError,'Uncertain'):
            self.phase('release_squid',self.forward['record'])
        self.assertEqual(len(self.f.moves),self.moves_after_forward)
        with self.assertRaisesRegex(handling.TransferError,'already used'):
            self.phase('release_squid',self.forward['record'])

    def test_failed_pickup_never_starts_loaded_return(self):
        r=self.phase('release_squid',self.forward['record'])
        r=self.phase('empty_return',r['record'])
        self.f.svc.move_gripper.side_effect=lambda *args:{'ok':True,'recovered':'uncertain'}
        with self.assertRaisesRegex(handling.TransferError,'Uncertain'):
            self.phase('retrieve',r['record'])
        self.assertEqual(self.f.state['pose_mm'],self.g['points'][-1])

    def test_geometry_changed_or_expired_receipt_refused(self):
        p=Path(self.forward['record']);data=json.loads(p.read_bytes())
        data['plan']['geometry']['seat']['Z']-=1;p.write_text(json.dumps(data))
        with self.assertRaisesRegex(handling.TransferError,'geometry'):
            self.phase('release_squid',p)
        data['finished_at']=time.time()-1801;p.write_text(json.dumps(data))
        with self.assertRaisesRegex(handling.TransferError,'Fresh'):
            self.phase('release_squid',p)


if __name__=='__main__':main()
