"""Real IK, fake controller: reseat/release failures must inhibit later motion."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pickup_holder import PickupHolder
from sequences import Runner
from test_staged_lift_trial import Service


class HolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.s=Service(); self.s.e1=3.9
        self.cfg=json.loads((Path(__file__).resolve().parents[1]/'robot_params.json').read_bytes())
        self.r=Runner(); token=object(); self.r.reserve(token,threading.Event()); self.r.claim(token)
        home=SimpleNamespace(get_service=lambda:self.s,get_runner=lambda:self.r,
                             params=lambda:self.cfg,require_home_queue=lambda x:None)
        self.t=PickupHolder(home,Path(self.tmp.name)/'receipts')
        self.t.configuration_ready=lambda:None
        self.grip=Path(self.tmp.name)/'grip.json'
        self.grip.write_text(json.dumps(dict(ok=True,target_e1_mm=3.9,at=time.time(),pose_mm=self.s.pose_mm())))
        self.result=dict(ok=True,target_e1_mm=3.9,executor='staged_reference_position',record=str(self.grip))
        self.moves=[]; self.openings=[]; self.fail_z=None; self.fail_open=False; self.open_short=False
        test=self
        class Queue:
            def __init__(self,s): self.s=s
            def capability(self): return dict(available=True,max_speed_mm_s=137)
            def execute(self,run,start,joints,points,cfg,speed,progress,**kwargs):
                test.moves.append((deepcopy(points),speed))
                if test.fail_z == points[-1]['Z']: return dict(ok=False)
                self.s.service.pose=dict(points[-1]); progress('motion',100,100)
                return dict(ok=True)
        def open_jaws(e1,speed):
            self.openings.append((e1,speed))
            if self.fail_open: return dict(ok=False,error='uncertain release')
            self.s.e1=7 if self.open_short else e1
            return dict(ok=True)
        self.s.move_gripper=open_jaws
        for name,value in [('LuaTrajectory',Queue),('verify_e2',lambda *a,**k:None)]:
            p=patch('pickup_holder.'+name,value); p.start(); self.addCleanup(p.stop)

    def step(self, method):
        getattr(self.t,method)(self.result)
        self.r._thread.join(3); self.assertFalse(self.r.active)
        self.result=self.r.result
        return self.result

    def test_finish_seated_open_and_thirty_mm_up_without_home(self):
        for method in ('start_lift','start_reseat','start_release','start_clearance'):
            self.assertTrue(self.step(method)['ok'])
        self.assertEqual([p[0][0]['Z'] for p in self.moves],[78.718,73.718,103.718])
        self.assertEqual([p[1] for p in self.moves],[5,5,137])
        self.assertEqual(self.openings,[(28,5)])
        self.assertEqual(self.s.e1,28)
        self.assertEqual(self.result['payload'],'empty')
        self.assertTrue(all(p[0][0]['X']==312.575 and p[0][0]['Rz']==89.865 for p in self.moves))

    def test_failed_lift_blocks_reseat(self):
        self.fail_z=78.718
        self.assertFalse(self.step('start_lift')['ok'])
        with self.assertRaises(Exception): self.step('start_reseat')
        self.assertEqual(len(self.moves),1); self.assertEqual(self.openings,[])

    def test_failed_reseat_blocks_opening(self):
        self.step('start_lift'); self.fail_z=73.718
        self.assertFalse(self.step('start_reseat')['ok'])
        with self.assertRaises(Exception): self.step('start_release')
        self.assertEqual(self.openings,[])

    def test_failed_opening_blocks_fast_ascent(self):
        self.step('start_lift'); self.step('start_reseat'); self.fail_open=True
        self.assertFalse(self.step('start_release')['ok'])
        with self.assertRaises(Exception): self.step('start_clearance')
        self.assertEqual(len(self.moves),2)

    def test_open_ack_without_actual_opening_blocks_ascent(self):
        self.step('start_lift'); self.step('start_reseat'); self.open_short=True
        self.assertFalse(self.step('start_release')['ok'])
        with self.assertRaises(Exception): self.step('start_clearance')
        self.assertEqual(len(self.moves),2)

    def test_moved_pose_after_lift_blocks_lowering(self):
        self.step('start_lift'); self.s.pose['X']+=1
        with self.assertRaises(Exception): self.step('start_reseat')
        self.assertEqual(len(self.moves),1)

    def test_expired_lift_receipt_blocks_lowering(self):
        self.step('start_lift'); self.t.receipt['at']-=31
        with self.assertRaises(Exception): self.step('start_reseat')
        self.assertEqual(len(self.moves),1)

    def test_full_corridor_checked_before_first_lift(self):
        self.s.envelope['Z'][1]=100
        with self.assertRaises(Exception): self.step('start_lift')
        self.assertEqual(self.moves,[])

    def test_missing_reference_is_presented_as_readiness_blocker(self):
        from autonomy import TransferError
        from researcher_teaching import TeachingError
        from classic_pickup import ClassicPickup
        del self.t.configuration_ready
        with patch('plate48_workflow.reference',side_effect=TransferError('Accepted grip binding missing')):
            with self.assertRaisesRegex(TeachingError,'Accepted grip binding missing'):
                self.t.configuration_ready()
            idle=SimpleNamespace(active=False,reserved=False)
            pickup=ClassicPickup(None,None,None,None,lambda:self.s,lambda:idle,self.t)
            # public must return a blocker, not crash the status endpoint.
            state=pickup.public()
            self.assertFalse(state['can_start'])
            self.assertEqual(state['blocker'],'Accepted grip binding missing')


if __name__=='__main__': unittest.main()
