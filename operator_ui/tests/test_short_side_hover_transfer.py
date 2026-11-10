"""Offline IK and real Lua protocol checks; no robot connection."""
import ast
import json
import tempfile
import copy
import sys
import unittest
import zipfile
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from short_side_hover_transfer import reference,build,ROOT
from trajectory_queue import LuaTrajectory,checksum
from autonomy import TransferError
from test_transfer import FakeService
from test_trajectory_queue import Controller
from test_researcher_workflow import FakeRunner

class HoverTransferTests(unittest.TestCase):
    def setup_route(self,direction='forward',legacy=False):
        p,_,_=reference();r=p['routes'][direction]
        self.s=FakeService();self.s.cfg=p['config'];self.s.pose=r['start'].copy();self.s.q=r['start_joints'].copy()
        self.s.envelope={k:(p['global_envelope'][k]['min'],p['global_envelope'][k]['max']) for k in ('X','Y','Z')}
        with zipfile.ZipFile(ROOT.parent/'controller/main_hostpoint_e2_holder_speed137_queue_220109.bin') as z:
            lua=z.read('main/mod_Trajectory.lua').decode('utf-8-sig')
        self.s.robot=Controller(self.s,source=None if legacy else lua);self.s._locked=lambda fn:fn()
        def stop(action):
            self.assertEqual(action,'stop')
            self.s.robot.program_state='stopped';self.s.robot.released.set()
            return dict(ok=True)
        self.s.program=stop
        self.run=FakeRunner();self.run.cancelled=False
        self.points=copy.deepcopy(r['points']);self.speeds=list(r['segment_speeds']);self.profile='pickup_hover03_'+direction

    def execute(self,progress=lambda *a:None,**extra):
        return LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,self.points,self.s.cfg,137,progress,
            reviewed=True,hamilton_short_side=self.profile,segment_speeds=self.speeds,**extra)

    def test_dense_ik_keeps_taught_turn_and_exact_reverse(self):
        p=build();old,_,_=__import__('short_side_direct_transfer').reference()
        self.assertEqual(p['taught_turn'],old['taught_turn'])
        f=p['routes']['forward'];r=p['routes']['reverse']
        self.assertEqual([f['start']]+f['points'],list(reversed([r['start']]+r['points'])))
        self.assertEqual(f['segment_speeds'],[137,137,137,137,5])
        self.assertEqual(r['segment_speeds'],[5,137,137,137,137])
        self.assertEqual(f['points'][-1],old['routes']['forward']['points'][-1])
        self.assertEqual(f['points'][-2]['Z'],55)
        for point in f['points'][-3:]:
            self.assertEqual([point[k] for k in ('X','Y','Rz')],[374.04,-184.17,-93.56])
        self.assertEqual(f['points'][1]['Z'],f['points'][2]['Z'])
        self.assertEqual(p['global_envelope']['Z']['min'],70)
        for route in p['routes'].values():
            self.assertTrue(route['validation']['ik_and_joint_limits_valid'])
            self.assertTrue(route['validation']['workspace_valid'])
            self.assertGreater(len(route['validation']['dense_samples']),700)

    def test_published_lua_five_moves_one_barrier_both_directions(self):
        for direction in ('forward','reverse'):
            self.setup_route(direction);result=self.execute()
            self.assertTrue(result['ok']);robot=self.s.robot
            self.assertEqual([c[1] for c in robot.calls],self.speeds)
            self.assertEqual(robot.barriers,1)
            self.assertEqual([j[4] for j in robot.jobs],[6,8,9,9,3,4])
            for call,p in zip(robot.calls,self.points):
                self.assertAlmostEqual(call[0][0],p['X'],places=3)
                self.assertAlmostEqual(call[0][2],p['Z'],places=3)
                self.assertEqual(call[0][6:9],(3.4,-2,0))
            self.assertEqual(self.s.grips,[])
            self.assertNotEqual(checksum(self.points,self.speeds),checksum(self.points,[137]*5))

    def test_speed_mask_missing_fast_seating_or_slow_before55_rejected(self):
        for bad in (None,[137]*5,[137,137,137,5,5],[137]*4,[137,137,137,137,float('nan')]):
            self.setup_route();self.speeds=bad
            with self.assertRaises(TransferError):self.execute()
            self.assertEqual(self.s.robot.jobs,[])

    def test_skip_hover_change_endpoint_or_global_limits_rejected_before_upload(self):
        for action in ('skip','height','workspace','winding','home'):
            self.setup_route()
            if action=='skip':self.points.pop(2)
            elif action=='height':self.points[-1]['Z']=55
            elif action=='workspace':self.s.envelope['Z']=(52,400)
            elif action=='winding':self.s.q['J4']+=360
            else:self.s.pose=reference()[1]['home']
            with self.assertRaises(TransferError):self.execute()
            self.assertEqual(self.s.robot.jobs,[])

    def test_old_lua_and_conflicting_profiles_rejected(self):
        self.setup_route(legacy=True)
        with self.assertRaisesRegex(TransferError,'220109'):self.execute()
        self.assertEqual(self.s.robot.jobs,[])
        self.setup_route()
        with self.assertRaises(TransferError):self.execute(squid_queue=True)
        self.assertEqual(self.s.robot.jobs,[])

    def test_interrupted_upload_stops_without_dispatch_or_retry(self):
        self.setup_route()
        def fail(*args):raise TransferError('lost feedback')
        with self.assertRaisesRegex(TransferError,'lost feedback'):self.execute(progress=fail)
        self.assertEqual(self.s.robot.calls,[])
        self.assertNotIn(4,[j[4] for j in self.s.robot.jobs])
        self.assertEqual(self.s.robot.program_state,'stopped')

    def test_trial_revision_and_runner_syntax(self):
        from short_side_full_trial import reference as trial_reference,receipt
        self.assertEqual(trial_reference('03')[0]['routes'],reference()[0]['routes'])
        self.assertEqual(receipt('hamilton','03').name,'full_sequence03_hamilton.json')
        source=(ROOT/'run_short_side_pickup_to_hamilton.py').read_text()
        ast.parse(source)
        self.assertNotIn('move_home',source)
        self.assertIn("choices=('02','03','04'),required=True",source)
        ast.parse((ROOT/'app.py').read_text(encoding='utf-8-sig'))

    def test_holder_checked_before_pickup_but_not_loaded_queue(self):
        import short_side_full_trial as trial
        self.setup_route()
        p,_,grip=reference()
        native=dict(manual=False,drag=False,error=False,emergency=False,moving=False,
                    external_axes={'E1':25,'E2':grip['holder_e2_degrees']+1})
        self.s._endpoint_addr=lambda:('fake',0)
        self.s.status=lambda:dict(ok=True,errors=[],pose_mm=self.s.pose.copy(),joints=self.s.q.copy())
        with tempfile.TemporaryDirectory() as folder:
            target=lambda phase,*args:Path(folder)/(phase+'.json')
            target('grip_lift').write_text(json.dumps({'status':'completed'}))
            with patch.object(trial,'receipt',target),patch.object(trial,'preflight',lambda service:service.status()),patch.object(trial,'DragGoRPC',lambda host:SimpleNamespace(info=lambda:native)):
                approved=trial.review(self.s,p['config'],'hamilton','03')
                result=trial.execute(self.run,self.s,p['config'],approved)
                self.assertTrue(result['ok'])
                self.assertEqual([c[1] for c in self.s.robot.calls],[137,137,137,137,5])
                native['external_axes']['E1']=28
                with self.assertRaisesRegex(TransferError,'Jaw or holder'):
                    trial.review(self.s,p['config'],'approach','03')

    def test_lift_holder_telemetry_does_not_remove_jaw_or_fault_checks(self):
        # Compile only the pure monitoring function, never the live runner.
        source=ast.parse((ROOT/'run_short_side_pickup_to_hamilton.py').read_text())
        fn=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='checked')
        state={'robot':dict(ok=True,connected=True,errors=[],enabled=True,
            control_mode={'mode':'auto'},program_state={'state':'running'},lua_app_initialized=True),
            'sequence':{'active':False}}
        native=dict(manual=False,drag=False,error=False,emergency=False,external_axes={'E1':25,'E2':91.0})
        ns=dict(api=lambda ep:state,DragGoRPC=lambda host:SimpleNamespace(info=lambda:native),
            time=__import__('time'),record={'samples':[]},grip={'holder_e2_degrees':90.71661229181757})
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'checked_only','exec'),ns)
        checked=ns['checked']
        with self.assertRaisesRegex(RuntimeError,'Holder changed'):checked((24.93,25.07))
        checked((24.93,25.07),holder_required=False)
        native['external_axes']['E1']=24.8
        with self.assertRaisesRegex(RuntimeError,'Jaw position'):checked((24.93,25.07),holder_required=False)
        native['external_axes']['E1']=25;state['robot']['errors']=['collision']
        with self.assertRaisesRegex(RuntimeError,'Healthy running Auto'):checked((24.93,25.07),holder_required=False)

    def test_corrected04_actual_lua_endpoint_and_reverse(self):
        p,_,_=reference('04')
        for direction in ('forward','reverse','departure'):
            self.setup_route('forward' if direction=='departure' else direction)
            route=p['routes'][direction]
            self.s.pose=route['start'].copy();self.s.q=route['start_joints'].copy()
            self.points=copy.deepcopy(route['points']);self.speeds=list(route['segment_speeds'])
            self.profile='pickup_hover04_'+direction
            self.assertTrue(self.execute()['ok'])
            self.assertEqual(self.s.robot.barriers,1)
            self.assertEqual([call[1] for call in self.s.robot.calls],self.speeds)
            for call,point in zip(self.s.robot.calls,self.points):
                for index,key in enumerate(('X','Y','Z','Rz')):
                    actual=call[0][index if index<3 else 5]
                    self.assertAlmostEqual(actual,point[key],places=3)
            self.assertEqual(self.s.envelope['Z'],(70,400))

    def test_departure_requires_accepted_arrival_and_preserves_grip(self):
        import short_side_full_trial as trial
        import hashlib
        p,_,grip=reference('04');route=p['routes']['departure']
        self.setup_route();self.s.pose=route['start'].copy();self.s.q=route['start_joints'].copy()
        self.s._endpoint_addr=lambda:('fake',0)
        self.s.status=lambda:dict(ok=True,errors=[],pose_mm=self.s.pose.copy(),joints=self.s.q.copy())
        native=dict(manual=False,drag=False,error=False,emergency=False,moving=False,
                    external_axes={'E1':25,'E2':grip['holder_e2_degrees']+1})
        with tempfile.TemporaryDirectory() as folder:
            target=lambda phase,*args:Path(folder)/(phase+'.json')
            target('ready').write_text(json.dumps(dict(status='completed',operator_confirmed_plate_reseated_empty_jaws=True)))
            target('grip_lift').write_text(json.dumps(dict(status='completed')))
            target('hamilton').write_text(json.dumps(dict(status='completed')))
            accepted=dict(accepted=False,hamilton_sha256=hashlib.sha256(target('hamilton').read_bytes()).hexdigest())
            target('operator_acceptance').write_text(json.dumps(accepted))
            with patch.object(trial,'receipt',target),patch.object(trial,'preflight',lambda service:service.status()),patch.object(trial,'DragGoRPC',lambda host:SimpleNamespace(info=lambda:native)):
                with self.assertRaisesRegex(TransferError,'operator-accepted'):
                    trial.review(self.s,p['config'],'departure','04')
                self.assertEqual(self.s.robot.jobs,[])
                accepted['accepted']=True;target('operator_acceptance').write_text(json.dumps(accepted))
                approved=trial.review(self.s,p['config'],'departure','04')
                self.assertTrue(trial.execute(self.run,self.s,p['config'],approved)['ok'])
                self.assertEqual([c[1] for c in self.s.robot.calls],[5,137,137,137])
                self.assertEqual(self.s.grips,[])
                self.assertEqual(self.s.robot.barriers,1)

    def test_corrected04_rejects_old_endpoint_and_fast_final_seating(self):
        p,_,_=reference('04')
        for change in ('old_endpoint','fast_seating'):
            self.setup_route()
            self.points=copy.deepcopy(p['routes']['forward']['points'])
            self.profile='pickup_hover04_forward'
            if change=='old_endpoint':self.points[-1]=reference()[0]['routes']['forward']['points'][-1]
            else:self.speeds=[137]*5
            with self.assertRaises(TransferError):self.execute()
            self.assertEqual(self.s.robot.jobs,[])

if __name__=='__main__':unittest.main()
