"""Exercise real Lua serialization with fake hardware; never connects to an arm."""
import json
import math
import unittest
from copy import deepcopy
from pathlib import Path
from autonomy import TransferError,wrap
from hamilton_transit_blend import BlendedTransitTrajectory,ROUNDED_ZONES,blend_checksum
from trajectory_queue import LuaTrajectory,KEYS,locate
import test_hamilton_opposite_wrist as fixtures
from cellvis24_squid_route import geometry,PLAN,validate_route,check_route
from cellvis24_hamilton_continuation import steps


class RoundedAndSquidTests(unittest.TestCase):
    def test_both_directions_actual_lua_one_barrier_pinned_zones(self):
        for direction in ('forward','reverse'):
            with self.subTest(direction=direction):
                h,s,p,_=fixtures.OppositeWristTests().setup_route()
                r=p['routes'][direction];s.pose=deepcopy(r['start']);s.q=deepcopy(r['start_joints'])
                if direction=='reverse':s.pose['Rz']=wrap(s.pose['Rz'])
                result=BlendedTransitTrajectory(s).execute(h.run,s.pose,s.q,r['points'],p['config'],137,lambda *a:None,
                    reviewed=True,hamilton_short_side='cellvis24_opposite_'+direction,
                    segment_speeds=r['segment_speeds'],transit_blend=True)
                self.assertTrue(result['ok']);self.assertEqual(s.robot.barriers,1)
                self.assertEqual([v[2] for v in s.robot.calls],list(ROUNDED_ZONES[direction]))
                self.assertEqual([v[1] for v in s.robot.calls],r['segment_speeds'])
                self.assertEqual([v[4] for v in s.robot.jobs],[19,6,20,21,21,3,4])
                self.assertEqual(s.grips,[])
        self.assertTrue(steps('return_home')[0]['flags']['transit_blend'])

    def test_new_lua_rejects_pinned_packet_tampering_before_motion(self):
        for direction in ('forward','reverse'):
            for case in ('zone','speed','yaw','height','checksum','start'):
                with self.subTest(direction=direction,case=case):
                    h,s,p,_=fixtures.OppositeWristTests().setup_route();r=p['routes'][direction]
                    s.pose=deepcopy(r['start']);s.q=deepcopy(r['start_joints']);q=LuaTrajectory(s)
                    points=deepcopy(r['points']);speeds=list(r['segment_speeds']);zones=list(ROUNDED_ZONES[direction])
                    if case=='zone':zones[1]=5 if zones[1]!=5 else 1
                    if case=='speed':speeds[0 if direction=='reverse' else -1]=137
                    if case=='yaw':points[2]['Rz']-=360
                    if case=='height':points[2]['Z']+=1
                    header=[6,137,-1]+[s.pose[k] for k in KEYS]+[s.q[k] for k in ('J1','J2','J3','J4')]
                    if case=='start':header[3]+=1
                    q._job(20,123,dict(enumerate(header)))
                    for offset in (0,3):
                        flat=[]
                        for i in range(offset,offset+3):flat.extend([points[i][k] for k in KEYS]+[speeds[i],zones[i]])
                        q._job(21,123,dict(enumerate(flat)),offset,3)
                    with self.assertRaises(TransferError):
                        q._job(3,123,offset=blend_checksum(points,speeds,zones)+(1 if case=='checksum' else 0))
                    self.assertEqual(s.robot.calls,[])

    def test_selected_geometric_model_fits_unchanged_corridor_and_height_monitor(self):
        _,s,p,_=fixtures.OppositeWristTests().setup_route()
        candidate=Path(__file__).resolve().parents[2]/'work/hamilton_smoothing_investigation/selected_z82_candidate.json'
        curve=json.loads(candidate.read_bytes())['candidate']['points']
        r=p['routes']['forward'];path=[r['start']]+r['points']
        executor=BlendedTransitTrajectory(s);executor.rounded=True
        for point in curve:
            xyz,yaw,_=locate(point,path)
            self.assertLessEqual(xyz,2);self.assertLessEqual(yaw,2)
            executor.check_motion_feedback(point)
        with self.assertRaisesRegex(TransferError,'above Z82'):
            executor.check_motion_feedback(dict(X=346,Y=-99,Z=83,Rz=247))
        with self.assertRaises(TransferError):
            executor.check_motion_feedback(dict(X=346,Y=-99,Z=83,Rz=-113))

    def test_squid_same_geometry_only_five_mm_slow_departure_one_queue(self):
        g=geometry();old=json.loads(PLAN.read_bytes())
        self.assertEqual(g['points'],old['points']);self.assertEqual(g['speeds'],[137,137,137,5])
        self.assertEqual(g['reverse'][1:],old['reverse'])
        self.assertEqual(g['reverse'][0],dict(old['points'][-1],Z=round(old['points'][-1]['Z']+5,2)))
        self.assertEqual(g['reverse_speeds'],[5,137,137,137,137])
        h,s,_,_=fixtures.OppositeWristTests().setup_route()
        s.pose=deepcopy(g['points'][-1]);s.q=deepcopy(g['end_joints']);s.cfg=g['cfg'];s.envelope=g['envelope']
        expected=check_route(s.pose,g['reverse'],s.q,g['cfg'],g['envelope'])
        result=LuaTrajectory(s).execute(h.run,s.pose,s.q,g['reverse'],g['cfg'],137,lambda *a:None,
            reviewed=True,squid_queue='cellvis24_home_holder',segment_speeds=g['reverse_speeds'])
        self.assertTrue(result['ok']);self.assertEqual(s.robot.barriers,1)
        self.assertEqual([v[1] for v in s.robot.calls],[5,137,137,137,137]);self.assertEqual(s.grips,[])
        self.assertAlmostEqual(s.q['J4'],expected['J4'],places=4)
        bad=deepcopy(g['reverse']);bad[0]['X']+=.1
        with self.assertRaises(TransferError):validate_route(g['points'][-1],bad)


if __name__=='__main__':unittest.main()
