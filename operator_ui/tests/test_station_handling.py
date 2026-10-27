"""Station intent must never dispatch the camera-based plate workflow."""
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from station_handling import station_plan
from experiment_plan import build_experiment
from lacry_agent import LacryAgent
from researcher_teaching import TeachingError
from sequences import Runner


class StationTests(unittest.TestCase):
    def test_station_operations_are_separate_and_require_teaching(self):
        for station in ('Hamilton','Squid'):
            for operation in ('pickup','release'):
                plan=station_plan(station,operation)
                self.assertFalse(plan['executable']);self.assertFalse(plan['camera_required'])
                self.assertEqual(plan['actions'],[])
                self.assertTrue(all(s['kind']=='station_handling_preview' for s in plan['steps']))
                self.assertIn(station+' → Home',plan['steps'][-1]['label'])
                self.assertIsNone(plan['approach_clearance_mm'])
                self.assertEqual(plan['opening_e1_mm'],5)
                self.assertEqual(plan['grip_target_e1_mm'],3.7 if operation=='pickup' else None)
                self.assertEqual((plan['lift_mm'],plan['lift_speed'],plan['departure_speed']),(5,5,137))
                self.assertEqual(plan['validation_status'],
                                 'operator_accepted_squid' if station=='Squid' else 'pending_station_validation')

    def test_experiment_uses_station_handling_once_without_duplicate_departure(self):
        plan=build_experiment('hamilton_to_squid',5)
        for step in plan['steps']:
            if step['phase'] in ('pickup','verify_delivery'):
                local=step['station_handling']
                self.assertEqual(len(local['steps']),4)
                self.assertFalse(local['camera_required'])
        self.assertNotIn('full_calibration',plan['actions'])

    def test_model_preview_cannot_run_even_after_yes(self):
        backend=Mock();runner=Runner()
        agent=LacryAgent(backend,Mock(),lambda:runner,client=Mock())
        plan=station_plan('Hamilton','release')
        plan.update(id='static-preview',at=__import__('time').time())
        agent.pending=plan
        with self.assertRaisesRegex(TeachingError,'preview only'):agent.send('yes')
        backend.execute_step.assert_not_called()
        self.assertFalse(runner.active)

    def test_wrong_camera_pickup_is_blocked_before_proposal_or_start(self):
        backend=Mock();runner=Runner();classic=Mock()
        backend.camera_plate_only.side_effect=TeachingError('Camera pickup is not station handling')
        agent=LacryAgent(backend,Mock(),lambda:runner,client=Mock(),classic_pickup=classic)
        with self.assertRaises(TeachingError):agent.button('full_calibration')
        with self.assertRaises(TeachingError):agent._start_classic({})
        classic.start.assert_not_called()


if __name__=='__main__':unittest.main()
