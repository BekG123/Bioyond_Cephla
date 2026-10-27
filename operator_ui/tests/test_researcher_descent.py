"""Researcher descent routing and open-before-lower checks; fake robot only."""
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_transfer import FakeService, PARAMS, check_path
from sequences import Runner
from researcher_descent import ResearcherDescent
from researcher_teaching import TeachingError


class DescentTests(unittest.TestCase):
    def setUp(self):
        # Stable fixture: runtime endpoint is operator-taught and can change.
        from pick_and_hold.Descend import correction
        profile=Path(__file__).resolve().parents[1]/'demonstrations/descent_endpoint_adjustment_20261017T103806Z/previous_profile.json'
        profile_patch=patch.object(correction,'PROFILE',profile)
        profile_patch.start();self.addCleanup(profile_patch.stop)
        self.service=FakeService()
        pose=dict(X=299.39,Y=-69.555,Z=300.,Rz=85.)
        self.service.q=check_path(self.service.pose,pose,self.service.q,PARAMS,self.service.envelope)
        self.service.pose=pose
        self.service.rotate_to_rz=lambda rz,speed=30,force_delta=None:self.service.move_cartesian(self.service.pose['X'],self.service.pose['Y'],self.service.pose['Z'],rz,speed)
        self.service.status=lambda:dict(connected=True,ok=True,errors=[],pose_mm=self.service.pose_mm(),joints=self.service.joints())
        self.run=Runner();self.run.name='researcher_align';self.run.state='done'
        self.run.result={'ok':True};self.run._t0=time.time()
        self.run.target=dict(x=299.39,y=-69.555,rz=85.,z_calibrated=71.37,config='Wide')
        self.events=[]
        self.open_result={'ok':True,'gripper':{'e1_position':28.0}}
        def opening(*args,**kwargs):
            self.events.append('open')
            return self.open_result
        self.service.move_gripper=opening
        self.prepare=Mock()
        self.action=ResearcherDescent(lambda:self.service,lambda:self.run,lambda:PARAMS,lambda:66,self.prepare)

    def execute(self):
        with patch('researcher_descent.LuaDescent') as lua:
            def descend(*args,**kwargs):
                self.events.append('descend');return dict(ok=True,breach=False)
            lua.return_value.execute.side_effect=descend
            return self.action.execute(self.run,self.service,self.run.target,self.service.pose.copy())

    def test_poll_is_read_only_and_align_required(self):
        self.assertTrue(self.action.public(self.service.status())['can_start'])
        self.run.name='grip'
        self.assertFalse(self.action.public(self.service.status())['can_start'])
        self.assertEqual(self.events,[]);self.prepare.assert_not_called()

    def test_expired_alignment_blocked(self):
        self.run._t0-=601
        self.assertFalse(self.action.public(self.service.status())['can_start'])

    def test_moved_pose_and_bottom_blocked(self):
        self.service.pose['X']+=5
        self.assertFalse(self.action.public(self.service.status())['can_start'])
        self.service.pose['X']-=5;self.service.pose['Z']=71.37
        self.assertFalse(self.action.public(self.service.status())['can_start'])

    def test_confirmation_required(self):
        with self.assertRaises(TeachingError):self.action.start({})
        self.assertEqual(self.events,[])

    def test_preview_projects_alignment_without_moving(self):
        start=dict(X=294.,Y=22.,Z=285.,Rz=4.)
        self.service.q=check_path(self.service.pose,start,self.service.q,PARAMS,self.service.envelope)
        self.service.pose=start
        plan=self.action.preview_after_alignment(self.run.target)
        self.assertGreaterEqual(plan['hover']['Z'],300)
        self.assertEqual(self.service.pose,start)
        self.assertEqual(self.events,[])
        self.assertEqual(self.service.moves,[])

    def test_unused_raw_depth_outside_workspace_does_not_block_valid_taught_depth(self):
        self.service.envelope['Z']=(70,400)
        self.run.target['z_calibrated']=69.0  # Within 2 mm of taught 70.467.
        plan=self.action.preview_after_alignment(self.run.target)
        self.assertAlmostEqual(plan['endpoint']['Z'],70.467,places=3)
        self.assertEqual(self.events,[])

    def test_open_verified_before_lua(self):
        self.assertTrue(self.execute()['ok'])
        self.assertEqual(self.events,['open','descend'])
        self.assertTrue(self.service.moves)
        self.assertTrue(all(p[2]>=300 for p in self.service.moves))
        self.assertEqual(self.run.target['x'],300.086)
        self.assertEqual(self.run.target['z_calibrated'],70.467)

    def test_correction_is_absolute_and_not_applied_twice(self):
        from pick_and_hold.Descend.correction import corrected_plan
        first=corrected_plan(self.service.pose,self.service.q,self.run.target,PARAMS,self.service.envelope,66)
        self.assertEqual(first['target']['x'],300.086)
        goal=dict(X=300.086,Y=-67.933,Z=300.,Rz=85.751)
        q=check_path(self.service.pose,goal,self.service.q,PARAMS,self.service.envelope)
        again=corrected_plan(goal,q,first['target'],PARAMS,self.service.envelope,66)
        self.assertEqual(again['legs'],[])
        self.assertEqual(again['target']['x'],300.086)

    def test_encoder_rounding_does_not_change_leg_type(self):
        from pick_and_hold.Descend.correction import corrected_plan, apply_correction
        plan=corrected_plan(self.service.pose,self.service.q,self.run.target,PARAMS,self.service.envelope,66)
        self.service.pose['X']+=.001
        self.service.pose['Rz']+=.001
        apply_correction(self.run,self.service,plan,PARAMS)
        self.assertAlmostEqual(self.service.moves[0][0],plan['start']['X']+.001)
        self.assertAlmostEqual(self.service.pose['X'],300.086)

    def test_real_drift_and_mixed_rotation_leg_are_refused(self):
        from copy import deepcopy
        from autonomy import TransferError
        from pick_and_hold.Descend.correction import corrected_plan, apply_correction
        plan=corrected_plan(self.service.pose,self.service.q,self.run.target,PARAMS,self.service.envelope,66)
        self.service.pose['X']+=.1
        with self.assertRaisesRegex(TransferError,'Arm moved'):
            apply_correction(self.run,self.service,plan,PARAMS)
        self.service.pose=deepcopy(plan['start'])
        plan['legs'][0]['X']+=.1
        with self.assertRaisesRegex(TransferError,'hold XYZ fixed'):
            apply_correction(self.run,self.service,plan,PARAMS)
        self.assertEqual(self.service.moves,[])

    def test_low_correction_or_different_plate_region_refused(self):
        self.service.pose['Z']=200
        self.assertFalse(self.action.public(self.service.status())['can_start'])
        self.service.pose['Z']=300
        self.run.target['x']+=15;self.service.pose['X']+=15
        self.assertFalse(self.action.public(self.service.status())['can_start'])
        self.assertEqual(self.service.moves,[])

    def test_unconfirmed_correction_prevents_open_and_descent(self):
        self.service.motion_failure='recovered'
        self.assertFalse(self.execute()['ok'])
        self.assertEqual(self.events,[])

    def test_stop_during_correction_prevents_open_and_descent(self):
        move=self.service.move_cartesian
        def stopped(*args,**kwargs):
            result=move(*args,**kwargs);self.run.request_stop();return result
        self.service.move_cartesian=stopped
        self.assertFalse(self.execute()['ok'])
        self.assertEqual(self.events,[])

    def test_invalid_corrected_endpoint_checked_before_motion(self):
        self.service.envelope['Z']=(71.,400.)
        self.assertFalse(self.execute()['ok'])
        self.assertEqual(self.events,[]);self.assertEqual(self.service.moves,[])

    def test_failed_or_unconfirmed_open_never_descends(self):
        for result in ({'ok':False},{'ok':True,'gripper':{'e1_position':27}},
                       {'ok':True,'gripper':{'e1_position':float('nan')}},
                       {'ok':True,'recovered':'uncertain','gripper':{'e1_position':28}}):
            with self.subTest(result=result):
                self.events.clear();self.open_result=result
                self.assertFalse(self.execute()['ok'])
                self.assertEqual(self.events,['open'])

    def test_stop_after_open_prevents_descent(self):
        def opening(*args,**kwargs):
            self.events.append('open');self.run.stop_event.set();return self.open_result
        self.service.move_gripper=opening
        self.assertFalse(self.execute()['ok'])
        self.assertEqual(self.events,['open'])

    def test_stop_api_bypasses_busy_dispatch_guard(self):
        from test_researcher import console
        with patch.object(console.runner,'_thread',Mock(is_alive=lambda:True)), \
                patch.object(console.researcher_descent,'stop',return_value={'ok':True}) as stop:
            response=console.app.test_client().post('/researcher/api/descent/stop',json={})
            self.assertEqual(response.status_code,200)
            stop.assert_called_once()

    def test_start_api_routes_without_haiku(self):
        from test_researcher import console
        with patch.object(console.researcher_descent,'start',return_value={'ok':True}) as start:
            response=console.app.test_client().post('/researcher/api/descent/start',json={'ready':True})
            self.assertEqual(response.status_code,200)
            start.assert_called_once_with({'ready':True})


if __name__=='__main__':unittest.main()
