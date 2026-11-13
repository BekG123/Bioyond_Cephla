import contextlib
import io
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from autonomy import TransferError
from cellvis24_recorded_hamilton_route import reference,SMOOTH_PROFILES,validate_shape,validate_speeds
from cellvis24_workflow import compile_steps
from trajectory_queue import LuaTrajectory
from test_cellvis_direct_wrist import DirectWristTests
import run_cellvis24_recorded_hamilton as cli


class SmoothHamiltonTests(unittest.TestCase):
    def test_preserves_lift_level_crossing_endpoint_and_slow_seat(self):
        parent=reference();p=reference('smooth3');f=p['routes']['forward']
        self.assertEqual(len(f['points']),6)
        self.assertEqual(f['points'][0],parent['routes']['forward']['points'][0])
        self.assertEqual(f['points'][-2:],parent['routes']['forward']['points'][-2:])
        self.assertEqual({q['Z'] for q in f['points'][:4]},{98.6})
        self.assertEqual(f['segment_speeds'],[137]*5+[5])
        self.assertGreater(p['comparison']['max_xyz_deviation_mm'],12)
        self.assertFalse(p['hardware_tested'])
        for r in p['routes'].values():
            self.assertTrue(r['validation']['workspace_valid'])
            self.assertFalse(r['validation']['collision_clearance_verified'])

    def test_real_lua_six_moves_one_barrier_both_directions(self):
        p=reference('smooth3')
        for direction,profile in zip(('forward','reverse'),SMOOTH_PROFILES):
            h,s,_,_=DirectWristTests().setup_route();r=p['routes'][direction]
            s.pose=deepcopy(r['start']);s.q=deepcopy(r['start_joints'])
            result=LuaTrajectory(s).execute(h.run,s.pose,s.q,r['points'],p['config'],137,lambda *a:None,
                reviewed=True,hamilton_short_side=profile,segment_speeds=r['segment_speeds'])
            self.assertTrue(result['ok']);self.assertEqual(s.robot.barriers,1)
            self.assertEqual(len(s.robot.calls),6)
            self.assertEqual([c[1] for c in s.robot.calls],r['segment_speeds'])
            self.assertEqual(s.grips,[])

    def test_exact_variant_shape_and_speed_binding(self):
        r=reference('smooth3')['routes']['forward'];pts=deepcopy(r['points']);pts[1]['Z']-=1
        with self.assertRaises(TransferError):validate_shape(r['start'],pts,SMOOTH_PROFILES[0])
        with self.assertRaises(TransferError):validate_speeds(r['start'],r['points'],SMOOTH_PROFILES[0],[137]*6)
        with self.assertRaises(TransferError):compile_steps(['hamilton'],1,recorded_hamilton_variant='smooth3')
        s=compile_steps(['hamilton'],1,recorded_hamilton_delivery=True,recorded_hamilton_variant='smooth3')
        self.assertEqual(s[-1]['flags']['hamilton_short_side'],SMOOTH_PROFILES[0])
        self.assertEqual(len(s[-1]['points']),6)
        self.assertEqual(len(compile_steps(['hamilton'],1,recorded_hamilton_delivery=True)[-1]['points']),42)

    def test_cli_continuous_calibration_selects_smooth_variant(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);receipt=folder/'receipt.json';receipt.write_text('{}')
            with patch.object(cli,'REPORTS',folder/'runs'),patch.object(cli,'verify_backend') as verify,patch.object(cli,'calibrate_to_scanner',return_value=dict(trial_id='a'*32,final=dict(record=str(receipt)))) as calibrate,patch.object(cli,'scanner_phase',return_value=dict(record=str(receipt))),patch.object(cli,'delivery',return_value=dict(record=str(receipt))) as delivery,patch('builtins.input',side_effect=AssertionError('No inspection prompts')),contextlib.redirect_stdout(io.StringIO()):
                result=cli.main(['--full-calibration','--smooth-transit','--execute','--path-clear'])
            verify.assert_called_once_with('smooth3')
            calibrate.assert_called_once_with(['--full-calibration','--execute','--continuous'])
            delivery.assert_called_once_with(receipt,'smooth3')
            self.assertEqual(result['variant'],'smooth3')

    def test_cli_stale_backend_blocks_before_calibration(self):
        with patch.object(cli,'api',return_value=dict(recorded_hamilton_delivery=True,route_sha256='old')),patch.object(cli,'calibrate_to_scanner') as calibrate:
            with self.assertRaisesRegex(RuntimeError,'Backend route differs'):
                cli.main(['--full-calibration','--smooth-transit','--execute','--path-clear'])
            calibrate.assert_not_called()

    def test_cli_preview_is_read_only_and_identifies_changed_sweep(self):
        out=io.StringIO()
        with patch.object(cli,'api') as api,contextlib.redirect_stdout(out):
            cli.main(['--full-calibration','--smooth-transit'])
        api.assert_not_called();p=json.loads(out.getvalue())
        self.assertEqual(p['queue_targets'],6);self.assertFalse(p['inspection_pauses'])
        self.assertEqual(len(p['transit_targets']),3)


if __name__=='__main__':unittest.main()
