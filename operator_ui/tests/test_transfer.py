"""Offline transfer tests. Fake hardware only; never connect to the cell."""
import copy
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

UI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UI))
from autonomy import (TransferError, GuardedService, check_path, ik,
                      validate_request, seq_transfer, wrap)
from sequences import Runner

PARAMS = json.loads((UI / "robot_params.json").read_text())
ENVELOPE = {"X": (100, 500), "Y": (-350, 350), "Z": (30, 420)}
BODY = dict(marker_id=3, destination=dict(x=340, y=30, z=100, rz=5),
            travel_z=300, grip_z_offset_mm=9, confirm=True, cell_clear=True)


class FakeService:
    def __init__(self):
        self.envelope_enabled = True
        self.envelope = copy.deepcopy(ENVELOPE)
        self.pose = dict(X=326., Y=0., Z=300., Rz=0.)
        self.q = dict(J1=300, J2=60., J3=60., J4=-120.)
        self.moves, self.grips = [], []
        self.e1, self.torque = 0., 150.
        self.motion_failure = None
        self.refusal = None
        self.stall = True
        self.span_position = 10.
    def _preflight(self):
        return self.refusal
    def pose_mm(self):
        return dict(self.pose)
    def joints(self):
        return dict(self.q)
    def move_cartesian(self, x, y, z, rz, speed=10, interpolation="linear"):
        self.moves.append((x,y,z,rz))
        end = dict(X=x,Y=y,Z=z,Rz=rz)
        if self.motion_failure == "stale":
            return {"ok": True}
        self.q = check_path(self.pose, end, self.q, PARAMS, self.envelope if self.envelope_enabled else None)
        self.pose = end
        return {"ok": True, **({"recovered": "drop"} if self.motion_failure == "recovered" else {})}
    def move_gripper(self, target):
        self.grips.append(target)
        self.e1 = self.span_position if target <= 9.5 else target
        self.torque = -187 if target <= 9.5 else 150
        err = self.e1-target if self.stall else 0
        return {"ok": True, "gripper": {"e1_position":self.e1,"e1_torque":self.torque,"position_error":err,"grip_detected":err>0.15 and self.torque < -100}}
    def torque_report(self):
        return {"ok":True,"telemetry_live":True,"joints":dict(J1=350,J2=1,J3=1,J4=1),"e1_position":self.e1,"e1_torque":self.torque}


class FakeVision:
    def __init__(self):
        self.W=SimpleNamespace(CAL={"marker_offsets":{"3":dict(dx_mm=0,dy_mm=0,rel_yaw_deg=0,width_mm=70,length_mm=105)}})
        self.result=dict(detected=True,id=3,H_mm=220,marker_world=[340.,20.,91.],marker_yaw_deg=0,
                         grab_candidates=[dict(tcp=[330.,20.],rz=0.,clampable=True,span_mm=70.)])
        self.n=0
        self.jitter=False
    def model_stamps(self):return ("same","same")
    def view_center_world(self,*args):return (340.,20.)
    def solve(self,*args,marker_id=None):
        self.n+=1
        out=copy.deepcopy(self.result)
        if self.jitter:out["marker_world"][2]+=self.n*2
        return out


CAM=SimpleNamespace(snap=lambda:None,save=lambda *args,**kwargs:"fake.png")


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.svc,self.vision,self.run=FakeService(),FakeVision(),Runner()
        self.run.state="running"
    def execute(self, preview=False):
        return seq_transfer(self.run,self.svc,CAM,self.vision,validate_request(BODY,preview),PARAMS)
    def test_valid_cycle(self):
        result=self.execute()
        self.assertTrue(result["ok"],result)
        self.assertFalse(result["holding"])
        self.assertEqual(self.svc.pose,dict(X=340.,Y=30.,Z=300.,Rz=5.))
        self.assertEqual(self.svc.grips[-1],28)
    def test_preview_has_no_motion(self):
        result=self.execute(True)
        self.assertTrue(result["ok"],result)
        self.assertEqual(len(result["plan"]),9)
        self.assertEqual(self.svc.moves+self.svc.grips,[])
    def test_validation(self):
        for value in (None,"",True,float("nan"),float("inf")):
            body=copy.deepcopy(BODY);body["destination"]["x"]=value
            with self.assertRaises(TransferError):validate_request(body)
        for update in (dict(confirm=False),dict(cell_clear="true"),dict(marker_id=3.5),dict(marker_id=50),dict(travel_z=250),dict(grip_z_offset_mm=500)):
            with self.assertRaises(TransferError):validate_request({**BODY,**update})
        self.assertTrue(validate_request({**BODY,"confirm":False},True)["preview"])
    def test_missing_and_duplicate_markers_fail(self):
        for mid in (None,4):
            self.vision.result.update(detected=mid is not None,id=mid)
            self.assertFalse(self.execute()["ok"])
            self.assertEqual(self.svc.moves+self.svc.grips,[])
    def test_bad_distance_and_scatter(self):
        self.vision.result["H_mm"]=260
        self.assertFalse(self.execute()["ok"])
        self.vision.result["H_mm"]=220;self.vision.jitter=True
        self.assertFalse(self.execute()["ok"])
        self.assertEqual(self.svc.moves+self.svc.grips,[])
    def test_missing_calibration(self):
        del self.vision.W.CAL["marker_offsets"]["3"]["width_mm"]
        self.assertFalse(self.execute()["ok"])
        self.assertEqual(self.svc.moves+self.svc.grips,[])
    def test_calibration_mismatch(self):
        self.vision.model_stamps=lambda:("new","old")
        self.assertFalse(self.execute()["ok"])
        self.assertEqual(self.svc.moves+self.svc.grips,[])
    def test_span_gate(self):
        self.vision.result["grab_candidates"][0]["clampable"]=False
        self.assertFalse(self.execute()["ok"])
        self.assertEqual(self.svc.moves+self.svc.grips,[])
    def test_envelope_required(self):
        self.svc.envelope_enabled=False
        self.assertFalse(self.execute()["ok"])
        self.assertEqual(self.svc.moves+self.svc.grips,[])
    def test_missing_joints(self):
        self.svc.joints=lambda:{}
        self.assertFalse(self.execute()["ok"])
        self.assertEqual(self.svc.moves+self.svc.grips,[])
    def test_model_mismatch(self):
        self.svc.q["J3"]=20
        self.assertFalse(self.execute()["ok"])
    def test_wrist_headroom(self):
        self.svc.q["J4"]=219
        result=self.execute()
        self.assertFalse(result["ok"])
        self.assertIn("J4",result["error"])
        self.assertEqual(self.svc.moves+self.svc.grips,[])
    def test_both_ik_branches(self):
        for ref in ((60,60),(-60,-60)):
            q=ik(326,0,ref,PARAMS)
            self.assertAlmostEqual(q[0],ref[0]);self.assertAlmostEqual(q[1],ref[1])
    def test_midpath_fold_refused(self):
        # Both endpoints have reach 200, but the segment crosses the base.
        a=dict(X=326,Y=0,Z=300,Rz=0)
        b=dict(X=-74,Y=0,Z=300,Rz=0)
        wide={**ENVELOPE,"X":(-100,500)}
        with self.assertRaises(TransferError):check_path(a,b,self.svc.q,PARAMS,wide)
    def test_stale_ack_stops_without_retry(self):
        self.svc.motion_failure="stale"
        result=self.execute()
        self.assertFalse(result["ok"])
        self.assertIn("arrival mismatch",result["error"])
        self.assertEqual(self.svc.grips,[])
    def test_reconnect_aborts(self):
        self.svc.motion_failure="recovered"
        self.assertFalse(self.execute()["ok"])
        self.assertEqual(len(self.svc.moves),1)
        self.assertEqual(self.svc.grips,[])
    def test_no_position_stall_no_lift(self):
        self.svc.stall=False
        result=self.execute()
        self.assertFalse(result["ok"])
        self.assertIn("both torque",result["error"])
        self.assertEqual(self.svc.pose["Z"],100)
    def test_wrong_gripped_span_no_lift(self):
        self.svc.span_position=20
        result=self.execute()
        self.assertFalse(result["ok"])
        self.assertIn("span",result["error"])
        self.assertEqual(self.svc.pose["Z"],100)
    def test_pick_contact_never_closes(self):
        with patch("sequences.seq_descend",return_value={"ok":True,"breach":True,"contact":False}):
            result=self.execute()
        self.assertFalse(result["ok"])
        self.assertEqual(self.svc.grips,[28])
    def test_place_contact_never_releases(self):
        import sequences
        original=sequences.seq_descend
        calls=[]
        def descend(*args):
            calls.append(1)
            return original(*args) if len(calls)==1 else dict(ok=True,breach=True,contact=True)
        with patch("sequences.seq_descend",side_effect=descend):result=self.execute()
        self.assertFalse(result["ok"])
        self.assertTrue(result["holding"])
        self.assertNotEqual(self.svc.grips[-1],28)
    def test_stop_before_start(self):
        self.run.request_stop()
        self.assertFalse(self.execute()["ok"])
        self.assertEqual(self.svc.moves+self.svc.grips,[])
    def test_initial_hold_refused(self):
        self.svc.torque=-187
        result=self.execute()
        self.assertFalse(result["ok"])
        self.assertIn("already hold",result["error"])
        self.assertEqual(self.svc.moves+self.svc.grips,[])
    def test_hold_loss_during_carry(self):
        original=self.svc.move_cartesian
        def moving(*args,**kwargs):
            was_holding=self.svc.torque < -100
            result=original(*args,**kwargs)
            if was_holding:self.svc.torque=150
            return result
        self.svc.move_cartesian=moving
        result=self.execute()
        self.assertFalse(result["ok"])
        self.assertTrue(result["holding"])
        self.assertNotEqual(self.svc.grips[-1],28)
        self.assertLess(self.svc.pose["Z"],300)
    def test_stop_bypasses_dispatch_lock(self):
        import app as console
        # If Stop attempted to acquire this lock, the assertion would fail
        # immediately instead of hanging the test suite.
        class MustNotLock:
            def acquire(self):raise AssertionError("Stop queued behind motion")
        with patch.object(console,"_dispatch_lock",MustNotLock()):
            self.assertEqual(console.app.test_client().post('/seq/stop',json={}).status_code,200)
    def test_real_solver_id_selection(self):
        import aruco_world
        marker=dict(id=3,cam_xyz_mm=[0,0,220],cam_yaw_deg=0,center_px=[10,10],side_px=100)
        other={**marker,"id":4}
        with patch.object(aruco_world.A,"detect",return_value=[other,marker]):
            self.assertEqual(aruco_world.solve("fake",326,0,300,0,marker_id=3)["id"],3)
        with patch.object(aruco_world.A,"detect",return_value=[marker,marker]):
            self.assertFalse(aruco_world.solve("fake",326,0,300,0,marker_id=3)["detected"])
    def test_routes_validate_before_runner(self):
        import app as console
        with patch.object(console.runner,"start") as start, patch.object(console.draggo, 'latched', False):
            client=console.app.test_client()
            self.assertEqual(client.post('/seq/transfer',json={}).status_code,400)
            start.assert_not_called()
    def test_active_sequence_owns_mutations(self):
        import app as console
        fake=SimpleNamespace(active=True,request_stop=lambda:{"ok":True},snapshot=lambda:{})
        with patch.object(console,"runner",fake):
            client=console.app.test_client()
            for path in ('/move','/disconnect','/enable','/envelope/enable','/target','/camera/release','/zcal','/seq/transfer'):
                self.assertEqual(client.post(path,json={}).status_code,409,path)
            self.assertEqual(client.post('/seq/stop',json={}).status_code,200)


if __name__ == '__main__':unittest.main(verbosity=2)
