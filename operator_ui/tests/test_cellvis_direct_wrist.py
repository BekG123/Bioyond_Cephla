import json,unittest,zipfile
from copy import deepcopy
from build_mixed_wrist_program import SOURCE,candidate_lua
from cellvis24_direct_rack import reference,MixedWristTrajectory,mixed_checksum,PROFILES
from cellvis24_rack_route import reference as baseline
from cellvis24_workflow import compile_steps
from trajectory_queue import LuaTrajectory
from autonomy import TransferError
from test_short_side_hover_transfer import HoverTransferTests
from test_trajectory_queue import Controller
from run_cellvis24_scanner_hamilton import parse_args

class DirectWristTests(unittest.TestCase):
    def setup_route(self,direction='forward',new=True):
        helper=HoverTransferTests();helper.setup_route();s=helper.s
        p=reference();r=p['routes'][direction]
        with zipfile.ZipFile(SOURCE) as z:src=z.read('main/mod_Trajectory.lua').decode('utf-8-sig')
        s.pose=deepcopy(r['start']);s.q=deepcopy(r['start_joints']);s.cfg=p['config']
        s.envelope={k:(v['min'],v['max']) for k,v in p['global_envelope'].items() if k!='enabled'}
        s.robot=Controller(s,source=candidate_lua(src) if new else src)
        return helper,s,p,r

    def test_one_mixed_queue_both_directions_with_slow_contact(self):
        for direction,profile in zip(('forward','reverse'),PROFILES):
            h,s,p,r=self.setup_route(direction)
            result=MixedWristTrajectory(s).execute(h.run,s.pose,s.q,r['points'],p['config'],137,lambda *a:None,
                reviewed=True,hamilton_short_side=profile,segment_speeds=r['segment_speeds'])
            self.assertTrue(result['ok']);self.assertEqual(s.robot.barriers,1)
            self.assertEqual(s.robot.motion_kinds,['MoveJ','MoveJ'])
            self.assertEqual([call[1] for call in s.robot.calls],r['segment_speeds'])
            self.assertEqual(result['segment_kinds'],r['kinds'])
            self.assertEqual(s.grips,[])

    def test_old_program_and_plain_executor_refuse_candidate_before_motion(self):
        h,s,p,r=self.setup_route(new=False)
        for executor in (MixedWristTrajectory,LuaTrajectory):
            with self.assertRaises(TransferError):executor(s).execute(h.run,s.pose,s.q,r['points'],p['config'],137,lambda *a:None,
                reviewed=True,hamilton_short_side=PROFILES[0],segment_speeds=r['segment_speeds'])
        self.assertFalse(s.robot.calls)

    def test_lua_rejects_translating_joint_move_even_with_valid_checksum(self):
        h,s,p,r=self.setup_route();q=LuaTrajectory(s);points=deepcopy(r['points']);kinds=list(r['kinds'])
        kinds[3]='J'  # Try converting the diagonal crossing into a joint move.
        header=[len(points),137,-1]+[s.pose[k] for k in ('X','Y','Z','Rz')]+[s.q[k] for k in ('J1','J2','J3','J4')]
        q._job(12,123,dict(enumerate(header)))
        for offset in range(0,len(points),3):
            flat=[]
            for i,point in enumerate(points[offset:offset+3],offset):
                flat.extend([point[k] for k in ('X','Y','Z','Rz')]+[r['segment_speeds'][i],int(kinds[i]=='J')])
            q._job(14,123,dict(enumerate(flat)),offset,3)
        with self.assertRaises(TransferError):q._job(3,123,offset=mixed_checksum(points,r['segment_speeds'],kinds))
        self.assertFalse(s.robot.calls)

    def test_legacy_route_stays_linear_on_new_program(self):
        h,s,p,r=self.setup_route();old=baseline();r=old['routes']['forward']
        s.pose=deepcopy(r['start']);s.q=deepcopy(r['start_joints'])
        result=LuaTrajectory(s).execute(h.run,s.pose,s.q,r['points'],p['config'],137,lambda *a:None,
            reviewed=True,hamilton_short_side='cellvis24_rack_forward',segment_speeds=r['segment_speeds'])
        self.assertTrue(result['ok']);self.assertEqual(s.robot.motion_kinds,[])
        self.assertEqual(len(s.robot.calls),7);self.assertEqual(s.robot.barriers,1)

    def test_explicit_candidate_selection_and_clearance_flag(self):
        default=compile_steps(['hamilton'],1,held_hamilton_roundtrip=True)
        candidate=compile_steps(['hamilton'],1,held_hamilton_roundtrip=True,direct_hamilton=True)
        self.assertEqual(next(s for s in default if s['label']=='Travel forward')['flags']['hamilton_short_side'],'cellvis24_rack_forward')
        self.assertEqual(next(s for s in candidate if s['label']=='Travel forward')['flags']['hamilton_short_side'],PROFILES[0])
        with self.assertRaises(TransferError):compile_steps(['hamilton'],1,direct_hamilton=True)
        with self.assertRaises(SystemExit):parse_args(['--from-home','--direct-hamilton','--execute'])
        self.assertTrue(parse_args(['--from-home','--direct-hamilton','--execute','--direct-clearance-confirmed']).direct_hamilton)
        p=reference();self.assertLess(p['comparison']['candidate_xyz_mm'],.62*p['comparison']['baseline_xyz_mm'])
        self.assertFalse(p['execution_enabled'])

if __name__=='__main__':unittest.main()
