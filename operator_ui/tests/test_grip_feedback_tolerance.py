import unittest
from gripper_closure import grip_feedback_matches
import cellvis24_workflow as w
from test_cellvis24_workflow import WorkflowTests as Fixture
from autonomy import TransferError


class GripFeedbackTests(unittest.TestCase):
    def test_asymmetric_bounds_and_invalid_feedback(self):
        for target in (3.9,4.9,25,26):
            self.assertTrue(grip_feedback_matches(target+.2,target))
            self.assertTrue(grip_feedback_matches(target-.07,target))
            self.assertFalse(grip_feedback_matches(target+.201,target))
            self.assertFalse(grip_feedback_matches(target-.071,target))
        for value in (float('nan'),float('inf'),None,True):
            self.assertFalse(grip_feedback_matches(value,25))

    def fixture(self,bias,opening_bias=0):
        h=Fixture('test_grip_or_holder_mismatch_prevents_dispatch');h.setUp();self.addCleanup(h.doCleanups)
        def grip(target,speed):
            result=h.grip(target,speed)
            h.e1+=opening_bias if target in (7,28) else bias
            return result
        h.service.move_gripper.side_effect=grip
        return h

    def test_plus_point_two_survives_grip_telemetry_travel_and_release(self):
        h=self.fixture(.2)
        p=w.plan(h.service,h.g['cfg'],['squid'],1,h.source)
        r=w.execute(h.run,h.service,h.g['cfg'],p)
        self.assertEqual(r['completed_cycles'],1);self.assertEqual(h.e1,28)
        h.service.program.assert_not_called()

    def test_above_point_two_stops_without_lift(self):
        h=self.fixture(.201)
        p=w.plan(h.service,h.g['cfg'],['squid'],1,h.source)
        with self.assertRaisesRegex(TransferError,'Jaw arrival'):
            w.execute(h.run,h.service,h.g['cfg'],p)
        self.assertEqual(len(h.grips),1)
        self.assertEqual(h.state['pose_mm'],h.g['seat'])
        h.service.program.assert_called_once_with('stop')

    def test_opening_tolerance_is_not_widened(self):
        h=self.fixture(0,opening_bias=.08)
        p=w.plan(h.service,h.g['cfg'],['squid'],1,h.source)
        with self.assertRaisesRegex(TransferError,'Jaw arrival'):
            w.execute(h.run,h.service,h.g['cfg'],p)
        self.assertEqual(h.state['pose_mm'],h.g['points'][-1])
        self.assertEqual(h.grips[-1],(7,5))


if __name__=='__main__':unittest.main()
