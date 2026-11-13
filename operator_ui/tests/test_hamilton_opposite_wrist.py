"""New route through real Lua with fake hardware; no robot connection."""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from autonomy import TransferError,wrap
from cellvis24_recorded_hamilton_route import reference,plan_path,validate_shape
from cellvis24_workflow import compile_steps,validate_steps
from hamilton_transit_blend import BlendedTransitTrajectory,ROUNDED_ZONES
Z77_ZONES=ROUNDED_ZONES['forward']
from trajectory_queue import LuaTrajectory
from build_rounded_transit_program import SOURCE,candidate_lua,build as build_archive
from test_trajectory_queue import Controller
import test_hamilton_transit_blend as blend_tests
import run_cellvis24_recorded_hamilton as cli


class OppositeWristTests(unittest.TestCase):
    def setup_route(self,new=True):
        h,s,_,_=blend_tests.TransitBlendTests().setup_route()
        p=reference('opposite3');r=p['routes']['forward']
        s.pose=deepcopy(r['start']);s.q=deepcopy(r['start_joints'])
        if new:
            with zipfile.ZipFile(SOURCE) as z:src=z.read('main/mod_Trajectory.lua').decode('utf-8-sig')
            s.robot=Controller(s,source=candidate_lua(src))
        return h,s,p,r

    def execute(self,h,s,p,r):
        return BlendedTransitTrajectory(s).execute(h.run,s.pose,s.q,r['points'],p['config'],137,lambda *a:None,
            reviewed=True,hamilton_short_side='cellvis24_opposite_forward',segment_speeds=r['segment_speeds'],transit_blend=True)

    def test_real_published_lua_one_queue_positive_wrist_and_wrapped_feedback(self):
        h,s,p,r=self.setup_route();finish=s.robot.finish
        def wrapped_finish():
            finish();s.pose['Rz']=wrap(s.pose['Rz'])
        s.robot.lua.globals().MOVFINISH=wrapped_finish
        result=self.execute(h,s,p,r)
        self.assertTrue(result['ok']);self.assertEqual(s.robot.barriers,1)
        self.assertEqual(len(s.robot.calls),6)
        self.assertEqual([c[2] for c in s.robot.calls],list(Z77_ZONES))
        self.assertEqual([c[1] for c in s.robot.calls],[137]*5+[5])
        self.assertEqual([round(c[0][5],2) for c in s.robot.calls],[87.88,175.75,245.85,245.85,266.98,266.98])
        self.assertEqual([round(c[0][2],2) for c in s.robot.calls],[118.15]*3+[77.,77.,53.72])
        self.assertAlmostEqual(s.q['J4'],163.51127,places=3)
        self.assertAlmostEqual(s.pose['Rz'],-93.02,places=3)
        self.assertEqual(s.grips,[])

    def test_wrong_terminal_joint_winding_rejected_even_when_pose_matches(self):
        h,s,p,r=self.setup_route();finish=s.robot.finish
        def wrong_finish():
            finish();s.pose['Rz']=wrap(s.pose['Rz']);s.q['J4']-=360
        s.robot.lua.globals().MOVFINISH=wrong_finish
        with self.assertRaisesRegex(TransferError,'joint'):
            self.execute(h,s,p,r)

    def test_no_shortcut_or_old_winding_can_replace_pinned_points(self):
        _,_,p,r=self.setup_route()
        for kind in ('delete','yaw','height'):
            pts=deepcopy(r['points'])
            if kind=='delete':pts.pop(1)
            if kind=='yaw':pts[-1]['Rz']-=360
            if kind=='height':pts[1]['Z']-=1
            with self.assertRaises(TransferError):validate_shape(r['start'],pts,'cellvis24_opposite_forward')
        self.assertEqual(validate_shape(r['points'][-1],p['routes']['reverse']['points'],'cellvis24_opposite_reverse'),p['routes']['reverse'])

    def test_reverse_queue_with_wrapped_start_preserves_winding_and_slow_departure(self):
        h,s,p,_=self.setup_route();r=p['routes']['reverse']
        s.pose=deepcopy(r['start']);s.pose['Rz']=wrap(s.pose['Rz']);s.q=deepcopy(r['start_joints'])
        result=LuaTrajectory(s).execute(h.run,s.pose,s.q,r['points'],p['config'],137,lambda *a:None,
            reviewed=True,hamilton_short_side='cellvis24_opposite_reverse',segment_speeds=r['segment_speeds'])
        self.assertTrue(result['ok']);self.assertEqual(s.robot.barriers,1)
        self.assertEqual([c[1] for c in s.robot.calls],[5]+[137]*5)
        self.assertEqual([c[2] for c in s.robot.calls],[-1]*6)
        self.assertAlmostEqual(s.q['J4'],p['routes']['forward']['start_joints']['J4'],places=3)
        self.assertEqual(s.grips,[])

    def test_three_travel_targets_and_separate_lift_descent(self):
        p=reference('opposite3');r=p['routes']['forward']
        self.assertEqual(len(p['transit_targets']),3);self.assertEqual(len(r['points']),6)
        self.assertEqual(r['points'][0]['Rz'],r['start']['Rz'])
        self.assertEqual({q['Z'] for q in r['points'][:3]},{118.15})
        self.assertEqual([q['Z'] for q in r['points'][-3:]],[77.,77.,53.72])
        self.assertEqual({k:v for k,v in r['points'][2].items() if k!='Z'},
                         {k:v for k,v in r['points'][3].items() if k!='Z'})
        steps=compile_steps(['hamilton'],1,recorded_hamilton_delivery=True,recorded_hamilton_variant='opposite3')
        self.assertEqual(steps[-1]['points'],r['points'])
        self.assertEqual(steps[-1]['flags']['hamilton_short_side'],'cellvis24_opposite_forward')
        self.assertTrue(steps[-1]['flags']['transit_blend'])
        env={k:(p['global_envelope'][k]['min'],p['global_envelope'][k]['max']) for k in ('X','Y','Z')}
        final=validate_steps([steps[-1]],dict(pose_mm=r['start'],joints=r['start_joints']),p['config'],env)
        self.assertGreater(final['joints']['J4'],160)

    def test_cli_read_only_preview_and_continuous_execution_selection(self):
        out=io.StringIO()
        with patch.object(cli,'api') as api,contextlib.redirect_stdout(out):
            cli.main(['--full-calibration','--opposite-wrist'])
        api.assert_not_called();preview=json.loads(out.getvalue())
        self.assertEqual(preview['variant'],'opposite3');self.assertEqual(preview['queue_targets'],6)
        self.assertEqual(len(preview['transit_targets']),3)
        self.assertFalse(preview['inspection_pauses'])
        self.assertEqual(preview['publish_required'],220114)
        self.assertEqual(preview['segment_zones'],list(Z77_ZONES))
        with tempfile.TemporaryDirectory() as temp:
            f=Path(temp);receipt=f/'receipt.json';receipt.write_text('{}')
            with patch.object(cli,'REPORTS',f/'runs'),patch.object(cli,'verify_backend') as verify,patch.object(cli,'calibrate_to_scanner',return_value=dict(trial_id='a'*32,final=dict(record=str(receipt)))),patch.object(cli,'scanner_phase',return_value=dict(record=str(receipt))),patch.object(cli,'delivery',return_value=dict(record=str(receipt))) as delivery,patch('builtins.input',side_effect=AssertionError('No inspection pause')),contextlib.redirect_stdout(io.StringIO()):
                cli.main(['--full-calibration','--opposite-wrist','--execute','--path-clear'])
            verify.assert_called_once_with('opposite3');delivery.assert_called_once_with(receipt,'opposite3')

    def test_new_capability_required_before_calibration(self):
        digest=hashlib.sha256(plan_path('opposite3').read_bytes()).hexdigest()
        def api(path,*args):
            if path.endswith('capabilities'):return dict(recorded_hamilton_delivery=True,recorded_route_variants={'opposite3':digest})
            self.assertEqual(args,({'variant':'opposite3'},))
            return dict(blended_transit_capability=220112)
        with patch.object(cli,'api',side_effect=api),patch.object(cli,'reconnect'),patch.object(cli,'calibrate_to_scanner') as calibrate:
            with self.assertRaisesRegex(RuntimeError,'capability not verified'):
                cli.main(['--full-calibration','--opposite-wrist','--execute','--path-clear'])
            calibrate.assert_not_called()

    def test_stale_backend_rejected_before_calibration(self):
        with patch.object(cli,'api',return_value=dict(recorded_hamilton_delivery=True,recorded_route_variants={'opposite3':'old'})),patch.object(cli,'calibrate_to_scanner') as calibrate:
            with self.assertRaisesRegex(RuntimeError,'Backend route differs'):
                cli.main(['--full-calibration','--opposite-wrist','--execute','--path-clear'])
            calibrate.assert_not_called()

    def test_blend_flag_cannot_send_new_vertical_corner_to_old_blend_protocol(self):
        h,s,p,r=self.setup_route(new=False)
        with self.assertRaisesRegex(TransferError,'220114'):
            self.execute(h,s,p,r)
        self.assertEqual(s.robot.calls,[])

    def test_lua_rejects_early_lowering_rotation_and_bad_zone(self):
        for change in ('early_lower','early_yaw','corner','speed','checksum'):
            h,s,p,r=self.setup_route();pts=deepcopy(r['points']);zones=list(Z77_ZONES);speeds=list(r['segment_speeds'])
            if change=='early_lower':pts[2]['Z']=77
            if change=='early_yaw':pts[3]['Rz']=266.98
            if change=='corner':zones[3]=1
            if change=='speed':speeds[-1]=137
            with self.assertRaises(TransferError):
                blend_tests.TransitBlendTests().upload(s,r,points=pts,zones=zones,speeds=speeds,bad_checksum=change=='checksum')
            self.assertEqual(s.robot.calls,[])

    def test_old_blended_route_on_new_lua(self):
        h,s,_,_=self.setup_route();p=reference('smooth3');r=p['routes']['forward']
        s.pose=deepcopy(r['start']);s.q=deepcopy(r['start_joints'])
        result=blend_tests.TransitBlendTests().execute(h,s,p,r)
        self.assertTrue(result['ok']);self.assertEqual(s.robot.barriers,1)
        self.assertEqual([c[2] for c in s.robot.calls],[-1,1,1,-1,-1,-1])

    def test_regular_mixed_speed_queue_on_new_lua(self):
        h,s,p,r=self.setup_route()
        result=LuaTrajectory(s).execute(h.run,s.pose,s.q,r['points'],p['config'],137,lambda *a:None,
            reviewed=True,hamilton_short_side='cellvis24_opposite_forward',segment_speeds=r['segment_speeds'])
        self.assertTrue(result['ok']);self.assertEqual(s.robot.barriers,1)
        self.assertEqual([c[2] for c in s.robot.calls],[-1]*6)

    def test_archive_only_updates_existing_trajectory_module(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'test.bin';build_archive(output=output)
            with zipfile.ZipFile(SOURCE) as a,zipfile.ZipFile(output) as b:
                self.assertEqual(a.namelist(),b.namelist())
                self.assertEqual([name for name in a.namelist() if a.read(name)!=b.read(name)],['main/mod_Trajectory.lua'])
                self.assertEqual(b.read('main/mod_Trajectory.lua').decode().count('MOVFINISH()'),1)


if __name__=='__main__':unittest.main()
