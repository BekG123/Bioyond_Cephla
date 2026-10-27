"""Direct true-Home route through real queue Lua with fake hardware."""
from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

import test_squid_handling as fixture
from hamilton_true_home import configured,check_route,segment_envelope,station_reference
from trajectory_queue import LuaTrajectory


class DirectHomeTests(unittest.TestCase):
    # Reuse complete fake controller setup without inheriting its test methods.
    setUp=fixture.SquidHandlingTests.setUp
    stop=fixture.SquidHandlingTests.stop
    jaw=fixture.SquidHandlingTests.jaw
    def test_direct_roundtrip_three_commands_each_without_home_area(self):
        original,_,_=self.backend.hamilton.reviewed()
        self.s.pose,self.s.q=station_reference(original)
        for action in ('move_home','move_hamilton'):
            before=len(self.s.robot.calls)
            plan=self.agent.button(action)
            self.assertIn('clearance',plan['summary'])
            self.assertTrue(any('accepted Home-Hamilton route' in r for r in plan['requirements']))
            self.agent.confirm(dict(ready=True,plan_id=plan['id']))
            result=self.run.finish()
            self.assertTrue(result['ok'],result)
            self.assertEqual(len(self.s.robot.calls)-before,3)
        self.assertFalse(self.s.grips)

    def test_revised_joint_height_and_negative_joint_start_rejection(self):
        review=configured()
        home=review['forward'][0]
        from scope_compact137 import accepted
        _,_,_,trials=accepted()
        q=trials['reverse']['final_robot']['joints']
        end,checked=check_route(home,review['forward'][1:],q,self.cfg,self.s.envelope,review)
        self.assertGreaterEqual(end['J1'],0)
        self.assertAlmostEqual(end['J1'],22.62,delta=.02)
        self.assertEqual(checked[-1]['pose']['Z'],61.22)
        bad={**end,'J1':-.001}
        with self.assertRaisesRegex(Exception,'starting vertical joint'):
            check_route(review['reverse'][0],review['reverse'][1:],bad,self.cfg,self.s.envelope,review)

    def test_old_hamilton_height_is_not_new_station(self):
        original,_,_=self.backend.hamilton.reviewed()
        first=original['trajectory'][0]
        self.assertEqual(self.backend.station(first['pose_mm'],first['joints']),'Other position')
        pose,q=station_reference(original)
        self.assertEqual(self.backend.station(pose,q),'Hamilton')

    def test_measured_return_uses_existing_exit_and_true_home(self):
        review = configured()
        measured = review['measured_return_start']
        self.s.pose, self.s.q = deepcopy(measured['pose']), deepcopy(measured['joints'])
        self.assertEqual(self.backend.station(self.s.pose,self.s.q), 'Hamilton')
        plan = self.agent.button('move_home')
        travel = [step for step in plan['steps'] if step['kind'] == 'travel']
        self.assertEqual(len(travel), 1)
        self.assertEqual(travel[0]['points'], review['reverse'][1:])
        self.assertEqual(travel[0]['start'], measured['pose'])
        self.agent.confirm(dict(ready=True,plan_id=plan['id']))
        self.assertTrue(self.run.finish()['ok'])
        self.assertEqual(len(self.s.robot.calls), 3)
        for key,value in review['reverse'][-1].items():
            self.assertAlmostEqual(self.s.pose[key],value,places=4)
        self.assertFalse(self.s.grips)

    def test_measured_departure_is_narrow_and_checks_joint_configuration(self):
        from hamilton_true_home import departure_start
        review = configured()
        pose = review['measured_return_start']['pose']
        q = review['measured_return_start']['joints']
        for axis in ('X','Y','Rz'):
            shifted = {**pose,axis:pose[axis]+.21}
            self.assertFalse(departure_start(shifted,review))
            self.assertEqual(self.backend.station(shifted,q),'Other position')
        for axis in ('J2','J3','J4'):
            wrong = {**q,axis:q[axis]+360}
            self.assertEqual(self.backend.station(pose,wrong),'Other position')
        with patch('hamilton_accepted_route.HASHES',{'candidate.json':'invalid'}):
            with self.assertRaisesRegex(Exception,'evidence changed'):
                configured()

    def test_near_endpoint_departure_only_truncates_exit_and_roundtrips(self):
        original,_,_=self.backend.hamilton.reviewed()
        self.s.pose,self.s.q=station_reference(original)
        self.s.pose['Z']+=.53;self.s.q['J1']+=.53
        for action in ('move_home','move_hamilton'):
            plan=self.agent.button(action)
            self.agent.confirm(dict(ready=True,plan_id=plan['id']))
            self.assertTrue(self.run.finish()['ok'])
        self.assertAlmostEqual(self.s.pose['Z'],61.22,places=4)
        self.assertEqual(len(self.s.robot.calls),6)
        self.assertFalse(self.s.grips)
        review=configured()
        from hamilton_true_home import departure_start
        for bad in ({**review['reverse'][0],'Z':66.28},
                    {**review['reverse'][0],'X':144.56},
                    {**review['reverse'][0],'Z':61.16}):
            self.assertFalse(departure_start(bad,review))

    def test_offroute_mixed_profile_overspeed_and_unreviewed_refused(self):
        review=configured();path=review['forward']
        bad=deepcopy(path[1:]);bad[0]['X']+=1
        for points,speed,flags in (
            (bad,137,dict(reviewed=True,hamilton_home=True,home_speed137=True)),
            (path[1:],138,dict(reviewed=True,hamilton_home=True,home_speed137=True)),
            (path[1:],137,dict(hamilton_home=True,home_speed137=True)),
            (path[1:],137,dict(reviewed=True,hamilton_home=True,scope_compact=True,home_speed137=True)),
        ):
            with self.assertRaises(Exception):
                LuaTrajectory(self.s).execute(self.run,path[0],self.s.q,points,self.cfg,speed,
                                              lambda *a:None,**flags)
        self.assertFalse(self.s.robot.calls)

    def test_new_connector_cannot_inherit_old_workspace_exception(self):
        review=configured();path=review['forward']
        self.assertIs(segment_envelope(path[0],path[1],self.s.envelope,review),self.s.envelope)
        shifted={**path[1],'X':path[1]['X']+.5}
        self.assertIs(segment_envelope(shifted,path[2],self.s.envelope,review),self.s.envelope)
        env=deepcopy(self.s.envelope);env['Y'][0]=-200
        with self.assertRaises(Exception):
            check_route(path[0],path[1:],self.s.q,self.cfg,env,review)

    def test_lacry_hamilton_squid_and_back_use_accepted_route_via_home(self):
        route=configured();home=route['forward'][0]
        for action,destination in (('move_hamilton','Hamilton'),('transfer_hamilton_squid','Squid'),
                                   ('move_hamilton','Hamilton'),('move_home','Home')):
            plan=self.agent.propose([action])
            legs=[s for s in plan['steps'] if s['kind']=='travel']
            if len(legs)>1:
                self.assertEqual(legs[0]['points'][-1],home)
                self.assertEqual(legs[1]['start'],home)
            for leg in legs:
                if leg['profile'].get('hamilton_home'):
                    expected=route['forward'] if leg['start']==home else route['reverse']
                    self.assertEqual(leg['points'],expected[1:])
            self.agent.confirm(dict(ready=True,plan_id=plan['id']))
            result=self.run.finish();self.assertTrue(result['ok'],result)
            self.assertEqual(self.backend.station(self.s.pose,self.s.q),destination)
        self.assertFalse(self.s.grips)

    def test_old_lower_endpoint_is_no_longer_hamilton(self):
        from hamilton_accepted_route import evidence
        old=evidence()['candidate.json']['parent']['forward'][-1]
        original,_,_=self.backend.hamilton.reviewed()
        self.assertEqual(self.backend.station(old,original['trajectory'][0]['joints']),'Other position')
