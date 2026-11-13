import contextlib
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from autonomy import TransferError
from build_blended_transit_program import SOURCE,candidate_lua,build
from cellvis24_recorded_hamilton_route import reference,plan_path
from cellvis24_workflow import compile_steps
from hamilton_transit_blend import BlendedTransitTrajectory,ZONES,blend_checksum
from trajectory_queue import LuaTrajectory
from test_cellvis_direct_wrist import DirectWristTests
from test_trajectory_queue import Controller
import run_cellvis24_recorded_hamilton as cli


class TransitBlendTests(unittest.TestCase):
    def setup_route(self,new=True):
        h,s,_,_=DirectWristTests().setup_route()
        p=reference('smooth3');r=p['routes']['forward']
        s.pose=deepcopy(r['start']);s.q=deepcopy(r['start_joints'])
        with zipfile.ZipFile(SOURCE) as z:src=z.read('main/mod_Trajectory.lua').decode('utf-8-sig')
        s.robot=Controller(s,source=candidate_lua(src) if new else src)
        return h,s,p,r

    def execute(self,h,s,p,r,executor=BlendedTransitTrajectory):
        return executor(s).execute(h.run,s.pose,s.q,r['points'],p['config'],137,lambda *a:None,
            reviewed=True,hamilton_short_side='cellvis24_smoothed_forward',segment_speeds=r['segment_speeds'],
            **({'transit_blend':True} if executor is BlendedTransitTrajectory else {}))

    def test_real_lua_only_two_corners_blend_one_barrier(self):
        h,s,p,r=self.setup_route();result=self.execute(h,s,p,r)
        self.assertTrue(result['ok']);self.assertEqual(s.robot.barriers,1)
        self.assertEqual([c[2] for c in s.robot.calls],list(ZONES))
        self.assertEqual([c[1] for c in s.robot.calls],[137]*5+[5])
        self.assertEqual(s.robot.motion_kinds,[]);self.assertEqual(s.grips,[])
        self.assertEqual(result['segment_zones'],list(ZONES))
        # External axes are copied from starting feedback, not commanded open/closed.
        self.assertTrue(all(c[0][6:]==(3.4,-2,0,0,0,0) for c in s.robot.calls))

    def test_old_lua_rejected_without_motion(self):
        h,s,p,r=self.setup_route(False)
        with self.assertRaisesRegex(TransferError,'220112'):self.execute(h,s,p,r)
        self.assertEqual(s.robot.calls,[])

    def test_legacy_linear_queue_is_unchanged(self):
        h,s,p,r=self.setup_route();self.execute(h,s,p,r,LuaTrajectory)
        self.assertEqual([c[2] for c in s.robot.calls],[-1]*6)
        self.assertEqual(s.robot.barriers,1)

    def upload(self,s,r,points=None,zones=ZONES,speeds=None,bad_checksum=False):
        q=LuaTrajectory(s);points=points or r['points'];speeds=speeds or r['segment_speeds']
        header=[len(points),137,-1]+[s.pose[k] for k in ('X','Y','Z','Rz')]+[s.q[k] for k in ('J1','J2','J3','J4')]
        q._job(16,123,dict(enumerate(header)))
        for offset in range(0,len(points),3):
            flat=[]
            for i,p in enumerate(points[offset:offset+3],offset):
                flat.extend([p[k] for k in ('X','Y','Z','Rz')]+[speeds[i],zones[i]])
            q._job(17,123,dict(enumerate(flat)),offset,len(points[offset:offset+3]))
        q._job(3,123,offset=blend_checksum(points,speeds,zones)+(1 if bad_checksum else 0))

    def test_lua_rejects_final_blending_height_change_and_checksum_tamper(self):
        for case in ('final_zone','lift_zone','height','speed','checksum'):
            with self.subTest(case=case):
                h,s,p,r=self.setup_route();pts=deepcopy(r['points']);z=list(ZONES);speeds=list(r['segment_speeds'])
                if case=='final_zone':z[-1]=1
                if case=='lift_zone':z[0]=1
                if case=='height':pts[2]['Z']-=1
                if case=='speed':speeds[-1]=137
                with self.assertRaises(TransferError):self.upload(s,r,pts,z,speeds,case=='checksum')
                self.assertFalse(s.robot.calls)

    def test_builder_changes_only_trajectory_and_keeps_vendor_zip_format(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'candidate.bin';build(output=output)
            self.assertEqual(output.read_bytes()[:7],b'byrobot')
            with zipfile.ZipFile(SOURCE) as old,zipfile.ZipFile(output) as new:
                self.assertEqual(old.namelist(),new.namelist())
                self.assertEqual([n for n in old.namelist() if old.read(n)!=new.read(n)],['main/mod_Trajectory.lua'])

    def test_cli_selection_has_no_inspections_and_refuses_old_backend_first(self):
        args=cli.parse_args(['--full-calibration','--blend-transit','--execute','--path-clear'])
        self.assertTrue(args.smooth_transit);self.assertFalse(args.pause_for_inspection)
        with patch.object(cli,'api',return_value={'recorded_hamilton_delivery':True,'recorded_route_variants':{}}),patch.object(cli,'calibrate_to_scanner') as calibration:
            with self.assertRaisesRegex(RuntimeError,'Backend route differs'):
                cli.main(['--full-calibration','--blend-transit','--execute','--path-clear'])
            calibration.assert_not_called()
        steps=compile_steps(['hamilton'],1,recorded_hamilton_delivery=True,recorded_hamilton_variant='blend3')
        self.assertTrue(steps[-1]['flags']['transit_blend'])
        self.assertFalse(any(s.get('flags',{}).get('transit_blend') for s in steps[:-1]))

    def test_unpublished_capability_stops_before_full_calibration(self):
        digest=hashlib.sha256(plan_path('blend3').read_bytes()).hexdigest()
        def api(path,*args):
            if path.endswith('capabilities'):
                return dict(recorded_hamilton_delivery=True,recorded_route_variants={'blend3':digest})
            raise RuntimeError('Publish220112 before calibration')
        with patch.object(cli,'api',side_effect=api),patch.object(cli,'reconnect'),patch.object(cli,'calibrate_to_scanner') as calibration:
            with self.assertRaisesRegex(RuntimeError,'Publish220112'):
                cli.main(['--full-calibration','--blend-transit','--execute','--path-clear'])
            calibration.assert_not_called()

    def test_stop_still_prevents_dispatch(self):
        h,s,p,r=self.setup_route();h.run.stopped=lambda:True
        with self.assertRaises(TransferError):self.execute(h,s,p,r)
        self.assertFalse(s.robot.calls)


if __name__=='__main__':unittest.main()
