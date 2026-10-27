"""Offline boundary checks; importing the planner cannot access hardware."""
import importlib.util
from pathlib import Path
import unittest
import json
import tempfile
from unittest.mock import patch

path = Path(__file__).resolve().parents[2]/'Pick and Hold/Grip/fast_position_plan.py'
spec = importlib.util.spec_from_file_location('fast_position_plan', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FastPositionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile = Path(self.tmp.name)/'profile.json'
        self.profile.write_text(json.dumps(dict(target_e1_mm=3.8,speed=5,
            phases=[dict(until_e1_mm=5,max_step_mm=1),
                    dict(until_e1_mm=4,max_step_mm=.2),
                    dict(until_e1_mm=3.8,max_step_mm=.1)])))
        active = patch.object(module,'PROFILE',self.profile)
        active.start()
        self.addCleanup(active.stop)

    def test_full_approach(self):
        plan = module.plan_closure(28)
        self.assertEqual(plan['command_count'], 30)
        self.assertFalse(plan['dispatch'])
        self.assertEqual([p['target_e1_mm'] for p in plan['commands'][-2:]], [3.9, 3.8])

    def test_boundary_and_partial_starts(self):
        for start in (28.05, 5.01, 5, 4.19, 4.01, 4, 3.95, 3.9, 3.8):
            plan = module.plan_closure(start)
            previous = start
            for command in plan['commands']:
                target = command['target_e1_mm']
                self.assertLess(target, previous)
                self.assertGreaterEqual(target, 3.8)
                bound = 1 if previous > 5 else .2 if previous > 4 else .1
                self.assertLessEqual(command['delta_mm'], bound+1e-9)
                self.assertGreaterEqual(target, 5 if previous > 5 else 4 if previous > 4 else 3.8)
                previous = target
            self.assertEqual(previous, 3.8)

    def test_invalid_feedback(self):
        for start in (True, None, '4', float('nan'), float('inf'), 3.79, 28.06):
            with self.assertRaises(ValueError):
                module.plan_closure(start)

    def test_3p7_requires_trial_and_never_closes_further(self):
        p=json.loads(self.profile.read_text())
        p['target_e1_mm']=3.7
        p['phases'][-1]['until_e1_mm']=3.7
        self.profile.write_text(json.dumps(p))
        with self.assertRaises(ValueError):module.plan_closure(28)
        p['supervised_trial']='e1_3p7_20261020'
        self.profile.write_text(json.dumps(p))
        plan=module.plan_closure(28)
        self.assertEqual(plan['command_count'],31)
        self.assertEqual(plan['commands'][-1]['target_e1_mm'],3.7)
        with self.assertRaises(ValueError):module.plan_closure(3.69)
        p['target_e1_mm']=3.6
        self.profile.write_text(json.dumps(p))
        with self.assertRaises(ValueError):module.plan_closure(28)


if __name__ == '__main__':
    unittest.main()
