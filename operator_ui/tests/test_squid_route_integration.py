"""Offline tests: recorded geometry and mocked devices; never move hardware."""
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import squid_handling_route as routes
import dropoff_approach_20261103 as approach
import release_empty_home_20261103 as release
import pickup_squid_home_20261103 as pickup
import real_camera_five_20261103 as imaging
import ten_real_imaging_cycles_20261103 as batch
import full_calibration_ten_imaging_20261107 as full
from capture_squid_approach_20261103 import sha
from prepare_squid_destination import validate

ROUTE = dict(route_source=routes.CURRENT_SOURCE, route_sha=routes.CURRENT_SHA)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.plan = routes.load_route(routes.CURRENT_SOURCE, routes.CURRENT_SHA)
        self.points = self.plan['routes']['from_capture']
        receipt = routes.FOLDER/'calibration_final_squid_retry02_20261108/calibrated_home.json'
        self.state = json.loads(receipt.read_bytes())['state']
        self.state['robot']['external_axes']['E1'] = 7

    def api(self, name, data=None):
        if name == 'state':
            return deepcopy(self.state)
        if name == 'robot_params':
            return self.plan['cfg']
        raise AssertionError(f'Unexpected device call: {name}')

    def test_recorded_roundtrip_geometry_and_return_evidence(self):
        result = validate(self.points, self.state['robot']['joints'], self.plan['cfg'], self.plan['envelope'])
        self.assertIn('final_joints', result)
        self.assertEqual(self.points[4], dict(X=223.941, Y=373.761, Z=266.768, Rz=88.34))
        reverse = json.loads((routes.FOLDER/'final_squid_loaded_return_20261108_plan.json').read_bytes())
        self.assertEqual(self.points[4:], reverse['routes']['from_capture'])
        self.assertEqual(self.plan['leg_speeds'][4:], reverse['leg_speeds'])
        legacy = routes.load_route()
        self.assertEqual(legacy['routes']['from_capture'][4]['Z'], 266.81)

    def test_modified_source_refused(self):
        path = self.folder/'changed.json'
        path.write_bytes(routes.CURRENT_SOURCE.read_bytes() + b' ')
        with self.assertRaisesRegex(RuntimeError, 'route changed'):
            routes.load_route(path, routes.CURRENT_SHA)

    def test_all_handling_phases_use_new_geometry_without_jaw_commands(self):
        for module in (approach, release, pickup):
            self.stack.enter_context(patch.object(module, 'api', side_effect=self.api))
        run = self.stack.enter_context(patch.object(approach.runner, 'main'))
        self.stack.enter_context(patch.object(sys, 'argv', ['offline']))
        approach.main(self.folder, **ROUTE)
        forward_path = self.folder/'dropoff_approach_plan_20261103.json'
        forward = json.loads(forward_path.read_bytes())
        self.assertEqual(forward['routes']['from_capture'], self.points[:5])
        write(self.folder/'dropoff_approach_trial_20261103.json', dict(
            status='at_squid_awaiting_supported_plate_confirmation',
            plan_sha256=sha(forward_path), preserved_e1_mm=3.9))
        self.state['robot']['pose_mm'] = self.points[4]
        self.state['robot']['external_axes']['E1'] = 3.9
        release.main(self.folder, **ROUTE)
        returned = json.loads((self.folder/'empty_return_plan_20261103.json').read_bytes())
        self.assertEqual(returned['routes']['from_capture'], self.points[4:])
        self.assertEqual(returned['leg_speeds'], [5,137,137,137])
        self.state['robot']['pose_mm'] = self.points[0]
        self.state['robot']['external_axes']['E1'] = 7
        pickup.main(self.folder, **ROUTE)
        for phase, points in [('pickup_approach', self.points[:5]), ('pickup_loaded_return', self.points[4:])]:
            plan = json.loads((self.folder/f'{phase}_plan_20261103.json').read_bytes())
            self.assertEqual(plan['routes']['from_capture'], points)
        self.assertEqual(run.call_count, 2)

    def test_release_rejects_receipt_for_different_route(self):
        self.stack.enter_context(patch.object(sys, 'argv', ['offline']))
        write(self.folder/'dropoff_approach_trial_20261103.json', dict(
            status='at_squid_awaiting_supported_plate_confirmation', plan_sha256='wrong'))
        write(self.folder/'dropoff_approach_plan_20261103.json', self.plan)
        with self.assertRaisesRegex(RuntimeError, 'does not match'):
            release.main(self.folder, **ROUTE)

    def test_imaging_cycle_passes_route_to_every_handling_call(self):
        self.stack.enter_context(patch.object(imaging, 'OUT', self.folder))
        plan = {}
        write(self.folder/'plan.json', plan)
        write(self.folder/'preflight.json', {'plan_sha256': imaging.digest(plan)})
        state = deepcopy(self.state)
        state['robot']['external_axes']['E1'] = 3.9
        self.stack.enter_context(patch.object(imaging, 'arm_home', return_value=state))
        self.stack.enter_context(patch.object(imaging, 'SquidAdapter'))
        execution = self.stack.enter_context(patch.object(imaging, 'SquidExecution')).return_value
        execution.start.return_value = dict(response={'total_images':5}, run_id='offline')
        self.stack.enter_context(patch.object(imaging, 'native_command', return_value=imaging.LOADING))
        self.stack.enter_context(patch.object(imaging.time, 'sleep'))
        calls = [self.stack.enter_context(patch.object(module, 'main')) for module in (approach, release, pickup)]
        imaging.execute(**ROUTE)
        self.assertEqual([call.call_count for call in calls], [2,1,1])
        for mock in calls:
            for call in mock.call_args_list:
                self.assertEqual(call.kwargs['route_source'], routes.CURRENT_SOURCE)
                self.assertEqual(call.kwargs['route_sha'], routes.CURRENT_SHA)
        execution.restore_loading.assert_called_once()
        execution.wait.assert_called_once()

    def run_batch(self, fail_cycle=None):
        folder = self.folder/'batch'
        self.stack.enter_context(patch.object(batch, 'OUT', folder))
        self.stack.enter_context(patch.object(sys, 'argv', ['offline', '--execute']))
        self.stack.enter_context(patch.object(imaging, 'OUT', self.folder/'unused'))
        self.stack.enter_context(patch.object(imaging, 'AUTH', 'offline'))
        self.stack.enter_context(patch.object(imaging, 'arm_home'))
        home = self.stack.enter_context(patch.object(batch, 'home', return_value={'robot':{}}))
        self.stack.enter_context(patch.object(batch, 'stage_ready', return_value={'state':{'simulation':False,'camera_simulated':False}}))
        self.stack.enter_context(patch.object(imaging, 'prepare'))
        def execute(**kwargs):
            self.assertEqual(kwargs, ROUTE)
            number = int(imaging.OUT.name.split('_')[-1])
            if number == fail_cycle:
                raise RuntimeError('Injected imaging failure')
            write(imaging.OUT/'run.json', {'status':'completed_pending_operator_assessment'})
        call = self.stack.enter_context(patch.object(imaging, 'execute', side_effect=execute))
        self.stack.enter_context(patch.object(batch, 'verify_images', side_effect=lambda folder: {'run_id':folder.name}))
        if fail_cycle:
            with self.assertRaisesRegex(RuntimeError, 'Injected'):
                batch.main()
        else:
            batch.main()
        for invocation in home.call_args_list:
            self.assertEqual(invocation.kwargs, ROUTE)
        return json.loads((folder/'batch.json').read_bytes()), call.call_count

    def test_ten_cycles_keep_count_and_route(self):
        result, count = self.run_batch()
        self.assertEqual((count, result['completed_cycles'], result['verified_images']), (10,10,50))
        self.assertEqual(result['route_source_sha256'], routes.CURRENT_SHA)

    def test_failure_stops_without_retry_or_next_cycle(self):
        result, count = self.run_batch(fail_cycle=2)
        self.assertEqual((count, result['completed_cycles'], result['verified_images']), (2,1,5))
        self.assertEqual(result['status'], 'stopped_or_failed')

    def test_full_entry_calibrates_once_then_runs_same_route(self):
        folder = self.folder/'full'
        self.stack.enter_context(patch.object(full, 'OUT', folder))
        self.stack.enter_context(patch.object(sys, 'argv', ['offline', '--execute']))
        self.stack.enter_context(patch.object(full.calibration, 'OUT'))
        self.stack.enter_context(patch.object(full.calibration, 'AUTH'))
        self.stack.enter_context(patch.object(batch, 'OUT'))
        self.stack.enter_context(patch.object(batch, 'AUTH'))
        self.stack.enter_context(patch.object(batch, 'stage_ready', return_value={'state':{'simulation':False,'camera_simulated':False}}))
        cal = self.stack.enter_context(patch.object(full.calibration, 'main', side_effect=lambda **kwargs: write(
            full.calibration.OUT/'run.json', {'status':'full_calibration_loaded_home_completed_pending_operator_assessment'})))
        cycles = self.stack.enter_context(patch.object(batch, 'main', side_effect=lambda **kwargs: write(
            batch.OUT/'batch.json', {'status':'completed_pending_operator_assessment','completed_cycles':10,'verified_images':50})))
        full.main()
        cal.assert_called_once_with(calibration_only=True, **ROUTE)
        cycles.assert_called_once_with(**ROUTE)


if __name__ == '__main__':
    unittest.main()
