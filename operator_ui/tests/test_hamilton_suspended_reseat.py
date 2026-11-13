import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reseat_hamilton_48_suspended import EXPECTED,SEATED,lowering,verify_arrival,opening,verify_opening
from park_after_hamilton_48_release import retreat_plan

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.pose={'positions':[dict(channel=c,position_x=v[0],position_y=v[1],position_z=v[2]) for c,v in EXPECTED.items()]}
    def test_preserves_jaw_difference_and_only_moves_z(self):
        command=lowering(self.pose)
        command.build_parameters().build()
        self.assertEqual(command.velocity,1)
        for p,c in zip(self.pose['positions'],command.channels):self.assertAlmostEqual(p['position_z']-c.z_position,10)
        after=copy.deepcopy(self.pose)
        for p in after['positions']:p['position_z']-=10
        verify_arrival(self.pose,after,10)
        after['positions'][0]['position_y']+=.2
        with self.assertRaises(RuntimeError):verify_arrival(self.pose,after,10)
    def test_changed_pose_and_nan_rejected(self):
        for value in (99,float('nan')):
            p=copy.deepcopy(self.pose);p['positions'][0]['position_z']=value
            with self.assertRaises(RuntimeError):lowering(p)
    def test_duplicate_channels_rejected(self):
        self.pose['positions'][1]['channel']=1
        with self.assertRaises(RuntimeError):lowering(self.pose)
    def test_opening_preserves_height_and_spreads_outward(self):
        seated={'positions':[dict(channel=c,position_x=v[0],position_y=v[1],position_z=v[2]) for c,v in SEATED.items()]}
        cmd=opening(seated);cmd.build_parameters().build()
        self.assertEqual(cmd.velocity,1)
        after=copy.deepcopy(seated)
        for p,c in zip(after['positions'],cmd.channels):
            self.assertAlmostEqual(c.y_position-p['position_y'],2 if c.channel==1 else -2)
            p['position_y']=c.y_position
        verify_opening(seated,after,True)
        after['positions'][0]['position_z']+=.2
        with self.assertRaises(RuntimeError):verify_opening(seated,after,True)
        with self.assertRaises(RuntimeError):opening(self.pose)
    def test_retreat_requires_verified_empty_opening_and_preserves_spacing(self):
        after={'positions':[dict(channel=c,position_x=v[0],position_y=v[1]+(2 if c==1 else -2),position_z=v[2]) for c,v in SEATED.items()]}
        opened=dict(status='opened_awaiting_clearance_inspection',jaws_opened=True,after=after)
        current=dict(PrepGetPositions=after,PrepGetPlateHeld=dict(value=False),PrepGetTipDefinitionHeld=dict(value=dict(label='DCG')))
        plan=retreat_plan(opened,current)
        for p,c in zip(after['positions'],plan['command'].channels):self.assertAlmostEqual(c.z_position-p['position_z'],10)
        current['PrepGetPlateHeld']['value']=True
        with self.assertRaises(RuntimeError):retreat_plan(opened,current)

if __name__=='__main__':unittest.main()
