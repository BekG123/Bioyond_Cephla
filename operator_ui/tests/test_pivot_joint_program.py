from pathlib import Path
import unittest
from build_pivot_joint_program import candidate_lua
from test_trajectory_queue import Controller
from test_transfer import FakeService
from trajectory_queue import LuaTrajectory,locate,checksum
from autonomy import TransferError

class PivotProgramTests(unittest.TestCase):
    def test_candidate_preserves_mixed_speed_hamilton_queue(self):
        from test_short_side_hover_transfer import HoverTransferTests
        h=HoverTransferTests();h.setup_route()
        src=(Path(__file__).resolve().parents[1]/'lua/mod_Trajectory_segment_speeds.lua').read_text()
        h.s.robot=Controller(h.s,source=candidate_lua(src))
        result=h.execute()
        self.assertTrue(result['ok']);self.assertEqual(h.s.robot.barriers,1)
        self.assertEqual(h.s.robot.motion_kinds,[])
        self.assertEqual([c[1] for c in h.s.robot.calls],h.speeds)
    def test_old_queue_cannot_silently_run_linear_wrist(self):
        s=FakeService();s.robot=Controller(s)
        with self.assertRaises(TransferError):LuaTrajectory(s).require_joint_pivot()
        self.assertEqual(s.robot.calls,[])

    def test_rotation_progress_uses_angle(self):
        a=dict(X=300,Y=50,Z=300,Rz=90);b=dict(a,Rz=0)
        self.assertAlmostEqual(locate(dict(a,Rz=45),[a,b])[2],50)

    def test_lua_rejects_translated_joint_command(self):
        s=FakeService();s.pose=dict(X=300,Y=50,Z=300,Rz=90)
        src=(Path(__file__).resolve().parents[1]/'lua/mod_Trajectory_segment_speeds.lua').read_text()
        s.robot=Controller(s,source=candidate_lua(src));q=LuaTrajectory(s);q.require_joint_pivot()
        point=dict(s.pose,X=301,Rz=0)
        header=[1,137,-1]+[s.pose[k] for k in ('X','Y','Z','Rz')]+[s.q[k] for k in ('J1','J2','J3','J4')]
        q._job(10,123,dict(enumerate(header)))
        q._job(2,123,dict(enumerate([point[k] for k in ('X','Y','Z','Rz')])),count=1)
        with self.assertRaises(TransferError):q._job(3,123,offset=checksum([point]))
        self.assertEqual(s.robot.calls,[])
