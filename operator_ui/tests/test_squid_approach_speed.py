"""Approach-only must not inherit the removed descent's slow speed."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_squid_destination_empty import forward_legs


class ApproachSpeedTest(unittest.TestCase):
    def test_overhead_stop_keeps_transit_speed(self):
        route = ['home', 'clearance', 'via', 'overhead']
        legs = forward_legs(route, 137, approach_only=True)
        self.assertEqual([p for _, p, _ in legs], route[1:])
        self.assertEqual([speed for _, _, speed in legs], [137, 137, 137])

    def test_full_route_keeps_descent_slow(self):
        route = ['home', 'clearance', 'via', 'overhead', 'seated']
        legs = forward_legs(route, 137)
        self.assertEqual([p for _, p, _ in legs], route[1:])
        self.assertEqual([speed for _, _, speed in legs], [137, 137, 137, 5])


if __name__ == '__main__':
    unittest.main()
