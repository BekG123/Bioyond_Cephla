import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_hamilton_wider_release import MoveYRelative
from encoder_opening_test import summarize, classify, front_plan, MoveYStep


def trace(channel, base, counter, encoder):
    sign = 1 if channel == 1 else -1
    s = lambda c, e: dict(channel=channel, position_mm=base + sign * c, encoder_position_mm=base + sign * e)
    # The last reading repeats while settled, as in the live trace.
    return [s(0, 0)] * 5, [s(c, e) for c, e in zip(counter, encoder)] + [s(counter[-1], encoder[-1])] * 5


def verdict(channel, counter, encoder, expected=.5):
    before, active = trace(channel, 90 if channel == 1 else -1.4, counter, encoder)
    return classify(summarize(before, active, channel, 'position_mm'),
                    summarize(before, active, channel, 'encoder_position_mm'), expected)


class EncoderOpeningTests(unittest.TestCase):
    def test_decision_table_both_channels(self):
        for c in (1, 2):
            self.assertEqual(verdict(c, [.1, .3, .5], [.1, .3, .5]), 'no_anomaly_both_followed')
            self.assertEqual(verdict(c, [-2.2, .2, .5], [.0, .2, .5]), 'counter_jump_only_reporting_or_resync')
            self.assertEqual(verdict(c, [-2.2, .2, .5], [-2.1, .2, .5]), 'both_inward_actual_reversal')
            self.assertEqual(verdict(c, [.1, .3, .5], [.0, .0, .05]), 'counter_outward_encoder_not_following')
            self.assertEqual(verdict(c, [.1, .2, .2], [.1, .2, .2]), 'inconclusive')
            self.assertEqual(verdict(c, [0, 0, 0], [0, 0, 0], expected=0), 'no_anomaly_both_followed')
            self.assertEqual(verdict(c, [0, .4, .4], [0, 0, 0], expected=0), 'inconclusive')

    def test_summary_signs(self):
        before, active = trace(2, -1.4, [-2.2, .5], [0, .5])
        counter = summarize(before, active, 2, 'position_mm')
        self.assertAlmostEqual(counter['most_inward_mm'], 2.2)
        self.assertAlmostEqual(counter['most_outward_mm'], .5)

    def test_front_plan_ends_on_target(self):
        plan = front_plan(53.87074279785156, -1.392259120941162)
        self.assertTrue(all(set(p) == {2} and 0 < p[2] <= .5 for p in plan))
        self.assertAlmostEqual(sum(p[2] for p in plan), 55.263, places=3)
        self.assertEqual(len(plan), 111)
        for bad in (53.87, 53.9, -10):
            with self.assertRaises(ValueError): front_plan(53.87, bad)

    def test_symmetric_step_matches_reviewed_payload(self):
        self.assertEqual(MoveYStep(((1, .5), (2, .5))).build_parameters().build(), MoveYRelative(.5).build_parameters().build())
        for bad in ((), ((2, .6),), ((2, -.1),), ((3, .5),)):
            with self.assertRaises(ValueError): MoveYStep(bad).build_parameters()


if __name__ == '__main__': unittest.main()
