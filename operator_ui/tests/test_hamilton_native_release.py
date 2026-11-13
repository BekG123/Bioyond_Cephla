import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from release_hamilton_supported_plate import EXPECTED,preflight,validate_motion

class NativeReleaseTests(unittest.TestCase):
    def setUp(self):
        self.start=preflight({'positions':[dict(channel=c,position_x=p[0],position_y=p[1],position_z=p[2]) for c,p in EXPECTED.items()]})
        self.bounds=[dict(channel=c,y_min=-20,y_max=397) for c in (1,2)]
    def test_outward_only_opening_is_accepted(self):
        after=copy.deepcopy(self.start)
        after[1]['position_y']+=4;after[2]['position_y']-=4
        validate_motion(self.start,after,self.bounds)
    def test_unexpected_lift_inward_or_excessive_opening_stops(self):
        for channel,key,delta in ((1,'position_z',1),(1,'position_x',1),(1,'position_y',-.5),(2,'position_y',.5),(2,'position_y',-11)):
            after=copy.deepcopy(self.start);after[channel][key]+=delta
            with self.assertRaises(RuntimeError):validate_motion(self.start,after,self.bounds)
    def test_changed_seated_pose_rejected(self):
        values=copy.deepcopy(self.start);values[1]['position_z']+=1
        with self.assertRaises(RuntimeError):preflight({'positions':list(values.values())})

if __name__=='__main__':unittest.main()
