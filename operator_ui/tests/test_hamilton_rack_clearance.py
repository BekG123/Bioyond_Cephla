import unittest
from test_short_side_hover_transfer import HoverTransferTests
from hamilton_rack_clearance import PROFILES, PROFILES04, ORIGINAL_PROFILES, TURN05_PROFILES, route, profiles_for_start, original_profiles_for_start
from trajectory_queue import LuaTrajectory
from autonomy import TransferError
from hamilton_rack_clearance import Z77_PROFILES, FAST_PROFILES, z77_profiles_for_start


class RackQueueTests(unittest.TestCase):
    def setup_route(self,profile):
        helper=HoverTransferTests();helper.setup_route()
        self.s,self.run=helper.s,helper.run
        r,joints=route(profile);self.s.pose=dict(r['start']);self.s.q=dict(joints)
        self.points=[dict(p) for p in r['points']];self.speeds=list(r['segment_speeds']);self.profile=profile

    def execute(self):
        return LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,self.points,self.s.cfg,137 if self.profile in FAST_PROFILES else 40,
            lambda *a:None,reviewed=True,hamilton_short_side=self.profile,segment_speeds=self.speeds)

    def test_actual_lua_both_phases_no_axis_commands(self):
        for profile in PROFILES+PROFILES04+ORIGINAL_PROFILES+TURN05_PROFILES+Z77_PROFILES+FAST_PROFILES:
            self.setup_route(profile);self.assertTrue(self.execute()['ok'])
            self.assertEqual([c[1] for c in self.s.robot.calls],self.speeds)
            self.assertEqual(self.s.robot.barriers,1)
            self.assertEqual(self.s.grips,[])
            self.assertTrue(all(c[0][6:9]==(3.4,-2,0) for c in self.s.robot.calls))
            self.assertEqual(self.s.envelope['Z'],(70,400))

    def test_raising_under_rack_and_fast_seating_rejected(self):
        for profile in PROFILES:
            self.setup_route(profile)
            self.points[0 if profile==PROFILES[0] else 2]['Z']+=1
            with self.assertRaises(TransferError):self.execute()
            self.assertEqual(self.s.robot.jobs,[])
        self.setup_route(PROFILES[1]);self.speeds[-1]=40
        with self.assertRaises(TransferError):self.execute()
        self.assertEqual(self.s.robot.jobs,[])

    def test_geometry_respects_reviewed_headspace(self):
        r,_=route(PROFILES[0]);self.assertLessEqual(r['points'][0]['Z'],r['start']['Z'])
        self.assertEqual(r['points'][0]['Rz'],r['start']['Rz'])
        self.assertEqual([r['points'][0][k] for k in ('X','Y')],[289.97,62.63])
        r,_=route(PROFILES[1]);self.assertEqual([r['points'][i]['Z'] for i in (1,2,3)],[115.02]*3)

    def test_z67_crossing_and_no_initial_lift(self):
        r,_=route(PROFILES04[0]);self.assertLess(r['points'][0]['Z'],r['start']['Z'])
        r,_=route(PROFILES04[1]);self.assertEqual([r['points'][i]['Z'] for i in (2,3)],[67,67])
        self.assertEqual(r['points'][-1]['Z'],53.72)
        self.setup_route(PROFILES04[1]);self.points[3]['Z']=115.02
        with self.assertRaises(TransferError):self.execute()
        self.assertEqual(self.s.robot.jobs,[])

    def test_already_home_only_runs_hamilton_phase(self):
        home=route(PROFILES04[1])[0]['start']
        self.assertEqual(profiles_for_start(home),(PROFILES04[1],))
        self.assertEqual(profiles_for_start(dict(home,Z=home['Z']+1)),PROFILES04)

    def test_original_route_preserves_overhead_and_reverse(self):
        forward,_=route(ORIGINAL_PROFILES[1]);back,_=route(ORIGINAL_PROFILES[0])
        self.assertEqual(forward['points'][1]['Z'],139.93)
        self.assertEqual(forward['points'][2]['Z'],139.93)
        self.assertEqual([forward['start']]+forward['points'],list(reversed([back['start']]+back['points'])))
        self.assertEqual(original_profiles_for_start(forward['start']),(ORIGINAL_PROFILES[1],))
        self.assertEqual(original_profiles_for_start(back['start']),ORIGINAL_PROFILES)

    def test_corrected_turn_keeps_overhead_and_final_destination(self):
        r,_=route(TURN05_PROFILES[1]);old,_=route(ORIGINAL_PROFILES[1])
        self.assertEqual(r['points'][0],dict(X=257.28,Y=-54.42,Z=116.58,Rz=19.49))
        self.assertEqual(r['points'][1],dict(X=257.28,Y=-54.42,Z=139.93,Rz=-93.02))
        self.assertEqual(r['points'][2:],old['points'][2:])
        back,_=route(TURN05_PROFILES[0])
        self.assertEqual([r['start']]+r['points'],list(reversed([back['start']]+back['points'])))

    def test_z77_keeps_turn_lowers_before_crossing_and_preserves_placement(self):
        r,_=route(Z77_PROFILES[1]);old,_=route(TURN05_PROFILES[1])
        self.assertEqual(r['points'][:2],old['points'][:2])
        self.assertEqual(r['points'][2],dict(old['points'][1],Z=77))
        self.assertEqual(r['points'][3],dict(old['points'][2],Z=77))
        self.assertEqual(r['points'][4:],old['points'][3:])
        self.assertEqual(r['points'][-1]['Z'],53.72)
        back,_=route(Z77_PROFILES[0])
        self.assertEqual([r['start']]+r['points'],list(reversed([back['start']]+back['points'])))
        self.assertEqual(z77_profiles_for_start(r['start']),(Z77_PROFILES[1],))
        self.assertEqual(z77_profiles_for_start(back['start']),Z77_PROFILES)
        self.setup_route(Z77_PROFILES[1]);self.points[3]['Z']=139.93
        with self.assertRaises(TransferError):self.execute()
        self.assertEqual(self.s.robot.jobs,[])

    def test_return_only_has_no_second_approach_and_requires_hamilton_start(self):
        back,_=route(Z77_PROFILES[0])
        self.assertEqual(z77_profiles_for_start(back['start'],'home'),(Z77_PROFILES[0],))
        with self.assertRaises(TransferError):z77_profiles_for_start(back['points'][-1],'home')
        with self.assertRaises(TransferError):z77_profiles_for_start(back['start'],'unknown')
        self.setup_route(Z77_PROFILES[1]);self.speeds[-1]=40
        with self.assertRaises(TransferError):self.execute()
        self.assertEqual(self.s.robot.jobs,[])

    def test_speed137_keeps_z77_geometry_and_slow_contact_segments(self):
        for old,new in zip(Z77_PROFILES,FAST_PROFILES):
            previous,_=route(old);fast,_=route(new)
            self.assertEqual(fast['points'],previous['points'])
            self.assertEqual(fast['start'],previous['start'])
            self.assertEqual(fast['segment_speeds'],[137 if v==40 else v for v in previous['segment_speeds']])
        self.setup_route(FAST_PROFILES[1]);self.speeds[-1]=137
        with self.assertRaises(TransferError):self.execute()
        self.assertEqual(self.s.robot.jobs,[])
        self.setup_route(FAST_PROFILES[0]);self.speeds[0]=137
        with self.assertRaises(TransferError):self.execute()
        self.assertEqual(self.s.robot.jobs,[])
        back,_=route(FAST_PROFILES[0])
        self.assertEqual(z77_profiles_for_start(back['start'],'home',FAST_PROFILES),(FAST_PROFILES[0],))


if __name__=='__main__':unittest.main()
