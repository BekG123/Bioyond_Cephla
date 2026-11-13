import contextlib
import io
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from autonomy import TransferError
from cellvis24_recorded_hamilton_route import reference,PROFILES,validate_route,validate_shape,validate_speeds
from cellvis24_workflow import compile_steps
from trajectory_queue import LuaTrajectory
from test_cellvis_direct_wrist import DirectWristTests
import run_cellvis24_recorded_hamilton as cli


class RecordedHamiltonTests(unittest.TestCase):
    def test_real_lua_one_queue_exact_42_points_both_directions(self):
        p=reference()
        for direction,profile in zip(('forward','reverse'),PROFILES):
            h,s,_,_=DirectWristTests().setup_route();r=p['routes'][direction]
            s.pose=deepcopy(r['start']);s.q=deepcopy(r['start_joints'])
            result=LuaTrajectory(s).execute(h.run,s.pose,s.q,r['points'],p['config'],137,lambda *a:None,
                reviewed=True,hamilton_short_side=profile,segment_speeds=r['segment_speeds'])
            self.assertTrue(result['ok']);self.assertEqual(s.robot.barriers,1)
            self.assertEqual(len(s.robot.calls),42)
            self.assertEqual([c[1] for c in s.robot.calls],r['segment_speeds'])
            self.assertEqual(s.grips,[])

    def test_shape_order_and_final_contact_speed_are_pinned(self):
        p=reference();r=p['routes']['forward'];pts=deepcopy(r['points'])
        pts[5],pts[6]=pts[6],pts[5]
        with self.assertRaises(TransferError):validate_shape(r['start'],pts,PROFILES[0])
        with self.assertRaises(TransferError):validate_speeds(r['start'],r['points'],PROFILES[0],[137]*42)
        self.assertEqual({q['Z'] for q in p['taught_points']},{98.6})
        self.assertLessEqual(p['approximation']['max_xyz_deviation_mm'],1.02)
        self.assertLessEqual(p['approximation']['max_yaw_deviation_deg'],1.02)

    def test_delivery_only_and_mutually_exclusive_modes(self):
        steps=compile_steps(['hamilton'],1,recorded_hamilton_delivery=True)
        self.assertEqual(steps[-1]['flags']['hamilton_short_side'],PROFILES[0])
        self.assertEqual(steps[-1]['label'],'Travel forward')
        self.assertEqual(len(steps[-1]['points']),42)
        for extra in ({'taught_hamilton_delivery':True},{'direct_hamilton':True},{'held_hamilton_roundtrip':True}):
            with self.assertRaises(TransferError):compile_steps(['hamilton'],1,recorded_hamilton_delivery=True,**extra)

    def test_workflow_holds_payload_at_destination(self):
        from test_cellvis24_workflow import WorkflowTests
        import cellvis24_workflow as w
        helper=WorkflowTests();helper.setUp()
        try:
            with patch('cellvis24_rack_route.validate_route',side_effect=validate_route):
                p=w.plan(helper.service,helper.g['cfg'],['hamilton'],1,helper.source,recorded_hamilton_delivery=True)
                result=w.execute(helper.run,helper.service,helper.g['cfg'],p)
            self.assertEqual(json.loads(Path(result['record']).read_text())['payload'],'held')
            self.assertEqual(helper.e1,25)
        finally:helper.doCleanups()

    def test_cli_preview_never_calls_api_and_flags_required(self):
        with patch.object(cli,'api') as api,contextlib.redirect_stdout(io.StringIO()):
            cli.main(['--full-calibration']);api.assert_not_called()
        with self.assertRaises(SystemExit),contextlib.redirect_stderr(io.StringIO()):
            cli.parse_args(['--full-calibration','--execute'])
        with self.assertRaises(SystemExit),contextlib.redirect_stderr(io.StringIO()):
            cli.parse_args(['--from-home','--execute','--path-clear'])

    def test_full_cli_sequence_uses_new_route_after_supported_release(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);receipt=folder/'receipt.json';receipt.write_text('{}')
            events=[]
            def calibrate(args):
                self.assertIn('--continuous',args)
                events.append('calibrate');return dict(trial_id='a'*32,final=dict(record=str(receipt)))
            def phase(ident,name,*args):events.append(name);return dict(record=str(receipt))
            def confirm(message):self.fail('Continuous workflow must not prompt for inspection')
            def delivery(source):events.append('delivery');return dict(record=str(receipt))
            with patch.object(cli,'REPORTS',folder/'runs'),patch.object(cli,'verify_backend'),patch.object(cli,'calibrate_to_scanner',side_effect=calibrate),patch.object(cli,'scanner_phase',side_effect=phase),patch.object(cli,'confirm',side_effect=confirm),patch.object(cli,'delivery',side_effect=delivery),contextlib.redirect_stdout(io.StringIO()):
                result=cli.main(['--full-calibration','--execute','--path-clear'])
            self.assertEqual(events,['calibrate','return_home','release_home','delivery'])
            self.assertNotIn('home_support_confirmed_at',result)
            self.assertEqual(result['home_release_basis'],'accepted_seating_pose_and_runtime_checks')
            self.assertEqual(result['status'],'arrived_hamilton_held_operator_observation_pending')

    def test_declined_home_inspection_never_releases_or_delivers(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);receipt=folder/'receipt.json';receipt.write_text('{}')
            with patch.object(cli,'REPORTS',folder/'runs'),patch.object(cli,'verify_backend'),patch.object(cli,'calibrate_to_scanner',return_value=dict(trial_id='a'*32,final=dict(record=str(receipt)))),patch.object(cli,'scanner_phase',return_value=dict(record=str(receipt))) as phase,patch.object(cli,'confirm',side_effect=RuntimeError('inspection declined')),patch.object(cli,'delivery') as delivery,contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):cli.main(['--full-calibration','--execute','--path-clear','--pause-for-inspection'])
            self.assertEqual(phase.call_count,1);delivery.assert_not_called()

    def test_continuous_scanner_checks_order_and_does_not_invent_observations(self):
        import run_cellvis24_scanner as scanner
        for fail_lift in (False,True):
            with self.subTest(fail_lift=fail_lift),tempfile.TemporaryDirectory() as temp:
                folder=Path(temp);receipt=folder/'receipt.json';receipt.write_text('{}');events=[]
                def grip(*a,**kw):events.append('grip');return receipt
                def lift(*a):
                    events.append('lift')
                    if fail_lift:raise RuntimeError('Proof lift uncertain')
                    return receipt
                def transfer(*a):events.append('scanner');return dict(record=str(receipt))
                with patch.object(scanner,'REPORTS',folder/'runs'),patch.object(scanner,'calibrate',return_value=dict(status='awaiting_open_claw_inspection',record=str(receipt))),patch.object(scanner,'trial_source',return_value=receipt),patch.object(scanner,'grip_trial',side_effect=grip),patch.object(scanner,'proof_lift',side_effect=lift),patch.object(scanner,'scanner_transfer',side_effect=transfer),patch('builtins.input',side_effect=AssertionError('Unexpected inspection prompt')),contextlib.redirect_stdout(io.StringIO()):
                    if fail_lift:
                        with self.assertRaisesRegex(RuntimeError,'Proof lift uncertain'):
                            scanner.main(['--full-calibration','--execute','--continuous'])
                    else:scanner.main(['--full-calibration','--execute','--continuous'])
                record=json.loads(next((folder/'runs').glob('*.json')).read_text())
                self.assertEqual(record['operator_observations'],[])
                self.assertEqual(events,['grip','lift'] if fail_lift else ['grip','lift','scanner'])
                self.assertEqual(record['status'],'stopped_or_uncertain' if fail_lift else 'completed_operator_retention_pending')


if __name__=='__main__':unittest.main()
