"""Real Lua queue, simulated controller; no hardware access."""
from unittest.mock import patch
import unittest
from test_squid_48well_endpoint_trial import EndpointTests
import squid_48well_retrieval_trial as retrieval
from squid_48well_endpoint_trial import check_route
from trajectory_queue import LuaTrajectory

class RetrievalTests(unittest.TestCase):
    stop=EndpointTests.stop
    def setUp(self):
        EndpointTests.setUp(self)
        plan,self.path=retrieval.reference()
        from scope_compact137 import accepted
        self.s.q=dict(accepted()[3]['reverse']['final_robot']['joints'])
        self.s.pose=dict(self.path[0]);self.e1=3.9
        p=patch.object(retrieval,'OUTPUT',__import__('squid_48well_endpoint_trial').OUTPUT)
        p.start();self.addCleanup(p.stop)
        self.grips=[]
        def grip(value,speed):
            self.grips.append((value,speed));self.e1=value
            return dict(ok=True)
        self.s.move_gripper=grip

    def test_retreat_retrieve_home(self):
        approved=retrieval.review(self.s,self.cfg)
        with patch.object(retrieval.time,'sleep',lambda _:None):
            result=retrieval.execute(self.run,self.s,self.cfg,approved)
        self.assertTrue(result['ok'])
        for key in self.path[0]:self.assertAlmostEqual(self.s.pose[key],self.path[0][key],places=4)
        self.assertEqual(self.e1,3.9)
        self.assertTrue(self.grips)
        self.assertEqual(self.grips[0],(7.0,5))
        self.assertTrue(all(3.9<=v<=7 and speed==5 for v,speed in self.grips))
        self.assertEqual([c[1] for c in self.s.robot.calls],
                         [137,137,137,5,5,137,137,137,137,137,137,137,5,5,137,137,137,137])
        self.assertEqual(self.stops,[])
        with self.assertRaisesRegex(Exception,'already attempted'):retrieval.review(self.s,self.cfg)

    def test_departure_overspeed_rejected(self):
        name,phase,start,points,speed=next(p for p in retrieval.phases() if p[0]=='loaded_lift')
        with self.assertRaisesRegex(Exception,'at most 5'):
            LuaTrajectory(self.s).execute(self.run,start,self.s.q,points,self.cfg,137,
                lambda *a:None,reviewed=True,scope_trial=True,scope_speed137=True,scope_phase=phase)
        self.assertEqual(self.s.robot.calls,[])

    def test_support_inspection_stops_before_release_or_retreat(self):
        approved=retrieval.review(self.s,self.cfg,stop_before_release=True)
        result=retrieval.execute(self.run,self.s,self.cfg,approved)
        self.assertTrue(result['ok'])
        self.assertTrue(result['seating_inspection_required'])
        self.assertFalse(result['release_executed'])
        self.assertEqual(self.grips,[])
        self.assertEqual(self.stops,[])
        self.assertEqual([c[1] for c in self.s.robot.calls],[137,137,137,5])
        for key in self.path[-1]:self.assertAlmostEqual(self.s.pose[key],self.path[-1][key],places=4)

    def test_cancel_before_first_motion(self):
        approved=retrieval.review(self.s,self.cfg);self.run.cancelled=True
        with self.assertRaisesRegex(Exception,'Stopped'):retrieval.execute(self.run,self.s,self.cfg,approved)
        self.assertEqual(self.s.robot.calls,[]);self.assertEqual(self.grips,[])
        self.assertIn('stop',self.stops)

    def test_final_3p94_is_within_existing_grip_band(self):
        original=self.s.move_gripper
        def grip(value,speed):
            result=original(value,speed)
            if value==3.9:self.e1=3.94
            return result
        self.s.move_gripper=grip
        with patch.object(retrieval.time,'sleep',lambda _:None):
            result=retrieval.execute(self.run,self.s,self.cfg,retrieval.review(self.s,self.cfg))
        self.assertTrue(result['ok']);self.assertEqual(self.stops,[])

    def test_unsettled_completed_grip_sends_no_lift_and_keeps_lua_running(self):
        original=self.s.move_gripper
        def grip(value,speed):
            result=original(value,speed)
            if value==3.9:
                self.e1=3.96
                p=patch.object(retrieval,'GRIP_SETTLE_SECONDS',0);p.start();self.addCleanup(p.stop)
            return result
        self.s.move_gripper=grip
        with patch.object(retrieval.time,'sleep',lambda _:None):
            with self.assertRaises(retrieval.GripSettlingIncomplete):
                retrieval.execute(self.run,self.s,self.cfg,retrieval.review(self.s,self.cfg))
        self.assertEqual(len(self.s.robot.calls),13)
        self.assertEqual(self.stops,[])
        self.assertEqual(self.s.robot.program_state,'running')

if __name__=='__main__':unittest.main()
