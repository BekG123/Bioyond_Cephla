"""48-well adapter integration tests. Fake hardware only."""
import sys
import time
import math
import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import projected_pickup as p
from researcher_descent import ResearcherDescent
from researcher_teaching import TeachingError
from sequences import Runner
from test_transfer import FakeService,PARAMS,check_path
from pick_and_hold.Grip.reference_grip import ReferenceGrip, plan_for_reference

FIXTURE=p.ROOT/'operator_ui/reports/projected_alignment/forward_lower_candidate_profile_20261027.json'


class InwardCorrectionTests(unittest.TestCase):
    def setUp(self):
        active=patch.object(p,'PROFILE',FIXTURE)
        active.start();self.addCleanup(active.stop)

    def test_explicit_trial_authorization_does_not_claim_visual_acceptance(self):
        profile,_=p.load()
        read_evidence=p.evidence
        approval=json.loads(read_evidence(profile['acceptance'],profile['acceptance_sha256']).read_bytes())
        approval.update(visual_alignment_accepted=False,supervised_open_claw_trial_authorized=True)
        def evidence(path,digest):
            if path==profile['acceptance']:
                return Mock(read_bytes=lambda:json.dumps(approval).encode())
            return read_evidence(path,digest)
        with patch.object(p,'evidence',side_effect=evidence):
            loaded,digest=p.load()
            self.assertEqual(loaded['descent_status'],'pending_supervised_open_claw_trial')
            with self.assertRaises(p.TransferError):p.target()
            self.assertTrue(p.target(trial=True)['open_claw_trial'])
            approval['supervised_open_claw_trial_authorized']=False
            with self.assertRaises(p.TransferError):p.load()

    def test_moves_exactly_two_mm_toward_actual_base_without_changing_height_or_yaw(self):
        source=dict(X=294.941,Y=-71.704,Z=78.718,Rz=86.389)
        cfg=dict(base_x_mm=126.,base_y_mm=0.)
        goal=p.inward_endpoint(source,cfg)
        self.assertAlmostEqual(math.hypot(goal['X']-source['X'],goal['Y']-source['Y']),2.)
        before=math.hypot(source['X']-126.,source['Y'])
        after=math.hypot(goal['X']-126.,goal['Y'])
        self.assertAlmostEqual(before-after,2.)
        self.assertEqual((goal['Z'],goal['Rz']),(source['Z'],source['Rz']))
        self.assertEqual(p.inward_endpoint(source,cfg),goal)
        self.assertEqual(source['X'],294.941)

    def test_invalid_or_unreviewed_correction_is_rejected(self):
        source=dict(X=294.941,Y=-71.704,Z=78.718,Rz=86.389)
        cfg=dict(base_x_mm=126.,base_y_mm=0.)
        for distance in (0.,-2.,3.,float('nan')):
            with self.assertRaises(p.TransferError):p.inward_endpoint(source,cfg,distance)
        with self.assertRaises(p.TransferError):
            p.inward_endpoint(dict(source,X=126.,Y=0.),cfg)


class ProjectedPickupTests(unittest.TestCase):
    def setUp(self):
        self.profile,self.digest=p.load(FIXTURE)
        self.profile=deepcopy(self.profile)
        self.profile['descent_status']='pending_supervised_open_claw_trial'
        active=patch.object(p,'load',return_value=(self.profile,self.digest))
        active.start();self.addCleanup(active.stop)
        self.s=FakeService()
        pose=deepcopy(self.profile['alignment_pose_mm'])
        self.s.q=check_path(self.s.pose,pose,self.s.q,PARAMS,self.s.envelope)
        self.s.pose=pose
        self.s.status=lambda:dict(connected=True,ok=True,errors=[],pose_mm=self.s.pose_mm(),joints=self.s.joints())
        self.r=Runner();self.r.name='projected_alignment';self.r.state='done'
        self.r._t0=time.time();self.r.result=dict(ok=True,alignment_pose_reached=True)
        self.completed=Mock();self.prepare=Mock()
        self.d=ResearcherDescent(lambda:self.s,lambda:self.r,lambda:PARAMS,lambda:66,
                                self.prepare,self.completed)
        self.grip=Mock()
        self.adapter=p.ProjectedPickup(self.d,self.grip,lambda:self.s,lambda:self.r,lambda:PARAMS,lambda:66)

    def test_unverified_height_blocks_regular_researcher_descent(self):
        public=self.d.public(self.s.status())
        self.assertFalse(public['can_start'])
        self.assertIn('open-claw trial',public['blocker'])
        with self.assertRaises(p.TransferError):p.target()
        self.assertEqual(self.s.moves,[])

    def test_trial_uses_current_alignment_not_old_two_disk_xy(self):
        t=p.target(trial=True)
        plan=p.descent_plan(self.s.pose,self.s.q,t,PARAMS,self.s.envelope,66)
        self.assertEqual(plan['legs'],[])
        self.assertEqual(plan['endpoint']['X'],self.profile['candidate_endpoint']['X'])
        self.assertEqual(plan['endpoint']['Y'],self.profile['candidate_endpoint']['Y'])
        self.assertAlmostEqual(plan['endpoint']['Z'],self.profile['candidate_endpoint']['Z'])
        self.assertEqual(self.s.moves,[])

    def test_trial_reuses_open_then_lua_and_does_not_prepare_grip(self):
        events=[]
        self.s.move_gripper=lambda *args,**kwargs:(events.append(('open',args[0])) or dict(ok=True,gripper=dict(e1_position=28.)))
        t=p.target(trial=True);plan=p.descent_plan(self.s.pose,self.s.q,t,PARAMS,self.s.envelope,66)
        with patch('researcher_descent.LuaDescent') as lua:
            def execute(*args):
                events.append(('lua',args[1]['z_calibrated']))
                return dict(ok=True,executor='lua_descent',breach=False)
            lua.return_value.execute.side_effect=execute
            result=self.d.execute(self.r,self.s,t,self.s.pose.copy(),plan)
        self.assertTrue(result['ok'],result)
        self.assertEqual(events,[('open',28),('lua',self.profile['candidate_endpoint']['Z'])])
        self.completed.assert_not_called()
        self.assertTrue(result['gripping_height_acceptance_pending'])

    def test_failed_open_prevents_lua(self):
        self.s.move_gripper=lambda *a,**k:dict(ok=True,gripper=dict(e1_position=5.))
        t=p.target(trial=True)
        with patch('researcher_descent.LuaDescent') as lua:
            result=self.d.execute(self.r,self.s,t,self.s.pose.copy())
            lua.assert_not_called()
        self.assertFalse(result['ok']);self.completed.assert_not_called()

    def test_changed_profile_or_pose_blocks_plan(self):
        t=p.target(trial=True)
        with self.assertRaises(p.TransferError):
            p.descent_plan(self.s.pose,self.s.q,dict(t,plate_profile_sha256='changed'),PARAMS,self.s.envelope,66)
        with self.assertRaises(p.TransferError):
            p.descent_plan(dict(self.s.pose,X=self.s.pose['X']+10.),self.s.q,t,PARAMS,self.s.envelope,66)

    def test_trial_requires_confirmations_and_current_profile(self):
        body=dict(ready=True,empty_gripper=True,cell_clear=True,plate_unchanged=True,
                  expected_profile_sha256=self.digest)
        for key in body:
            changed=dict(body);del changed[key]
            with self.assertRaises(TeachingError):self.adapter.start_trial(changed)
        self.assertEqual(self.s.moves,[])

    def test_alignment_success_alone_cannot_be_accepted_as_descent(self):
        with self.assertRaises(TeachingError):self.adapter.accept_descent(dict(visually_accepted=True))
        self.grip.completed_descent.assert_not_called()

    def test_pending_profile_rejects_grip_without_movement(self):
        with self.assertRaises(TeachingError):
            self.adapter.grip_configuration(dict(plate_profile_id=p.PLATE_ID),{},'base')
        self.assertEqual(self.s.moves,[])

    def test_accepted_profile_uses_same_grip_algorithm_at_new_pose(self):
        self.profile['descent_status']='operator_accepted_open_claw_descent'
        result=dict(plate_profile_id=p.PLATE_ID,descent_correction=dict(
            endpoint=self.profile['candidate_endpoint'],profile_sha256=self.digest))
        ref=dict(settings=dict(target_e1_mm=3.8),closure=dict(pose_mm_degrees={'old':True}))
        adapted,digest=self.adapter.grip_configuration(result,ref,'base')
        self.assertEqual(adapted['closure']['pose_mm_degrees'],self.profile['candidate_endpoint'])
        self.assertEqual(adapted['settings'],ref['settings'])
        self.assertEqual(ref['closure']['pose_mm_degrees'],{'old':True})
        self.assertFalse(adapted['physical_grip_validated_for_plate'])
        self.assertNotEqual(digest,'base')

    def test_missing_plate_adapter_cannot_fall_back_to_two_disk(self):
        g=ReferenceGrip.__new__(ReferenceGrip);g.plate_configuration=None
        with patch('pick_and_hold.Grip.reference_grip.configuration',return_value=({},'base')):
            with self.assertRaises(TeachingError):g._configuration(dict(plate_profile_id=p.PLATE_ID))

    def test_accepted_48well_closure_stops_at_3p9_without_changing_two_disk(self):
        baseline=plan_for_reference({})
        reference=dict(plate_profile_id=p.PLATE_ID,accepted_plate_grip=True,
            physical_grip_validated_for_plate=True,settings=dict(target_e1_mm=3.9,closing_speed=5))
        actual=plan_for_reference(reference)
        self.assertEqual(actual['commands'][-1]['target_e1_mm'],3.9)
        self.assertTrue(all(step['target_e1_mm']>=3.9 and step['speed']==5 for step in actual['commands']))
        self.assertEqual(actual['commands'],baseline['commands'][:len(actual['commands'])])
        self.assertEqual(plan_for_reference({}),baseline)
        reference['settings']['target_e1_mm']=3.7
        with self.assertRaises(TeachingError):plan_for_reference(reference)

    def test_accepted_grip_rejects_changed_endpoint_or_evidence(self):
        path=p.ROOT/'Pick and Hold/Grip/accepted_48well_grip_reference.json'
        reference=json.loads(path.read_bytes())
        profile=dict(candidate_endpoint=reference['taught_endpoint'],
            accepted_grip_reference=path.relative_to(p.ROOT).as_posix(),
            accepted_grip_reference_sha256=p.sha(path.read_bytes()))
        self.assertEqual(p.accepted_grip(profile)['settings']['target_e1_mm'],3.9)
        changed=deepcopy(profile);changed['candidate_endpoint']['X']+=1
        with self.assertRaises(p.TransferError):p.accepted_grip(changed)
        changed=deepcopy(profile);changed['accepted_grip_reference_sha256']='changed'
        with self.assertRaises(p.TransferError):p.accepted_grip(changed)

if __name__=='__main__':unittest.main()
