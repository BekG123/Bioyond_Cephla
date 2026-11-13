import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reseat_hamilton_coordinated_stop import EXPECTED,SEAT_Z,plan,C

class ReseatTests(unittest.TestCase):
    def feedback(self):return {'positions':[dict(channel=c,position_x=p[0],position_y=p[1],position_z=p[2]) for c,p in EXPECTED.items()]}
    def test_only_short_downward_z_without_jaw_opening(self):
        start,goal,cmd=plan(self.feedback())
        self.assertIsInstance(cmd,C.PrepMoveZAbsolute);self.assertEqual(cmd.velocity,1)
        for c in (1,2):
            self.assertEqual(start[c]['position_y'],goal[c]['position_y'])
            self.assertEqual(start[c]['position_x'],goal[c]['position_x'])
            self.assertTrue(0<start[c]['position_z']-goal[c]['position_z']<3)
            self.assertEqual(goal[c]['position_z'],SEAT_Z)
    def test_changed_pose_is_rejected(self):
        for key in ('position_x','position_y','position_z'):
            feedback=self.feedback();feedback['positions'][0][key]+=.2
            with self.assertRaises(RuntimeError):plan(feedback)

if __name__=='__main__':unittest.main()
