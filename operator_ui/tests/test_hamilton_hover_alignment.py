import unittest
from hamilton_hover_alignment import plan_hover


class HoverTests(unittest.TestCase):
    def setUp(self):
        self.start={1:[289.3,344.99,165.604],2:[289.3,365.015,167.503]}
        self.bounds={c:dict(x_min=.78,x_max=299.78,y_min=-9,y_max=385,z_min=18.2,z_max=165.6) for c in (1,2)}
        self.openings=[[55.87,30.49,66],[56.01,57.48,66.39]]

    def test_path_keeps_clearance_and_channel_order(self):
        plan=plan_hover(self.start,self.bounds,self.openings,.45)
        previous=self.start
        for step in plan['path']:
            p=step['positions']
            self.assertGreaterEqual(p[2][1]-p[1][1],15)
            self.assertEqual(p[1][0],p[2][0])
            for c in (1,2):
                self.assertGreaterEqual(p[c][2],130)
                self.assertLessEqual(p[c][2],165.6)
                self.assertLessEqual(max(abs(a-b) for a,b in zip(previous[c],p[c])),10.001)
            previous=p
        self.assertEqual(previous[1][2],130)
        self.assertFalse(plan['pickup'])

    def test_no_post_match(self):
        with self.assertRaises(ValueError):plan_hover(self.start,self.bounds,self.openings,2)

    def test_no_low_start(self):
        self.start[1][2]=75
        with self.assertRaises(ValueError):plan_hover(self.start,self.bounds,self.openings,.2)

    def test_no_averaging_large_rotation(self):
        self.openings[1][0]=60
        with self.assertRaises(ValueError):plan_hover(self.start,self.bounds,self.openings,.2)

    def test_reject_missing_bounds(self):
        with self.assertRaises(ValueError):plan_hover(self.start,{1:self.bounds[1]},self.openings,.2)


if __name__=='__main__':unittest.main()
