"""Real reviewed path through Lua 5.1 fake hardware; isolated one-run permission."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from recorded_return import RecordedReturn
from researcher_teaching import TeachingError
from trajectory_queue import prepare_points,LuaTrajectory
from autonomy import TransferError
from test_transfer import FakeService
from test_researcher_workflow import FakeRunner
from test_trajectory_queue import Controller

HERE=Path(__file__).resolve().parents[1]


class PrunedReplayTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.folder=self.root/'demonstrations/source';self.folder.mkdir(parents=True)
        source=HERE/'demonstrations/return_home_20261016_130748'
        if not (source/'return_path.json').exists():self.skipTest('Local recording unavailable')
        for name in ('return_path.json','samples.jsonl','replay_permission.json'):shutil.copyfile(source/name,self.folder/name)
        self.review=self.root/'reports/trajectory_smoothing/pruned_middle';self.review.mkdir(parents=True)
        raw=(HERE/'reports/trajectory_smoothing/pruned_middle/candidate.json').read_bytes()
        (self.review/'candidate.json').write_bytes(raw);self.candidate=json.loads(raw)
        self.ident=hashlib.sha256(raw).hexdigest()
        self.grant=dict(path_sha256=self.ident,source_sha256=self.candidate['source_sha256'],attempt_available=True,
                        clearance_approved=True,workspace_box_exception=True,direction='toward_home',speed=40,allow_explicit_repeats=False)
        self.permission=self.review/'replay_permission.json';self.permission.write_text(json.dumps(self.grant))
        self.data=json.loads((self.folder/'return_path.json').read_bytes());first=self.data['trajectory'][0]
        self.s=FakeService();self.s.cfg=json.loads((HERE/'robot_params.json').read_text())
        self.s.pose=first['pose_mm'].copy();self.s.q=first['joints'].copy()
        self.s.robot=Controller(self.s);self.s._locked=lambda fn:fn();self.s.program=Mock(return_value={'ok':True})
        self.s.status=lambda:dict(ok=True,connected=True,errors=[])
        self.run=FakeRunner();self.prepare=Mock()
        self.r=RecordedReturn(self.folder,lambda:self.s,lambda:self.run,lambda:self.s.cfg,self.prepare,Mock())
        self.body=dict(ready=True,path_id=self.ident)

    def test_exact_78_reverse_points_one_shot_and_original_permission_unchanged(self):
        original=(self.folder/'replay_permission.json').read_bytes()
        self.r.start_pruned(self.body);result=self.run.finish()
        self.assertTrue(result['ok']);self.assertEqual(result['queue']['points'],78)
        self.assertEqual(result['route_kind'],'approved_pruned')
        expected,_=prepare_points(self.data['trajectory'][0]['pose_mm'],self.data['trajectory'][0]['joints'],
                                 list(reversed([self.candidate['start']]+self.candidate['grouped']))[1:],self.s.cfg,reviewed=True)
        actual=[dict(zip(('X','Y','Z','Rz'),call[0][:3]+(call[0][5],))) for call in self.s.robot.calls]
        transmitted=[{k:struct.unpack('f',struct.pack('f',v))[0] for k,v in p.items()} for p in expected]
        self.assertEqual(actual,transmitted)
        self.assertEqual(self.s.robot.barriers,1)
        self.assertFalse(json.loads(self.permission.read_text())['attempt_available'])
        self.assertEqual((self.folder/'replay_permission.json').read_bytes(),original)
        with self.assertRaises(TeachingError):self.r.start_pruned(self.body)

    def test_tampered_artifact_or_missing_clearance_is_refused(self):
        self.grant['clearance_approved']=False;self.permission.write_text(json.dumps(self.grant))
        with self.assertRaises(TeachingError):self.r.start_pruned(self.body)
        self.grant['clearance_approved']=True;self.permission.write_text(json.dumps(self.grant))
        with (self.review/'candidate.json').open('a') as f:f.write(' ')
        with self.assertRaises(TeachingError):self.r.start_pruned(self.body)
        self.prepare.assert_not_called();self.assertEqual(self.s.robot.jobs,[])

    def test_displaced_start_and_cancel_do_not_move(self):
        self.s.pose['X']+=3
        with self.assertRaises(TeachingError):self.r.start_pruned(self.body)
        self.s.pose['X']-=3
        self.r.start_pruned(self.body);self.r.stop()
        with self.assertRaises(TransferError):self.run.finish()
        self.assertFalse(json.loads(self.permission.read_text())['attempt_available'])
        self.assertEqual(self.s.robot.jobs,[])

    def test_reviewed_mode_cannot_regroup_or_expand_step_limits(self):
        with self.assertRaises(TransferError):
            LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,self.candidate['grouped'],self.s.cfg,40,Mock(),grouped=True,reviewed=True)
        with self.assertRaises(TransferError):
            prepare_points(self.s.pose,self.s.q,[{**self.s.pose,'Z':self.s.pose['Z']+51}],self.s.cfg,reviewed=True)
        self.assertEqual(self.s.robot.jobs,[])

    def configure_vertical(self,direction):
        review=self.root/'reports/trajectory_smoothing/vertical_smoothing';review.mkdir(parents=True,exist_ok=True)
        raw=(HERE/'reports/trajectory_smoothing/vertical_smoothing/candidate.json').read_bytes()
        (review/'candidate.json').write_bytes(raw)
        ident=hashlib.sha256(raw).hexdigest()
        self.permission=review/'replay_permission.json'
        self.permission.write_text(json.dumps({**self.grant,'path_sha256':ident,'direction':direction}))
        self.body=dict(ready=True,path_id=ident,route='vertical',direction=direction)
        first=self.data['trajectory'][0 if direction=='toward_home' else -1]
        self.s.pose=first['pose_mm'].copy();self.s.q=first['joints'].copy();self.s.robot=Controller(self.s)
        return json.loads(raw)

    def test_actual_vertical_route_both_directions_through_real_lua(self):
        for direction in ('toward_home','to_hamilton'):
            c=self.configure_vertical(direction)
            self.r.start_pruned(self.body);result=self.run.finish()
            self.assertTrue(result['ok']);self.assertEqual(result['queue']['points'],75)
            self.assertEqual(result['route_kind'],'approved_vertical')
            self.assertEqual(len(self.s.robot.calls),75)
            self.assertEqual(self.s.robot.barriers,1)
            self.assertFalse(json.loads(self.permission.read_text())['attempt_available'])
            target=c['start'] if direction=='toward_home' else c['endpoint']
            for k in ('X','Y','Z','Rz'):self.assertAlmostEqual(self.s.pose[k],target[k],delta=.01)

    def test_vertical_wrong_direction_or_changed_parent_is_blocked(self):
        self.configure_vertical('toward_home')
        with self.assertRaises(TeachingError):self.r.start_pruned({**self.body,'direction':'to_hamilton'})
        with (self.review/'candidate.json').open('a') as f:f.write(' ')
        with self.assertRaises(TeachingError):self.r.start_pruned(self.body)
        self.prepare.assert_not_called();self.assertEqual(self.s.robot.jobs,[])

    def configure_straight(self,direction,variant='straight'):
        folder='straight_transfer_212' if variant=='straight_212' else 'straight_transfer'
        review=self.root/'reports/trajectory_smoothing'/folder;review.mkdir(parents=True,exist_ok=True)
        raw=(HERE/'reports/trajectory_smoothing'/folder/'candidate.json').read_bytes()
        (review/'candidate.json').write_bytes(raw);ident=hashlib.sha256(raw).hexdigest()
        self.permission=review/'replay_permission.json'
        self.permission.write_text(json.dumps({**self.grant,'path_sha256':ident,'direction':direction}))
        self.body=dict(ready=True,path_id=ident,route=variant,direction=direction)
        first=self.data['trajectory'][0 if direction=='toward_home' else -1]
        self.s.pose=first['pose_mm'].copy();self.s.q=first['joints'].copy();self.s.robot=Controller(self.s)
        return json.loads(raw)

    def test_three_exact_straight_moves_both_directions_through_lua(self):
        original=(self.folder/'replay_permission.json').read_bytes()
        for direction in ('to_hamilton','toward_home'):
            candidate=self.configure_straight(direction)
            self.r.start_pruned(self.body);result=self.run.finish()
            self.assertTrue(result['ok']);self.assertEqual(result['queue']['points'],3)
            self.assertEqual(result['route_kind'],'approved_straight');self.assertEqual(self.s.robot.barriers,1)
            expected=candidate['routes'][direction]['points']
            actual=[dict(zip(('X','Y','Z','Rz'),call[0][:3]+(call[0][5],))) for call in self.s.robot.calls]
            self.assertEqual(actual,[{k:struct.unpack('f',struct.pack('f',v))[0] for k,v in p.items()} for p in expected])
            self.assertFalse(json.loads(self.permission.read_text())['attempt_available'])
            self.assertEqual((self.folder/'replay_permission.json').read_bytes(),original)

    def test_straight_profile_rejects_diagonal_lift_or_extra_segments(self):
        c=self.configure_straight('to_hamilton');route=c['routes']['to_hamilton']
        bad=[dict(p) for p in route['points']];bad[0]['X']+=1
        for points in (bad,route['points']+[route['points'][-1]]):
            with self.assertRaises(TransferError):
                prepare_points(route['start'],self.s.q,points,self.s.cfg,reviewed=True,straight_transfer=True)
        with self.assertRaises(TransferError):
            prepare_points(route['start'],self.s.q,route['points'],self.s.cfg,reviewed=True)
        self.assertEqual(self.s.robot.jobs,[])

    def test_lower_transfer_both_directions(self):
        for direction in ('to_hamilton','toward_home'):
            c=self.configure_straight(direction,'straight_212')
            self.r.start_pruned(self.body);result=self.run.finish()
            self.assertTrue(result['ok']);self.assertEqual(result['queue']['points'],3)
            self.assertEqual(result['speed'],40)
            self.assertEqual([call[0][2] for call in self.s.robot.calls[:2]],[212,212])
            self.assertFalse(json.loads(self.permission.read_text())['attempt_available'])

    def test_level_return_real_lua_and_guardrails(self):
        review=self.root/'reports/trajectory_smoothing/return_to_start_212';review.mkdir(parents=True)
        raw=(HERE/'reports/trajectory_smoothing/return_to_start_212/candidate.json').read_bytes()
        (review/'candidate.json').write_bytes(raw);c=json.loads(raw)
        ident=hashlib.sha256(raw).hexdigest();permission=review/'replay_permission.json'
        permission.write_text(json.dumps({**self.grant,'path_sha256':ident}))
        first=c['start_sample'];self.s.pose=first['pose_mm'].copy();self.s.q=first['joints'].copy()
        self.s.robot=Controller(self.s)
        body=dict(ready=True,path_id=ident,route='return_212',direction='toward_home')
        original=(self.folder/'replay_permission.json').read_bytes()
        self.s.pose['X']+=3
        with self.assertRaises(TeachingError):self.r.start_pruned(body)
        self.s.pose['X']-=3
        with self.assertRaises(TeachingError):self.r.start_pruned({**body,'direction':'to_hamilton'})
        bad=[dict(p) for p in c['points']];bad[0]['Z']+=1
        with self.assertRaises(TransferError):prepare_points(self.s.pose,self.s.q,bad,self.s.cfg,reviewed=True,level_return=True)
        with self.assertRaises(TransferError):prepare_points(self.s.pose,self.s.q,c['points'],self.s.cfg,level_return=True)
        with self.assertRaises(TransferError):prepare_points(self.s.pose,self.s.q,c['points'],self.s.cfg,reviewed=True,level_return=True,straight_transfer=True)
        self.r.start_pruned(body);result=self.run.finish()
        self.assertTrue(result['ok']);self.assertEqual(result['queue']['points'],2)
        self.assertEqual(result['speed'],40);self.assertEqual(result['route_kind'],'approved_level_return')
        self.assertEqual(len(self.s.robot.calls),2);self.assertEqual(self.s.robot.barriers,1)
        self.assertFalse(json.loads(permission.read_text())['attempt_available'])
        self.assertEqual((self.folder/'replay_permission.json').read_bytes(),original)
        for k in ('X','Y','Z','Rz'):self.assertAlmostEqual(self.s.pose[k],c['points'][-1][k],delta=.01)

    def test_forward_entrance_exact_lua_and_shape_guards(self):
        review=self.root/'reports/trajectory_smoothing/entry_forward_3mm';review.mkdir(parents=True)
        raw=(HERE/'reports/trajectory_smoothing/entry_forward_3mm/candidate.json').read_bytes()
        (review/'candidate.json').write_bytes(raw);c=json.loads(raw);ident=hashlib.sha256(raw).hexdigest()
        permission=review/'replay_permission.json'
        permission.write_text(json.dumps({**self.grant,'path_sha256':ident,'direction':'to_hamilton'}))
        first=self.data['trajectory'][-1];self.s.pose=first['pose_mm'].copy();self.s.q=first['joints'].copy()
        self.s.robot=Controller(self.s);route=c['routes']['to_hamilton'];points=route['points']
        body=dict(ready=True,path_id=ident,route='entry_forward_3mm',direction='to_hamilton')
        with self.assertRaises(TeachingError):self.r.start_pruned({**body,'direction':'toward_home'})
        for x,y in ((194.8,-363.26),(195.88,-354.36),(198.88,-357.36)):
            bad=[dict(p) for p in points];bad[1].update(X=x,Y=y)
            with self.assertRaises(TransferError):prepare_points(self.s.pose,self.s.q,bad,self.s.cfg,reviewed=True,forward_entry=True)
        for flags in ({'forward_entry':True},{'reviewed':True,'forward_entry':True,'straight_transfer':True}):
            with self.assertRaises(TransferError):prepare_points(self.s.pose,self.s.q,points,self.s.cfg,**flags)
        original=(self.folder/'replay_permission.json').read_bytes()
        self.r.start_pruned(body);result=self.run.finish()
        self.assertTrue(result['ok']);self.assertEqual(result['route_kind'],'approved_forward_entry')
        self.assertEqual(len(self.s.robot.calls),3);self.assertEqual(self.s.robot.barriers,1)
        actual=[dict(zip(('X','Y','Z','Rz'),call[0][:3]+(call[0][5],))) for call in self.s.robot.calls]
        self.assertEqual(actual,[{k:struct.unpack('f',struct.pack('f',v))[0] for k,v in p.items()} for p in points])
        self.assertFalse(json.loads(permission.read_text())['attempt_available'])
        self.assertEqual((self.folder/'replay_permission.json').read_bytes(),original)

    def test_reset_route_uses_exact_reverse_baseline(self):
        c=self.configure_straight('toward_home','straight_212')
        src=self.permission.parent;dst=src.parent/'straight_212_return';shutil.copytree(src,dst)
        self.body['route']='straight_212_return';self.permission=dst/'replay_permission.json'
        self.r.start_pruned(self.body);result=self.run.finish()
        self.assertTrue(result['ok']);self.assertEqual(result['queue']['points'],3)
        self.assertEqual(result['direction'],'toward_home')
        self.assertFalse(json.loads(self.permission.read_text())['attempt_available'])

    def configure_speed47(self,direction,speed=47):
        variant=f'entry_speed{speed}_'+direction
        review=self.root/'reports/trajectory_smoothing'/variant;review.mkdir(parents=True,exist_ok=True)
        raw=(HERE/'reports/trajectory_smoothing'/variant/'candidate.json').read_bytes()
        (review/'candidate.json').write_bytes(raw);ident=hashlib.sha256(raw).hexdigest()
        self.permission=review/'replay_permission.json'
        self.permission.write_text(json.dumps({**self.grant,'speed':speed,'path_sha256':ident,'direction':direction}))
        self.body=dict(ready=True,path_id=ident,route=variant,direction=direction)
        first=self.data['trajectory'][0 if direction=='toward_home' else -1]
        self.s.pose=first['pose_mm'].copy();self.s.q=first['joints'].copy();self.s.robot=Controller(self.s)
        return json.loads(raw)['routes']['to_hamilton']

    def test_speed47_both_directions_same_geometry_real_lua(self):
        for direction in ('toward_home','to_hamilton'):
            c=self.configure_speed47(direction)
            self.r.start_pruned(self.body);result=self.run.finish()
            self.assertTrue(result['ok']);self.assertEqual(result['speed'],47)
            self.assertEqual(len(self.s.robot.calls),3);self.assertEqual(self.s.robot.barriers,1)
            self.assertTrue(all(call[1]==47 for call in self.s.robot.calls))
            path=[c['start']]+c['points']
            if direction=='toward_home':path=list(reversed(path))
            actual=[dict(zip(('X','Y','Z','Rz'),call[0][:3]+(call[0][5],))) for call in self.s.robot.calls]
            self.assertEqual(actual,[{k:struct.unpack('f',struct.pack('f',v))[0] for k,v in p.items()} for p in path[1:]])
            self.assertFalse(json.loads(self.permission.read_text())['attempt_available'])

    def test_speed47_legacy_controller_refused_without_consumption_or_motion(self):
        c=self.configure_speed47('to_hamilton');self.s.robot=Controller(self.s,legacy=True)
        with self.assertRaisesRegex(TeachingError,'220102'):self.r.start_pruned(self.body)
        self.assertTrue(json.loads(self.permission.read_text())['attempt_available'])
        self.prepare.assert_not_called();self.assertEqual(self.s.robot.jobs,[])
        with self.assertRaisesRegex(TransferError,'220102'):
            LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,c['points'],self.s.cfg,47,Mock(),reviewed=True,forward_entry=True,research_speed47=True)
        self.assertEqual(self.s.robot.jobs,[])

    def test_speed47_requires_specific_trial_and_refuses_higher_speed(self):
        c=self.configure_speed47('to_hamilton')
        for speed,flags in ((47,{}),(48,{'research_speed47':True})):
            with self.assertRaises(TransferError):
                LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,c['points'],self.s.cfg,speed,Mock(),reviewed=True,forward_entry=True,**flags)
        self.assertEqual(self.s.robot.jobs,[])

    def test_speed55_both_directions_exact_geometry_real_lua(self):
        for direction in ('toward_home','to_hamilton'):
            c=self.configure_speed47(direction,55)
            self.r.start_pruned(self.body);result=self.run.finish()
            self.assertTrue(result['ok']);self.assertEqual(result['speed'],55)
            self.assertEqual(len(self.s.robot.calls),3);self.assertEqual(self.s.robot.barriers,1)
            self.assertTrue(all(call[1]==55 for call in self.s.robot.calls))
            path=[c['start']]+c['points']
            if direction=='toward_home':path=list(reversed(path))
            actual=[dict(zip(('X','Y','Z','Rz'),call[0][:3]+(call[0][5],))) for call in self.s.robot.calls]
            self.assertEqual(actual,[{k:struct.unpack('f',struct.pack('f',v))[0] for k,v in p.items()} for p in path[1:]])
            self.assertFalse(json.loads(self.permission.read_text())['attempt_available'])

    def test_speed55_both_old_controllers_refused_without_commands(self):
        for legacy in (True,47):
            c=self.configure_speed47('to_hamilton',55);self.s.robot=Controller(self.s,legacy=legacy)
            with self.assertRaisesRegex(TeachingError,'220103'):self.r.start_pruned(self.body)
            self.assertTrue(json.loads(self.permission.read_text())['attempt_available'])
            with self.assertRaisesRegex(TransferError,'220103'):
                LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,c['points'],self.s.cfg,55,Mock(),reviewed=True,forward_entry=True,research_speed55=True)
            self.assertEqual(self.s.robot.jobs,[]);self.prepare.assert_not_called()

    def test_speed55_requires_specific_trial_and_rejects_over55(self):
        c=self.configure_speed47('to_hamilton',55)
        for speed,flags in ((55,{}),(55,{'research_speed47':True}),(56,{'research_speed55':True}),
                            (55,{'research_speed47':True,'research_speed55':True})):
            with self.assertRaises(TransferError):
                LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,c['points'],self.s.cfg,speed,Mock(),reviewed=True,forward_entry=True,**flags)
        self.assertEqual(self.s.robot.jobs,[])

    def test_speed47_remains_compatible_with_published_47_module(self):
        self.configure_speed47('toward_home');self.s.robot=Controller(self.s,legacy=47)
        self.r.start_pruned(self.body);result=self.run.finish()
        self.assertTrue(result['ok']);self.assertEqual(result['speed'],47)

    def test_speed70_both_directions_exact_geometry_real_lua(self):
        for direction in ('toward_home','to_hamilton'):
            c=self.configure_speed47(direction,70)
            self.r.start_pruned(self.body);result=self.run.finish()
            self.assertTrue(result['ok']);self.assertEqual(result['speed'],70)
            self.assertEqual(len(self.s.robot.calls),3);self.assertEqual(self.s.robot.barriers,1)
            self.assertTrue(all(call[1]==70 for call in self.s.robot.calls))
            path=[c['start']]+c['points']
            if direction=='toward_home':path=list(reversed(path))
            actual=[dict(zip(('X','Y','Z','Rz'),call[0][:3]+(call[0][5],))) for call in self.s.robot.calls]
            self.assertEqual(actual,[{k:struct.unpack('f',struct.pack('f',v))[0] for k,v in p.items()} for p in path[1:]])
            self.assertFalse(json.loads(self.permission.read_text())['attempt_available'])

    def test_speed70_old_controllers_refused_without_commands(self):
        for legacy in (True,47,55):
            c=self.configure_speed47('to_hamilton',70);self.s.robot=Controller(self.s,legacy=legacy)
            with self.assertRaisesRegex(TeachingError,'220104'):self.r.start_pruned(self.body)
            self.assertTrue(json.loads(self.permission.read_text())['attempt_available'])
            with self.assertRaisesRegex(TransferError,'220104'):
                LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,c['points'],self.s.cfg,70,Mock(),reviewed=True,forward_entry=True,research_speed70=True)
            self.assertEqual(self.s.robot.jobs,[]);self.prepare.assert_not_called()

    def test_speed70_requires_specific_trial_and_rejects_over70(self):
        c=self.configure_speed47('to_hamilton',70)
        for speed,flags in ((70,{}),(70,{'research_speed55':True}),(71,{'research_speed70':True}),
                            (70,{'research_speed55':True,'research_speed70':True})):
            with self.assertRaises(TransferError):
                LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,c['points'],self.s.cfg,speed,Mock(),reviewed=True,forward_entry=True,**flags)
        self.assertEqual(self.s.robot.jobs,[])

    def test_speed55_remains_compatible_with_published_55_module(self):
        self.configure_speed47('toward_home',55);self.s.robot=Controller(self.s,legacy=55)
        self.r.start_pruned(self.body);result=self.run.finish()
        self.assertTrue(result['ok']);self.assertEqual(result['speed'],55)

    def test_speed80_both_directions_exact_geometry_real_lua(self):
        for direction in ('toward_home','to_hamilton'):
            c=self.configure_speed47(direction,80)
            self.r.start_pruned(self.body);result=self.run.finish()
            self.assertTrue(result['ok']);self.assertEqual(result['speed'],80)
            self.assertEqual(len(self.s.robot.calls),3);self.assertEqual(self.s.robot.barriers,1)
            self.assertTrue(all(call[1]==80 for call in self.s.robot.calls))
            path=[c['start']]+c['points']
            if direction=='toward_home':path=list(reversed(path))
            actual=[dict(zip(('X','Y','Z','Rz'),call[0][:3]+(call[0][5],))) for call in self.s.robot.calls]
            self.assertEqual(actual,[{k:struct.unpack('f',struct.pack('f',v))[0] for k,v in p.items()} for p in path[1:]])
            self.assertFalse(json.loads(self.permission.read_text())['attempt_available'])

    def test_speed80_old_controllers_refused_without_commands(self):
        for legacy in (True,47,55,70):
            c=self.configure_speed47('to_hamilton',80);self.s.robot=Controller(self.s,legacy=legacy)
            with self.assertRaisesRegex(TeachingError,'220105'):self.r.start_pruned(self.body)
            self.assertTrue(json.loads(self.permission.read_text())['attempt_available'])
            with self.assertRaisesRegex(TransferError,'220105'):
                LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,c['points'],self.s.cfg,80,Mock(),reviewed=True,forward_entry=True,research_speed80=True)
            self.assertEqual(self.s.robot.jobs,[]);self.prepare.assert_not_called()

    def test_speed80_requires_specific_trial_and_rejects_over80(self):
        c=self.configure_speed47('to_hamilton',80)
        for speed,flags in ((80,{}),(80,{'research_speed70':True}),(81,{'research_speed80':True}),
                            (80,{'research_speed70':True,'research_speed80':True})):
            with self.assertRaises(TransferError):
                LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,c['points'],self.s.cfg,speed,Mock(),reviewed=True,forward_entry=True,**flags)
        self.assertEqual(self.s.robot.jobs,[])

    def test_speed70_remains_compatible_with_published_70_module(self):
        self.configure_speed47('toward_home',70);self.s.robot=Controller(self.s,legacy=70)
        self.r.start_pruned(self.body);result=self.run.finish()
        self.assertTrue(result['ok']);self.assertEqual(result['speed'],70)

    def test_speed100_both_directions_exact_geometry_real_lua(self):
        for direction in ('toward_home','to_hamilton'):
            c=self.configure_speed47(direction,100)
            self.r.start_pruned(self.body);result=self.run.finish()
            self.assertTrue(result['ok']);self.assertEqual(result['speed'],100)
            self.assertEqual(len(self.s.robot.calls),3);self.assertEqual(self.s.robot.barriers,1)
            self.assertTrue(all(call[1]==100 for call in self.s.robot.calls))
            path=[c['start']]+c['points']
            if direction=='toward_home':path=list(reversed(path))
            actual=[dict(zip(('X','Y','Z','Rz'),call[0][:3]+(call[0][5],))) for call in self.s.robot.calls]
            self.assertEqual(actual,[{k:struct.unpack('f',struct.pack('f',v))[0] for k,v in p.items()} for p in path[1:]])
            self.assertFalse(json.loads(self.permission.read_text())['attempt_available'])

    def test_speed100_old_controllers_refused_without_commands(self):
        for legacy in (True,47,55,70,80):
            c=self.configure_speed47('to_hamilton',100);self.s.robot=Controller(self.s,legacy=legacy)
            with self.assertRaisesRegex(TeachingError,'220106'):self.r.start_pruned(self.body)
            self.assertTrue(json.loads(self.permission.read_text())['attempt_available'])
            with self.assertRaisesRegex(TransferError,'220106'):
                LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,c['points'],self.s.cfg,100,Mock(),reviewed=True,forward_entry=True,research_speed100=True)
            self.assertEqual(self.s.robot.jobs,[]);self.prepare.assert_not_called()

    def test_speed100_requires_specific_trial_and_rejects_over100(self):
        c=self.configure_speed47('to_hamilton',100)
        for speed,flags in ((100,{}),(100,{'research_speed80':True}),(101,{'research_speed100':True}),
                            (100,{'research_speed80':True,'research_speed100':True})):
            with self.assertRaises(TransferError):
                LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,c['points'],self.s.cfg,speed,Mock(),reviewed=True,forward_entry=True,**flags)
        self.assertEqual(self.s.robot.jobs,[])

    def test_speed130_both_directions_exact_geometry_real_lua(self):
        for direction in ('toward_home','to_hamilton'):
            c=self.configure_speed47(direction,130)
            self.r.start_pruned(self.body);result=self.run.finish()
            self.assertTrue(result['ok']);self.assertEqual(result['speed'],130)
            self.assertEqual(len(self.s.robot.calls),3);self.assertEqual(self.s.robot.barriers,1)
            self.assertTrue(all(call[1]==130 for call in self.s.robot.calls))
            path=[c['start']]+c['points']
            if direction=='toward_home':path=list(reversed(path))
            actual=[dict(zip(('X','Y','Z','Rz'),call[0][:3]+(call[0][5],))) for call in self.s.robot.calls]
            self.assertEqual(actual,[{k:struct.unpack('f',struct.pack('f',v))[0] for k,v in p.items()} for p in path[1:]])
            self.assertFalse(json.loads(self.permission.read_text())['attempt_available'])

    def test_speed130_old_controllers_refused_without_commands(self):
        for legacy in (True,47,55,70,80,100):
            c=self.configure_speed47('to_hamilton',130);self.s.robot=Controller(self.s,legacy=legacy)
            with self.assertRaisesRegex(TeachingError,'220107'):self.r.start_pruned(self.body)
            self.assertTrue(json.loads(self.permission.read_text())['attempt_available'])
            with self.assertRaisesRegex(TransferError,'220107'):
                LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,c['points'],self.s.cfg,130,Mock(),reviewed=True,forward_entry=True,research_speed130=True)
            self.assertEqual(self.s.robot.jobs,[]);self.prepare.assert_not_called()

    def test_speed130_requires_specific_trial_and_rejects_over130(self):
        c=self.configure_speed47('to_hamilton',130)
        for speed,flags in ((130,{}),(130,{'research_speed100':True}),(131,{'research_speed130':True}),
                            (130,{'research_speed100':True,'research_speed130':True})):
            with self.assertRaises(TransferError):
                LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,c['points'],self.s.cfg,speed,Mock(),reviewed=True,forward_entry=True,**flags)
        self.assertEqual(self.s.robot.jobs,[])

    def test_speed137_both_directions_exact_geometry_real_lua(self):
        for direction in ('toward_home','to_hamilton'):
            c=self.configure_speed47(direction,137)
            self.r.start_pruned(self.body);result=self.run.finish()
            self.assertTrue(result['ok']);self.assertEqual(result['speed'],137)
            self.assertEqual(len(self.s.robot.calls),3);self.assertEqual(self.s.robot.barriers,1)
            self.assertTrue(all(call[1]==137 for call in self.s.robot.calls))
            path=[c['start']]+c['points']
            if direction=='toward_home':path=list(reversed(path))
            actual=[dict(zip(('X','Y','Z','Rz'),call[0][:3]+(call[0][5],))) for call in self.s.robot.calls]
            self.assertEqual(actual,[{k:struct.unpack('f',struct.pack('f',v))[0] for k,v in p.items()} for p in path[1:]])
            self.assertFalse(json.loads(self.permission.read_text())['attempt_available'])

    def test_speed137_old_controllers_refused_without_commands(self):
        for legacy in (True,47,55,70,80,100,130):
            c=self.configure_speed47('to_hamilton',137);self.s.robot=Controller(self.s,legacy=legacy)
            with self.assertRaisesRegex(TeachingError,'220108'):self.r.start_pruned(self.body)
            self.assertTrue(json.loads(self.permission.read_text())['attempt_available'])
            with self.assertRaisesRegex(TransferError,'220108'):
                LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,c['points'],self.s.cfg,137,Mock(),reviewed=True,forward_entry=True,research_speed137=True)
            self.assertEqual(self.s.robot.jobs,[]);self.prepare.assert_not_called()

    def test_speed137_requires_specific_trial_and_rejects_over137(self):
        c=self.configure_speed47('to_hamilton',137)
        for speed,flags in ((137,{}),(137,{'research_speed130':True}),(138,{'research_speed137':True}),
                            (137,{'research_speed130':True,'research_speed137':True})):
            with self.assertRaises(TransferError):
                LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,c['points'],self.s.cfg,speed,Mock(),reviewed=True,forward_entry=True,**flags)
        self.assertEqual(self.s.robot.jobs,[])

    def test_speed130_remains_compatible_with_published_130_module(self):
        self.configure_speed47('toward_home',130);self.s.robot=Controller(self.s,legacy=130)
        self.r.start_pruned(self.body);result=self.run.finish()
        self.assertTrue(result['ok']);self.assertEqual(result['speed'],130)

    def test_speed100_remains_compatible_with_published_100_module(self):
        self.configure_speed47('toward_home',100);self.s.robot=Controller(self.s,legacy=100)
        self.r.start_pruned(self.body);result=self.run.finish()
        self.assertTrue(result['ok']);self.assertEqual(result['speed'],100)

    def test_speed80_remains_compatible_with_published_80_module(self):
        self.configure_speed47('toward_home',80);self.s.robot=Controller(self.s,legacy=80)
        self.r.start_pruned(self.body);result=self.run.finish()
        self.assertTrue(result['ok']);self.assertEqual(result['speed'],80)


if __name__=='__main__':unittest.main()
