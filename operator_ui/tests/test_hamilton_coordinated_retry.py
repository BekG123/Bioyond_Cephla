import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from retry_hamilton_dcg_coordinated import C,target,command,corridor,steps,CLOSED_SPAN

class CoordinatedRetryTests(unittest.TestCase):
    def test_high_clearance_complete_targets(self):
        for label,goal in steps():
            cmd=command(goal);cmd.build_parameters().build()
            self.assertIsInstance(cmd,C.PrepMoveToPosition)
            self.assertEqual({p.channel for p in cmd.move_parameters.axis_parameters},{1,2})
            self.assertTrue(all(150<=p['position_z']<=160 for p in goal.values()))
    def test_uncommanded_jaw_repacking_rejected(self):
        start=target(CLOSED_SPAN+20,150);goal=target(CLOSED_SPAN+20,160)
        bad={c:dict(p) for c,p in start.items()};bad[2]['position_y']=59.8
        with self.assertRaisesRegex(RuntimeError,'position_y'):corridor(bad,start,goal)
    def test_arrival_cannot_pass_just_by_spacing(self):
        start=target(CLOSED_SPAN,150);goal=target(CLOSED_SPAN+20,150)
        bad={c:dict(p) for c,p in goal.items()}
        for p in bad.values():p['position_y']+=2
        with self.assertRaises(RuntimeError):corridor(bad,start,goal,arrival=True)
    def test_correct_lift_keeps_jaws_open(self):
        start=target(CLOSED_SPAN+20,150);goal=target(CLOSED_SPAN+20,160)
        corridor(target(CLOSED_SPAN+20,155),start,goal)
        corridor(goal,start,goal,arrival=True)
    def test_no_low_or_overwide_targets(self):
        for span,z in ((CLOSED_SPAN,20),(CLOSED_SPAN+21,150)):
            with self.assertRaises(ValueError):target(span,z)

if __name__=='__main__':unittest.main()
