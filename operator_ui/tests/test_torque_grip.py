"""Real Lua/vendor wrapper with fake native motor calls. NEVER connects hardware."""
import copy
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_transfer import FakeService
from test_trajectory_queue import Controller
from sequences import Runner
from researcher_teaching import TeachingError
from pick_and_hold.Grip.torque import TorqueGrip,LuaTorqueGrip,read_profile
from build_grip_program import build,ROOT,CONTROLLER_DIR

# Synthetic numbers for software tests only; not exported to the live profile.
PROFILE=dict(schema=1,reviewed=True,force_limits=[10,20,30,40,50,60],
    force_units='fake test units',contact_torque_abs=10,closing_torque_sign=-1,
    source='offline fixture only',e1_floor_mm=3.8,speed=5)


class GripController(Controller):
    def __init__(self,s):
        super().__init__(s)
        self.ext=[28,-2,3,4,5,6];self.force_calls=[];self.grip_calls=[]
        self.contact=-12.;self.endpoint=4.1;self.wrong_version=False
        self.lose_reply=False;self.arm_shift=False;self.ext_shift=False;self.nan=False
        self.after_complete=None
        g=self.lua.globals()
        g.GetCJoints=lambda:self.lua.table_from([s.q[k] for k in ('J1','J2','J3','J4')]+[0,0]+self.ext)
        g.GetCJointsTrq=lambda:self.lua.table_from([1]*6+[float('nan') if self.nan else self.contact]+[0]*5)
        g.GetCJointsNormTrq=lambda:self.lua.table_from([.1]*6+[-.12]+[0]*5)
        g.DelayMS=lambda _:None
        g.DefArray=lambda *a:self.lua.table_from({'_a'+str(i+1):v for i,v in enumerate(a)})
        g.JointTarget=lambda *a:self.lua.table_from({'_ext'+str(i+1):v for i,v in enumerate(a[6:])})
        g.SetExtJTrqLimit=lambda a:self.force_calls.append([a['_a'+str(i)] for i in range(1,7)])
        g.MoveExtJ=self.move_ext
        g.MOVFINISH=lambda:None
        with zipfile.ZipFile(CONTROLLER_DIR/'main_hostpoint_descent_137.bin') as z:
            source=z.read('main/__lif.lua').decode().replace('\r','')
        primitive=re.search(r'function MoveExtJWithForce\(.*?\nend',source,re.S).group()
        self.lua.execute(primitive)
        self.lua.execute((ROOT/'operator_ui/lua/mod_Grip.lua').read_text())
        g.GripInit()

    def move_ext(self,target,speed,*_):
        values=[target['_ext'+str(i)] for i in range(1,7)]
        self.grip_calls.append((values,speed));self.started.set()
        if self.block_motion:
            self.released.wait(3);raise RuntimeError('controller stopped')
        self.ext[0]=self.endpoint
        if self.arm_shift:self.service.pose['Z']+=1
        if self.ext_shift:self.ext[1]+=1

    def set_sys_var_i(self,values,reply_timeout=10):
        self.jobs.append(values.copy());self.vars.update(values)
        for k,v in values.items():setattr(self.lua.globals(),'SYSINVAR'+str(k),v)
        if self.wrong_version and values[4]==6:return {'index':1,'value':230101}
        self.reply=None;self.lua.globals().mod_Grip()
        if values[4]==2:
            if self.lose_reply:raise TimeoutError('lost acknowledgement')
            if self.after_complete:self.after_complete()
        return self.reply


class TorqueGripTests(unittest.TestCase):
    def setUp(self):
        self.s=FakeService();self.s.robot=GripController(self.s);self.stops=0
        self.s._locked=lambda fn:fn()
        self.s.external_axes=lambda:{'E1':self.s.robot.ext[0]}
        self.s.status=lambda:dict(ok=True,connected=True,errors=[],enabled=True,
            control_mode={'mode':'auto'},program_state={'state':'running'},
            pose_mm=self.s.pose_mm(),external_axes=self.s.external_axes())
        self.s.program=self.stop
        self.run=Runner();self.receipt=dict(pose_mm=self.s.pose_mm())
        self.executor=LuaTorqueGrip(self.s);self.executor.OBSERVE_SECONDS=.02;self.executor.POLL=.001
        self.record={};self.saved=[]

    def stop(self,action):
        self.assertEqual(action,'stop');self.stops+=1
        self.s.robot.program_state='stopped';self.s.robot.released.set();return {'ok':True}

    def execute(self):
        return self.executor.execute(self.run,self.receipt,PROFILE,self.record,lambda:self.saved.append(copy.deepcopy(self.record)))

    def test_real_vendor_array_mapping_and_no_arm_approach(self):
        initial=self.s.pose_mm();r=self.execute()
        self.assertTrue(r['contact_detected']);self.assertFalse(r['grasp_verified']);self.assertFalse(r['gripped'])
        self.assertAlmostEqual(r['e1_position'],4.1) # contact above floor is allowed
        values,speed=self.s.robot.grip_calls[0]
        self.assertAlmostEqual(values[0],3.8,places=5)
        self.assertEqual(values[1:],[-2,3,4,5,6]);self.assertEqual(speed,5)
        self.assertEqual(self.s.robot.force_calls,[PROFILE['force_limits']])
        self.assertEqual(self.s.robot.calls,[]);self.assertEqual(self.s.pose_mm(),initial)
        self.assertEqual(self.s.grips,[]);self.assertTrue(self.record['samples'])

    def test_no_contact_does_not_claim_success_or_lift(self):
        self.s.robot.contact=0
        with self.assertRaisesRegex(TeachingError,'contact torque'):self.execute()
        self.assertEqual(len(self.s.robot.grip_calls),1);self.assertEqual(self.stops,1)
        self.assertEqual(self.s.robot.calls,[])

    def test_below_floor_arm_motion_other_axis_motion_and_bad_feedback_stop(self):
        for attr,value in [('endpoint',3.4),('arm_shift',True),('ext_shift',True),('nan',True)]:
            with self.subTest(attr=attr):
                self.setUp();setattr(self.s.robot,attr,value)
                with self.assertRaises(TeachingError):self.execute()
                self.assertLessEqual(len(self.s.robot.grip_calls),1)
                self.assertEqual(self.s.robot.calls,[])

    def test_wrong_program_no_fallback(self):
        self.s.robot.wrong_version=True
        with self.assertRaisesRegex(TeachingError,'Publish'):self.execute()
        self.assertEqual(self.s.robot.grip_calls,[]);self.assertEqual(self.s.grips,[])

    def test_lost_completion_stops_without_retry_or_open(self):
        self.s.robot.lose_reply=True
        with self.assertRaises(TimeoutError):self.execute()
        self.assertEqual(len(self.s.robot.grip_calls),1);self.assertEqual(self.stops,1)

    def test_delayed_servo_fault_does_not_leave_success(self):
        reads=0
        def feedback():
            nonlocal reads
            reads+=1
            if reads>=6:self.s.refusal='servo error 0x3230'
            return {'E1':self.s.robot.ext[0]}
        self.s.external_axes=feedback
        with self.assertRaisesRegex(TeachingError,'servo error'):self.execute()
        self.assertEqual(self.stops,1)

    def test_stop_during_force_move_stops_controller(self):
        self.s.robot.block_motion=True
        helper=threading.Thread(target=lambda:(self.s.robot.started.wait(2),self.run.stop_event.set()))
        helper.start()
        with self.assertRaisesRegex(TeachingError,'stopped'):self.execute()
        helper.join(3);self.assertEqual(self.stops,1)

    def test_duplicate_execute_never_recloses(self):
        self.execute();job=self.s.robot.jobs[-1]
        self.assertEqual(self.s.robot.set_sys_var_i(job),{'index':1,'value':-1})
        self.assertEqual(len(self.s.robot.grip_calls),1)

    def test_closed_claw_or_moved_pose_refused(self):
        self.s.robot.ext[0]=3.8
        with self.assertRaisesRegex(TeachingError,'open claw'):self.execute()
        self.s.robot.ext[0]=28;self.s.pose['X']+=1
        with self.assertRaisesRegex(TeachingError,'moved'):self.execute()
        self.assertEqual(self.s.robot.grip_calls,[])

    def test_logging_failure_prevents_motion(self):
        with self.assertRaises(OSError):
            self.executor.execute(self.run,self.receipt,PROFILE,{},lambda:(_ for _ in ()).throw(OSError('disk full')))
        self.assertEqual(self.s.robot.grip_calls,[])

    def test_profile_gate_and_receipt_bound_to_reviewed_values(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'profile.json';path.write_text(json.dumps(PROFILE))
            g=TorqueGrip(td,lambda:self.s,lambda:self.run,profile_path=path)
            g.completed_descent(dict(ok=True,executor='lua_descent'),self.s.pose_mm())
            self.assertTrue(g.public(self.s.status())['can_start'])
            changed=dict(PROFILE,force_limits=[11,20,30,40,50,60]);path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(TeachingError,'profile changed'):
                g.start(dict(ready=True,descent_id=g.receipt['id']))
            self.assertEqual(self.s.robot.grip_calls,[])
            for change in ({'reviewed':False},{'force_limits':None},{'force_units':''},{'source':''},{'e1_floor_mm':3.5},{'contact_torque_abs':float('nan')}):
                path.write_text(json.dumps(dict(PROFILE,**change)))
                with self.assertRaises(TeachingError):read_profile(path)
            with self.assertRaises(TeachingError):read_profile() # live template is deliberately unconfigured

    def test_ui_wrapper_dispatches_torque_once_and_logs_actual_contact(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'profile.json';path.write_text(json.dumps(PROFILE))
            g=TorqueGrip(td,lambda:self.s,lambda:self.run,profile_path=path)
            g.completed_descent(dict(ok=True,executor='lua_descent'),self.s.pose_mm())
            body=dict(ready=True,descent_id=g.receipt['id'])
            with patch.object(LuaTorqueGrip,'OBSERVE_SECONDS',.01),patch.object(LuaTorqueGrip,'POLL',.001):
                g.start(body);self.run._thread.join(3)
            self.assertFalse(self.run.active);self.assertTrue(self.run.result['ok'],self.run.result)
            self.assertEqual(len(self.s.robot.grip_calls),1);self.assertEqual(self.s.grips,[])
            saved=json.loads(Path(self.run.result['record']).read_text())
            self.assertEqual(saved['method'],'lua_torque_grip');self.assertEqual(saved['e1_position'],4.1)
            self.assertEqual(saved['force_profile'],PROFILE)
            with self.assertRaises(TeachingError):g.start(body)

    def test_current_api_routes_use_reference_grip_and_reject_stale_receipt(self):
        from test_researcher import console
        from pick_and_hold.Grip.reference_grip import ReferenceGrip
        self.assertIsInstance(console.position_grip,ReferenceGrip)
        before=console.position_grip.receipt
        client=console.app.test_client()
        with patch.object(console.runner,'start') as start:
            for url in ('/seq/grip','/researcher/api/grip/start'):
                response=client.post(url,json={'ready':True,'descent_id':'old'})
                self.assertFalse(response.get_json().get('ok',False))
            start.assert_not_called()
        self.assertEqual(console.position_grip.receipt,before)

    def test_full_pipeline_blocks_before_calibration_when_profile_missing(self):
        from test_lacry_pickup import PickupTests
        fixture=PickupTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.pickup.grip.configuration_ready=lambda:read_profile()
        self.assertFalse(fixture.pickup.public()['can_start'])
        with self.assertRaises(TeachingError):fixture.pickup.start()
        self.assertEqual(fixture.calls,[])

    def test_build_preserves_descent_and_compiles_real_lua(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/'grip.bin';manifest=build(output=output)
            self.assertTrue(manifest['descent_unchanged']);self.assertTrue(manifest['trajectory_unchanged'])
            with zipfile.ZipFile(output) as z,zipfile.ZipFile(CONTROLLER_DIR/'main_hostpoint_descent_137.bin') as old:
                for name in old.namelist():
                    if name not in manifest['changed']:self.assertEqual(z.read(name),old.read(name))
                for name in manifest['changed']:
                    self.s.robot.lua.eval('function(s) local f,e=loadstring(s); assert(f,e) end')(z.read(name).decode())
                self.assertIn(b'Use the versioned Device 24',z.read('main/mod_HostPoint.lua'))


if __name__=='__main__':unittest.main()
