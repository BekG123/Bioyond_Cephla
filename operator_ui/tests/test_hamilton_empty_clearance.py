"""Offline actual Lua execution and invalid-plan rejection for empty clearance."""
import unittest
from test_short_side_hover_transfer import HoverTransferTests
from hamilton_empty_clearance import IDLE, IDLE_JOINTS, PROFILE, SPEEDS, points, reference
from trajectory_queue import LuaTrajectory
from autonomy import TransferError


class EmptyClearanceTests(unittest.TestCase):
    def setup_route(self):
        helper=HoverTransferTests();helper.setup_route()
        self.s,self.run=helper.s,helper.run
        self.s.pose=dict(IDLE);self.s.q=dict(IDLE_JOINTS)
        self.s.cfg=reference()['config'];self.points=points();self.speeds=list(SPEEDS)

    def execute(self,speed=40,**extra):
        return LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,self.points,self.s.cfg,
            speed,lambda *a:None,reviewed=True,hamilton_short_side=PROFILE,segment_speeds=self.speeds,**extra)

    def test_published_queue_preserves_jaws_and_speeds(self):
        self.setup_route();self.assertTrue(self.execute()['ok'])
        self.assertEqual([c[1] for c in self.s.robot.calls],SPEEDS)
        self.assertEqual(self.s.robot.barriers,1)
        self.assertEqual(self.s.grips,[])
        self.assertTrue(all(c[0][6:9]==(3.4,-2,0) for c in self.s.robot.calls))
        self.assertEqual(self.s.envelope['Z'],(70,400))

    def test_invalid_routes_speeds_and_winding_send_nothing(self):
        for change in ('point','start','winding','workspace','mask','speed','mixed'):
            self.setup_route();speed=40;extra={}
            if change=='point':self.points[0]['X']+=1
            elif change=='start':self.s.pose['Z']+=1
            elif change=='winding':self.s.q['J4']+=360
            elif change=='workspace':self.s.envelope['Z']=(50,400)
            elif change=='mask':self.speeds[-1]=40
            elif change=='speed':speed=137
            elif change=='mixed':extra['scanner_empty']=True
            with self.assertRaises(TransferError):self.execute(speed,**extra)
            self.assertEqual(self.s.robot.jobs,[])


if __name__=='__main__':unittest.main()
