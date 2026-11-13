"""Offline commissioning regressions; no controller connections or movement."""
import copy
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hamilton_48_dcg_plan import STAGES,actions,verify_plan,digest,validated_frame,assert_bounds
from hamilton_48_dcg_pipeline import (compile_action,check_transition,save_owned,pose_matches,
    consistent_source_samples,archive_unstarted,check_reopen_pose,stage_actions,measured_release_action,temporal_median,run_stage,
    measured_coordinated_action,coordinated_goal)
from hamilton_48_dcg_repeat import leg_plan,accepted_reference,measured_pickup_plan,resume_plan

PLAN_FILE=ROOT/'reports/hamilton_api/plate_offset_20261108T112943Z/staged_transfer_plan.json'

class CommissioningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan=json.loads(PLAN_FILE.read_text())

    def test_saved_plan_reproduces_evidence(self):
        verify_plan(self.plan)
        p=self.plan
        self.assertEqual(p['profile']['labware_id'],166)
        self.assertAlmostEqual(p['grip_z_mm'],17.19,places=3)
        self.assertAlmostEqual(p['source_top_mm'][2],24.19,places=3)
        self.assertAlmostEqual(p['profile']['plate']['grip_body_width_mm'],82.11818,places=4)

    def test_coordinated_release_preserves_measured_xy_through_both_lifts(self):
        from hamilton_dcg_transfer import C
        base=copy.deepcopy(self.plan);base.update(release_mode='coordinated_open_retreat',release_outward_mm=10)
        for site in (3,4):
            p=leg_plan(base,site);seq=stage_actions(p,'release_return')
            self.assertEqual([s['command'] for s in seq],['Slow','CoordinatedOpen','CoordinatedLift','CoordinatedClearance','ReleaseAbovePlate','Fast','DropTool','Park'])
            x,y,_=p['destination_top_mm']
            pos={'positions':[dict(channel=c,position_x=x,position_y=y+sign*40.559,position_z=p['grip_z_mm']) for c,sign in ((1,1),(2,-1))]}
            opening=measured_coordinated_action(seq[1],pos,p['native_bounds'],p['grip_z_mm'])
            self.assertAlmostEqual(opening['y'][1],y+50.559)
            self.assertAlmostEqual(opening['y'][2],y-50.559)
            for action in seq[1:4]:
                a=measured_coordinated_action(action,pos,p['native_bounds'],p['grip_z_mm'])
                self.assertEqual(a['y'],opening['y'])
                self.assertIsInstance(compile_action(p,a),C.PrepMoveToPosition)
                pos={'positions':[dict(channel=c,**v) for c,v in coordinated_goal(a).items()]}
            self.assertEqual(pos['positions'][0]['position_z'],165)

    def test_coordinated_open_rejects_unseated_or_out_of_bounds(self):
        p=copy.deepcopy(self.plan);p.update(release_mode='coordinated_open_retreat',release_outward_mm=10)
        a=stage_actions(p,'release_return')[1]
        pos={'positions':[dict(channel=c,position_x=50,position_y=100-sign*10,position_z=p['grip_z_mm']+1) for c,sign in ((1,1),(2,-1))]}
        with self.assertRaisesRegex(RuntimeError,'seated'):measured_coordinated_action(a,pos,p['native_bounds'],p['grip_z_mm'])
        for row in pos['positions']:row['position_z']=p['grip_z_mm'];row['position_y']=-20 if row['channel']==2 else 100
        with self.assertRaisesRegex(RuntimeError,'bounds'):measured_coordinated_action(a,pos,p['native_bounds'],p['grip_z_mm'])

    def test_unresolved_jaw_reversal_blocks_before_hardware_access(self):
        p=copy.deepcopy(self.plan);p['release_mode']='separate_open_retreat'
        for stage in STAGES:
            with self.assertRaisesRegex(RuntimeError,'front-jaw reversal'):
                asyncio.run(run_stage(None,p,stage,{},True))

    def test_loaded_coordinated_release_stop_blocks_before_hardware_access(self):
        p=copy.deepcopy(self.plan);p['release_mode']='coordinated_open_retreat'
        for stage in STAGES:
            with self.assertRaisesRegex(RuntimeError,'raised both jaws before opening'):
                asyncio.run(run_stage(None,p,stage,{},True))

    def test_temporal_median_removes_transient_noise_without_spatial_warp(self):
        image=np.full((20,30),40,dtype=np.uint8);image[3:17,8:22]=180
        frames=[image.copy() for _ in range(5)]
        frames[0][4,9]=255;frames[1][4,9]=0
        np.testing.assert_array_equal(temporal_median(frames),image)
        with self.assertRaises(ValueError):temporal_median(frames[:4])
        frames[0]=np.zeros((10,10),dtype=np.uint8)
        with self.assertRaises(ValueError):temporal_median(frames)

    def test_ten_mm_release_is_measured_per_jaw_and_keeps_pickup_unchanged(self):
        p=copy.deepcopy(self.plan);p.update(release_mode='separate_open_retreat',release_outward_mm=10)
        for site in (3,4):
            leg=leg_plan(p,site);step=stage_actions(leg,'release_return')[1]
            y=leg['destination_top_mm'][1]
            pos={'positions':[dict(channel=1,position_y=y+40),dict(channel=2,position_y=y-40)]}
            action=measured_release_action(step,pos,p['native_bounds'])
            self.assertAlmostEqual(action['y'][1],y+50)
            self.assertAlmostEqual(action['y'][2],y-50)
            compile_action(leg,action).build_parameters().build()
            self.assertEqual(stage_actions(leg,'pickup_lift'),stage_actions(leg_plan(self.plan,site),'pickup_lift'))
        p['release_outward_mm']=11
        with self.assertRaises(ValueError):stage_actions(p,'release_return')

    def test_separate_release_opens_then_retreats_before_native_release(self):
        base=copy.deepcopy(self.plan);base['release_mode']='separate_open_retreat'
        for site in (3,4):
            p=leg_plan(base,site);steps=stage_actions(p,'release_return')
            self.assertEqual([s['command'] for s in steps],['Slow','OpenAtSeat','LiftOpen','RaiseToSafe','ReleaseAbovePlate','Fast','DropTool','Park'])
            self.assertEqual(steps[1]['outward_mm'],6)
            self.assertAlmostEqual((steps[1]['y'][1]+steps[1]['y'][2])/2,p['destination_top_mm'][1])
            self.assertEqual(steps[2]['z'],p['grip_z_mm']+10)
            self.assertEqual(steps[2]['speed'],1)
            for step in steps:compile_action(p,step).build_parameters().build()
            self.assertEqual(p['destination_top_mm'],leg_plan(self.plan,site)['destination_top_mm'])
            positions={'positions':[dict(channel=1,position_y=p['destination_top_mm'][1]+40),dict(channel=2,position_y=p['destination_top_mm'][1]-40)]}
            measured=measured_release_action(steps[1],positions,p['native_bounds'])
            self.assertAlmostEqual(measured['y'][1]-positions['positions'][0]['position_y'],6)
            self.assertAlmostEqual(measured['y'][2]-positions['positions'][1]['position_y'],-6)
            positions['positions'][0]['position_y']=1000
            with self.assertRaises(ValueError):measured_release_action(steps[1],positions,p['native_bounds'])

    def test_roundtrip_preserves_both_original_positions_without_accumulating_offset(self):
        base=accepted_reference(PLAN_FILE)
        for _ in range(5):
            reverse=leg_plan(base,3);forward=leg_plan(base,4)
            self.assertEqual(reverse['source_top_mm'],base['destination_top_mm'])
            self.assertEqual(reverse['destination_top_mm'],base['source_top_mm'])
            self.assertEqual(forward['destination_top_mm'],reverse['source_top_mm'])
            self.assertEqual(forward['source_top_mm'],reverse['destination_top_mm'])
            self.assertNotEqual(reverse['destination_top_mm'],base['nominal_source_top_mm'])

    def test_measured_pickup_never_changes_dropoff_target(self):
        old=leg_plan(self.plan,3)
        m=dict(native_center_mm=[old['source_top_mm'][0]-.1,old['source_top_mm'][1]-.53,24.19])
        new=measured_pickup_plan(self.plan,3,m)
        self.assertEqual(new['destination_top_mm'],self.plan['source_top_mm'])
        self.assertNotEqual(new['source_top_mm'],old['source_top_mm'])
        m['native_center_mm'][0]+=5
        with self.assertRaises(RuntimeError):measured_pickup_plan(self.plan,3,m)

    def test_resume_release_widens_only_release_and_preserves_pickup_and_endpoints(self):
        m=dict(native_center_mm=self.plan['destination_top_mm'])
        p=measured_pickup_plan(self.plan,3,m)
        ticket=dict(action='falcon48_staged_dcg',plan_sha256=self.plan['plan_sha256'],status='awaiting_site4_seating_inspection',
            rounds_requested=5,cycle=1,source_site=3,next_stage='release_return',transfers_completed=0,rounds_completed=0,pending_plan=p)
        revised=resume_plan(self.plan,ticket,5,6)
        release=compile_action(revised,actions(revised,'release_return')[1])
        pickup=compile_action(revised,actions(revised,'pickup_lift')[1])
        self.assertEqual(release.clearance_y,6)
        self.assertEqual(pickup.clearance_y,4)
        self.assertEqual(revised['destination_top_mm'],self.plan['source_top_mm'])
        ticket['status']='failed_or_uncertain'
        with self.assertRaises(RuntimeError):resume_plan(self.plan,ticket,5,6)

    def test_all_stages_encode_without_hardware(self):
        for stage in STAGES:
            for action in actions(self.plan,stage):
                self.assertIsInstance(compile_action(self.plan,action).build_parameters().build(),bytes)

    def test_hover_cannot_grip_or_release(self):
        a=actions(self.plan,'hover')
        self.assertEqual(a[-1]['command'],'OpenMove')
        self.assertEqual(a[-1]['z'],80)
        self.assertFalse({'PickupPlate','DropPlate'} & {x['command'] for x in a})

    def test_proof_lift_is_vertical_five_mm(self):
        a=actions(self.plan,'pickup_lift')
        np.testing.assert_allclose(a[-1]['top'],np.asarray(self.plan['source_top_mm'])+[0,0,5])

    def test_seating_holds_until_separate_release_stage(self):
        a=actions(self.plan,'transfer_seat')
        self.assertNotIn('DropPlate',[v['command'] for v in a])
        self.assertEqual(a[-1]['top'],self.plan['destination_top_mm'])
        self.assertNotEqual(a[-1]['top'][0],self.plan['source_top_mm'][0])
        self.assertEqual(actions(self.plan,'release_return')[1]['command'],'DropPlate')

    def test_cannot_skip_inspection_or_replay_uncertain_stage(self):
        for stage in STAGES[1:]:
            with self.assertRaises(RuntimeError):check_transition(None,self.plan,stage)
        s=dict(action='falcon48_staged_dcg',plan_sha256=self.plan['plan_sha256'],
               status='awaiting_inspection',next_stage='pickup_lift')
        check_transition(s,self.plan,'pickup_lift')
        for stage in ('hover','transfer_seat','release_return'):
            with self.assertRaises(RuntimeError):check_transition(s,self.plan,stage)
        s['status']='failed_or_uncertain'
        with self.assertRaises(RuntimeError):check_transition(s,self.plan,'pickup_lift')

    def test_evidence_rebuild_rejects_edited_speed_even_if_rehashed(self):
        p=copy.deepcopy(self.plan);p['fast_scale']=100;p.pop('plan_sha256');p['plan_sha256']=digest(p)
        with self.assertRaisesRegex(ValueError,'fast_scale'):verify_plan(p)

    def test_frame_refits_instead_of_trusting_cached_matrix(self):
        report=json.loads(Path(self.plan['frame_file']).read_text())
        a=validated_frame(report,self.plan['camera_calibration_sha256'])
        report['frame_fit']['translation_mm']=[999,999,999]
        b=validated_frame(report,self.plan['camera_calibration_sha256'])
        np.testing.assert_allclose(a['translation_mm'],b['translation_mm'])
        report['serial']='wrong'
        with self.assertRaises(ValueError):validated_frame(report,self.plan['camera_calibration_sha256'])

    def test_out_of_bounds_open_jaw_is_rejected(self):
        p=copy.deepcopy(self.plan);p['source_top_mm'][1]=-10
        with self.assertRaises(ValueError):assert_bounds(p,p['native_bounds'])

    def test_owned_marker_cannot_clobber_other_operation(self):
        with tempfile.TemporaryDirectory() as folder:
            marker=Path(folder)/'active.json'
            ticket=dict(request_id='a',action='falcon48_staged_dcg')
            save_owned(marker,ticket,create=True)
            with self.assertRaises(FileExistsError):save_owned(marker,dict(ticket,request_id='b'),create=True)
            with self.assertRaises(RuntimeError):save_owned(marker,dict(ticket,request_id='b'))
            self.assertEqual(json.loads(marker.read_text())['request_id'],'a')

    def test_resume_rejects_changed_position_or_nan(self):
        p=dict(positions=[dict(channel=1,position_x=1,position_y=2,position_z=3),
                          dict(channel=2,position_x=1,position_y=4,position_z=3)])
        self.assertTrue(pose_matches(p,p))
        for x in (2,float('nan')):
            changed=copy.deepcopy(p);changed['positions'][0]['position_x']=x
            self.assertFalse(pose_matches(changed,p))

    def test_two_good_exposures_required_and_no_outlier_discard(self):
        s=dict(native_center_mm=self.plan['source_top_mm'])
        consistent_source_samples([s,s],self.plan)
        with self.assertRaises(RuntimeError):consistent_source_samples([s],self.plan)
        bad=dict(native_center_mm=[self.plan['source_top_mm'][0]+1,*self.plan['source_top_mm'][1:]])
        with self.assertRaises(RuntimeError):consistent_source_samples([s,s,bad],self.plan)

    def test_explicit_reopen_only_changes_empty_jaw_spacing_at_hover(self):
        target=actions(self.plan,'hover')[-1]
        initial=dict(plate_held=False,tool=dict(value=dict(label='DCG')),positions=dict(positions=[
            dict(channel=c,position_x=target['x'],position_y=target['y'][c],position_z=80) for c in (1,2)]))
        checkpoint=copy.deepcopy(initial)
        initial['positions']['positions'][1]['position_y']=55.91
        check_reopen_pose(initial,checkpoint,self.plan)
        seq=stage_actions(self.plan,'pickup_lift',True)
        self.assertEqual(seq[1],target)
        for field,value in (('position_z',20),('position_x',100),('position_y',100)):
            bad=copy.deepcopy(initial);bad['positions']['positions'][1][field]=value
            with self.assertRaises(RuntimeError):check_reopen_pose(bad,checkpoint,self.plan)
        initial['plate_held']=True
        with self.assertRaises(RuntimeError):check_reopen_pose(initial,checkpoint,self.plan)
        with self.assertRaises(ValueError):stage_actions(self.plan,'transfer_seat',True)

    def test_unstarted_archive_never_resolves_controller_write(self):
        with tempfile.TemporaryDirectory() as folder:
            h=SimpleNamespace(folder=Path(folder));marker=h.folder/'active.json'
            t=dict(request_id='test',action='falcon48_staged_dcg',plan_sha256=self.plan['plan_sha256'],write_attempted=False)
            marker.write_text(json.dumps(t));journal=h.folder/'test.jsonl'
            journal.write_text(json.dumps(dict(kind='native_request')))
            with self.assertRaises(RuntimeError):archive_unstarted(h,self.plan)
            self.assertTrue(marker.exists())
            journal.write_text(json.dumps(dict(kind='stage_begin')))
            archive_unstarted(h,self.plan)
            self.assertFalse(marker.exists())
            self.assertFalse(json.loads((h.folder/'test_not_started.json').read_text())['motion_sent'])

if __name__=='__main__':unittest.main()
