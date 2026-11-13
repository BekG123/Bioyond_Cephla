import unittest
from plan_hotel_slot2_from_slot1 import build
from run_hotel_slot1_workflow import load_workflow

class Slot2CandidateTests(unittest.TestCase):
    def test_preserves_home_and_lower_turns_and_uses_exact_taught_endpoint(self):
        p=build();_,base=load_workflow()
        d=p['delivery_routes'];r=p['retrieval_routes']
        for phase in ('connect','descend','proof'):
            self.assertEqual(d[phase]['points'],base['deliver']['routes'][phase]['points'])
            self.assertEqual(d[phase]['speeds'],base['deliver']['routes'][phase]['speeds'])
        self.assertEqual(d['deliver']['points'][:4],base['deliver']['routes']['deliver']['points'][:4])
        self.assertEqual(r['seat']['points'],base['retrieve']['routes']['seat']['points'])
        end=p['endpoint'];self.assertEqual(end,dict(X=293.72,Y=-135.351,Z=295.995,Rz=-.652))
        self.assertEqual(d['deliver']['points'][-1],end)
        self.assertEqual(r['approach']['points'][-1],end)
        for key in ('Y','Z','Rz'):self.assertEqual(d['deliver']['points'][-2][key],end[key])
        self.assertEqual(r['lift']['points'][0]['Z']-end['Z'],5)
        for key in ('Y','Z','Rz'):self.assertEqual(r['return']['points'][0][key],r['lift']['points'][0][key])
        self.assertFalse(p['execution_enabled']);self.assertFalse(p['global_limits_changed'])

    def test_slot3_uses_vertical_pitch_without_accumulating_xy_or_yaw(self):
        two=build(2);three=build(3)
        self.assertEqual(three['endpoint']['Z'],352.387)
        self.assertEqual(three['retrieval_routes']['lift']['points'][0]['Z'],357.387)
        for k in ('X','Y','Rz'):self.assertEqual(two['endpoint'][k],three['endpoint'][k])
        self.assertEqual(three['blockers'],[])
        for phase in ('connect','descend','proof'):
            self.assertEqual(two['delivery_routes'][phase]['points'],three['delivery_routes'][phase]['points'])
        self.assertEqual(two['delivery_routes']['deliver']['points'][:4],three['delivery_routes']['deliver']['points'][:4])

    def test_slot4_remains_blocked_above_workspace_and_does_not_expand_limits(self):
        p=build(4)
        self.assertEqual(p['endpoint']['Z'],406.779)
        self.assertEqual(p['retrieval_routes']['lift']['points'][0]['Z'],411.779)
        self.assertEqual(p['status'],'blocked_workspace_limit')
        self.assertTrue(p['blockers']);self.assertFalse(p['execution_enabled'])
        self.assertEqual(p['original_global_envelope']['Z'][1],400)
        self.assertFalse(p['global_limits_changed'])

if __name__=='__main__':unittest.main()
