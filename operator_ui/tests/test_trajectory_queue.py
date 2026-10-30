"""Execute the real Lua module on Lua 5.1, with fake vendor functions. No hardware."""
from pathlib import Path
import json
import io
import math
import struct
import sys
import tempfile
import threading
import unittest
import zipfile
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lupa.lua51 import LuaRuntime
from trajectory_queue import LuaTrajectory, VERSION, checksum, prepare_points, locate
from build_trajectory_program import build, ROOT, CONTROLLER_DIR, HERE
from autonomy import check_path, TransferError
from test_transfer import PARAMS, FakeService
from test_researcher_workflow import FakeRunner


class Controller:
    connected = True
    def __init__(self, service, legacy=False):
        self.service = service
        self.vars, self.floats, self.calls, self.jobs = {},{},[],[]
        self.reply = None
        self.barriers = 0
        self.program_state = 'running'
        self.block_motion = False
        self.started, self.released = threading.Event(),threading.Event()
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        g = self.lua.globals()
        g.SetSysInVarI = self.vars.__setitem__
        g.GetSysParamF = lambda i:self.floats.get(i,0)
        g.SendSysOutVarI = lambda i,v:setattr(self,'reply',dict(index=i,value=v))
        g.GetCRobT = lambda *_:self.lua.table_from([service.pose[k] for k in ('X','Y','Z')]+[0,0,service.pose['Rz']])
        g.GetCJoints = lambda:self.lua.table_from([service.q[k] for k in ('J1','J2','J3','J4')]+[0,0,3.4,-2,0,0,0,0])
        g.GetElem = lambda t,i:t[i]
        g.RobTarget = lambda *args:self.lua.table_from(args)
        g.MoveL = self.move
        g.MOVFINISH = self.finish
        g.T0,g.U0 = 'T0','U0'
        if legacy:
            filename=f'main_hostpoint_trajectory_{legacy}.bin' if legacy in (47,55,70,80,100,130) else 'main_hostpoint_trajectory.bin'
            with zipfile.ZipFile(CONTROLLER_DIR/filename) as archive:
                source=archive.read('main/mod_Trajectory.lua').decode()
        else:source=(HERE/'lua/mod_Trajectory.lua').read_text()
        self.lua.execute(source)
        g.TrajectoryInit()

    def move(self,target,speed,zone,tool,user):
        self.calls.append((tuple(target[i] for i in range(1,13)),speed,zone,tool,user))
        self.started.set()

    def finish(self):
        self.barriers += 1
        if self.block_motion:
            if not self.released.wait(5): raise RuntimeError('Fake Stop never arrived')
            raise RuntimeError('Fake controller program stopped')
        for target,*_ in self.calls[getattr(self,'executed_count',0):]:
            end = dict(zip(('X','Y','Z','Rz'),target[:3]+(target[5],)))
            self.service.q=check_path(self.service.pose,end,self.service.q,getattr(self.service,'cfg',PARAMS),None)
            self.service.pose=end
        self.executed_count=len(self.calls)

    def set_sys_para_f(self,values):
        assert max(values)<=18
        # Real controller float registers may be single precision.
        self.floats.update({k:struct.unpack('f',struct.pack('f',v))[0] for k,v in values.items()})

    def set_sys_var_i(self,values,reply_timeout=10):
        self.jobs.append(values.copy())
        self.vars.update(values)
        for k,v in values.items(): setattr(self.lua.globals(),f'SYSINVAR{k}',v)
        self.reply = None
        self.lua.globals().mod_Trajectory()
        return self.reply

    def get_sys_var_i(self,indexes): return {i:self.vars.get(i,0) for i in indexes}
    def get_lua_app_status(self): return self.program_state=='running'
    def get_prog_state(self): return dict(state=self.program_state)


class QueueTests(unittest.TestCase):
    def test_uninitialized_program_does_not_diagnose_unpublished_registers(self):
        self.s.robot.program_state='stopped'
        self.s.robot.get_sys_var_i=Mock(side_effect=AssertionError('Registers are not initialized'))
        support=self.executor.capability()
        self.assertFalse(support['available'])
        self.assertTrue(support['needs_initialization'])
        self.s.robot.get_sys_var_i.assert_not_called()

    def setUp(self):
        self.s = FakeService()
        self.s.robot = Controller(self.s)
        self.s._locked = lambda fn:fn()
        self.s.program = self.stop
        self.executor = LuaTrajectory(self.s)
        self.run = FakeRunner()
        self.run.cancelled = False
        self.start, self.joints = self.s.pose.copy(), self.s.q.copy()
        self.points = [{**self.start,'Y':y} for y in (1,2,3,4,5,6,7)]
        self.points,self.expected = prepare_points(self.start,self.joints,self.points,PARAMS)
        self.events = []

    def stop(self,action):
        self.assertEqual(action,'stop')
        self.s.robot.program_state='stopped'
        self.s.robot.released.set()
        return dict(ok=True)

    def execute(self):
        return self.executor.execute(self.run,self.start,self.joints,self.points,PARAMS,40,
                                     lambda *args:self.events.append(args))

    def upload(self):
        header=[len(self.points),40,-1]+[self.start[k] for k in ('X','Y','Z','Rz')]+[self.joints[k] for k in ('J1','J2','J3','J4')]
        self.executor._job(1,123,dict(enumerate(header)))
        for i in range(0,len(self.points),3):
            batch=self.points[i:i+3]
            self.executor._job(2,123,dict(enumerate(v for p in batch for v in p.values())),i,len(batch))

    def test_complete_queue_one_barrier_order_external_axes_and_no_gripper(self):
        result=self.execute()
        r=self.s.robot
        self.assertTrue(result['ok'])
        self.assertEqual(result['points'],7)
        self.assertEqual(r.barriers,1)
        self.assertEqual(len(r.calls),7)

        self.assertEqual([j[4] for j in r.jobs],[6,1,2,2,2,3,4])
        self.assertEqual([c[0][1] for c in r.calls],list(range(1,8)))
        self.assertTrue(all(c[1:]==(40,-1,'T0','U0') for c in r.calls))
        self.assertTrue(all(c[0][6:]==(3.4,-2,0,0,0,0) for c in r.calls))
        self.assertEqual(self.s.grips,[])
        self.assertEqual(self.events[-1],('motion',100,100))
        with self.assertRaises(TransferError):self.executor._job(4,123)
        self.assertEqual(len(r.calls),7)

    def test_legacy_queue_still_executes_speed40(self):
        self.s.robot=Controller(self.s,legacy=True)
        self.assertEqual(self.executor.capability()['max_speed_mm_s'],40)
        self.assertTrue(self.execute()['ok'])

    def test_home_profile_rejects_unreviewed_wrong_shape_and_overspeed_before_jobs(self):
        for kwargs,speed in [(dict(home_speed137=True),137),
                             (dict(reviewed=True,home_transit=True,home_speed137=True),138),
                             (dict(reviewed=True,home_transit=True,home_speed137=True),137),
                             (dict(reviewed=True,home_transit=True,home_speed137=True,research_speed137=True),137)]:
            with self.assertRaises(TransferError):
                self.executor.execute(self.run,self.start,self.joints,self.points,PARAMS,speed,lambda *a:None,**kwargs)
        self.assertEqual(self.s.robot.jobs,[])

    def test_home_transit_rejects_diagonal_low_crossing_yaw_and_reversal(self):
        from straight_transfer import validate_home_transit
        start=dict(X=290.,Y=60.,Z=248.,Rz=0.)
        for points in ([{**start,'X':291.,'Z':300.}],
                       [{**start,'X':300.}],
                       [{**start,'Z':300.,'Rz':1.}],
                       [{**start,'Z':240.},{**start,'Z':300.}]):
            with self.assertRaises(TransferError):validate_home_transit(start,points)

    def test_lua_rejects_speed_over137_before_upload(self):
        header=[1,138,-1]+[self.start[k] for k in ('X','Y','Z','Rz')]+[self.joints[k] for k in ('J1','J2','J3','J4')]
        with self.assertRaises(TransferError):self.executor._job(1,123,dict(enumerate(header)))
        self.assertEqual(self.s.robot.calls,[])

    def test_upload_and_commit_never_move(self):
        self.upload()
        self.executor._job(3,123,offset=checksum(self.points))
        self.assertEqual(self.s.robot.calls,[])
        self.assertEqual(self.s.robot.barriers,0)
        self.assertEqual(self.s.robot.vars[18],2)

    def test_checksum_mismatch_prevents_execution(self):
        self.upload()
        with self.assertRaises(TransferError):self.executor._job(3,123,offset=checksum(self.points)+1)
        with self.assertRaises(TransferError):self.executor._job(4,123)
        self.assertEqual(self.s.robot.calls,[])

    def test_duplicate_or_out_of_order_append_poison_transaction(self):
        self.upload()
        with self.assertRaises(TransferError):self.executor._job(2,123,{0:1,1:2,2:3,3:4},0,1)
        with self.assertRaises(TransferError):self.executor._job(3,123,offset=checksum(self.points))
        self.assertEqual(self.s.robot.calls,[])

    def test_incomplete_upload_and_execute_without_commit(self):
        self.upload()
        with self.assertRaises(TransferError):self.executor._job(4,123)
        self.assertEqual(self.s.robot.calls,[])

    def test_lua_start_drift_blocks_motion_even_after_commit(self):
        self.upload()
        self.executor._job(3,123,offset=checksum(self.points))
        self.s.pose['Z']+=5
        with self.assertRaises(TransferError):self.executor._job(4,123)
        self.assertEqual(self.s.robot.calls,[])

    def test_restart_discards_committed_path(self):
        self.upload()
        self.executor._job(3,123,offset=checksum(self.points))
        self.s.robot.lua.globals().TrajectoryInit()
        with self.assertRaises(TransferError):self.executor._job(4,123)
        self.assertEqual(self.s.robot.calls,[])

    def test_old_controller_refused_without_any_write(self):
        self.s.robot.vars[17]=0
        with self.assertRaises(TransferError):self.execute()
        self.assertEqual(self.s.robot.jobs,[])

    def test_stale_version_register_cannot_dispatch_motion(self):
        self.s.robot.set_sys_var_i=Mock(return_value={'index':1,'value':-1})
        with self.assertRaisesRegex(TransferError,'handshake failed'):self.execute()
        self.s.robot.set_sys_var_i.assert_called_once()
        self.assertEqual(self.s.robot.calls,[])

    def test_vendor_move_l_backpressure_preserves_point_order(self):
        import re
        with zipfile.ZipFile(CONTROLLER_DIR/'main_hostpoint_trq.bin') as z:
            vendor=z.read('main/__lif.lua').decode().replace('\r','')
        wrapper=re.search(r'function MoveL\(.*?\nend',vendor,re.S).group()
        attempts=[]
        def enqueue(*args):
            attempts.append(args)
            if len(attempts)%3: return 0
            self.s.robot.move(*args)
            return 1
        self.s.robot.lua.globals()._MOVE_L=enqueue
        self.s.robot.lua.globals().DelayMS=lambda _:None
        self.s.robot.lua.execute(wrapper)
        self.execute()
        self.assertEqual(len(attempts),21)
        self.assertEqual([c[0][1] for c in self.s.robot.calls],list(range(1,8)))
        self.assertEqual(self.s.robot.barriers,1)

    def test_actual_hamilton_recording_both_directions_offline(self):
        from recorded_return import RecordedReturn
        path=HERE/'demonstrations/return_home_20261016_130748/return_path.json'
        if not path.exists():self.skipTest('Local recording not distributed with tests')
        data=json.loads(path.read_bytes())
        cfg=json.loads((HERE/'robot_params.json').read_text())
        for direction,count in [('toward_home',544),('to_hamilton',543)]:
            directed=RecordedReturn.directed(data,direction)
            first=directed['trajectory'][0]
            service=FakeService()
            service.cfg=cfg
            service.pose=first['pose_mm'].copy()
            service.q=first['joints'].copy()
            service.robot=Controller(service)
            service._locked=lambda fn:fn()
            service.program=Mock(return_value={'ok':True})
            replay=RecordedReturn(path.parent,lambda:service,lambda:self.run,lambda:cfg,Mock(),Mock())
            legs,_=replay.plan(directed)
            result=LuaTrajectory(service).execute(self.run,service.pose.copy(),service.q.copy(),legs,cfg,40,Mock())
            self.assertTrue(result['ok'])
            self.assertEqual(len(service.robot.calls),count)
            self.assertEqual(service.robot.barriers,1)
            service.program.assert_not_called()

    def test_cancel_during_upload_does_not_execute(self):
        original=self.s.robot.set_sys_var_i
        def cancel(values,**kwargs):
            result=original(values,**kwargs)
            if values[4]==2:self.run.cancelled=True
            return result
        self.s.robot.set_sys_var_i=cancel
        with self.assertRaises(TransferError):self.execute()
        self.assertEqual(self.s.robot.calls,[])
        self.assertEqual(self.s.robot.program_state,'stopped')

    def test_stop_during_motion_calls_controller_stop_without_queue_drain(self):
        self.s.robot.block_motion=True
        self.run.stopped=lambda:self.s.robot.started.is_set()
        with self.assertRaises(TransferError):self.execute()
        self.assertTrue(self.s.robot.released.is_set())
        self.assertEqual(self.s.pose,self.start)

    def test_failed_stop_latches_fault(self):
        self.s.robot.block_motion=True
        self.run.stopped=lambda:self.s.robot.started.is_set()
        self.s.program=Mock(return_value=dict(ok=False,error='Disconnected'))
        try:
            with self.assertRaisesRegex(TransferError,'Stop was not confirmed'):self.execute()
            self.assertTrue(self.s.trajectory_fault)
        finally:self.s.robot.released.set()

    def test_joint_violation_during_motion_stops_program(self):
        self.s.robot.block_motion=True
        original=self.s.joints
        self.s.joints=lambda:({**original(),'J2':94} if self.s.robot.started.is_set() else original())
        with self.assertRaisesRegex(TransferError,'joints exceed'):self.execute()
        self.assertTrue(self.s.robot.released.is_set())

    def test_corridor_violation_during_motion_stops_program(self):
        self.s.robot.block_motion=True
        original=self.s.pose_mm
        self.s.pose_mm=lambda:({**original(),'Z':original()['Z']+3} if self.s.robot.started.is_set() else original())
        with self.assertRaisesRegex(TransferError,'corridor'):self.execute()
        self.assertTrue(self.s.robot.released.is_set())

    def test_upload_timeout_is_never_retried(self):
        self.s.robot.set_sys_var_i=Mock(side_effect=TimeoutError('unknown reply'))
        with self.assertRaises(TimeoutError):self.execute()
        self.s.robot.set_sys_var_i.assert_called_once()
        self.assertEqual(self.s.robot.calls,[])
        self.assertEqual(self.s.robot.program_state,'stopped')

    def test_invalid_points_speed_and_kinematics_fail_without_writes(self):
        for points in ([],[{**self.start,'X':float('nan')}],[{**self.start,'X':526}]):
            with self.assertRaises(TransferError):prepare_points(self.start,self.joints,points,PARAMS)
        for speed in (0,-1,41,float('nan'),True):
            with self.assertRaises(TransferError):self.executor.execute(self.run,self.start,self.joints,self.points,PARAMS,speed,Mock())
        self.assertEqual(self.s.robot.jobs,[])

    def test_measured_polyline_progress(self):
        d,yaw,percent=locate({**self.start,'Y':3.5},[self.start]+self.points)
        self.assertEqual((d,yaw,percent),(0,0,50))

    def test_retraced_position_matches_orientation_on_same_segment(self):
        # Reproduced from the 64% false stop: the earlier pass is microscopically
        # closer in XYZ but its yaw is about 4.6 degrees away.
        path=[dict(X=230.47,Y=-9.4,Z=253.71,Rz=6.93),
              dict(X=228.24,Y=-9.8,Z=253.71,Rz=6.25),
              dict(X=229.18,Y=-9.63,Z=253.71,Rz=11.04),
              dict(X=229.7,Y=-9.54,Z=253.71,Rz=12.02)]
        pose=dict(X=229.258,Y=-9.617,Z=253.71,Rz=11.187)
        d,yaw,_=locate(pose,path)
        self.assertLess(d,.001)
        self.assertLess(yaw,.001)

    def test_in_place_yaw_interpolates_and_invalid_feedback_is_rejected(self):
        path=[self.start,{**self.start,'Rz':20}]
        d,yaw,_=locate({**self.start,'Rz':10},path)
        self.assertEqual((d,yaw),(0,0))
        with self.assertRaises(TransferError):locate({**self.start,'X':float('nan')},path)

    def test_matching_does_not_hide_true_position_or_yaw_departures(self):
        path=[self.start,{**self.start,'Y':10}]
        d,_,_=locate({**self.start,'Y':5,'Z':self.start['Z']+3},path)
        self.assertGreater(d,2)
        _,yaw,_=locate({**self.start,'Y':5,'Rz':self.start['Rz']+3},path)
        self.assertGreater(yaw,2)

    def test_build_preserves_station_modules_and_compiles_changed_lua(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'candidate.bin'
            manifest=build(output=path)
            self.assertEqual(manifest['protocol'],220108)
            self.assertEqual(manifest['max_speed_mm_s'],137)
            with zipfile.ZipFile(path) as new, zipfile.ZipFile(CONTROLLER_DIR/'main_hostpoint_trajectory_130.bin') as deployed:
                changed=[n for n in deployed.namelist() if deployed.read(n)!=new.read(n)]
                self.assertEqual(changed,['main/mod_Trajectory.lua'])
            self.assertEqual(set(manifest['changed']),{'main/mod_Trajectory.lua','main/mod_Socket.lua','main/mod_Init.lua','main/__loader.lua'})
            with zipfile.ZipFile(path) as new, zipfile.ZipFile(CONTROLLER_DIR/'main_hostpoint_trq.bin') as old:
                for name in old.namelist():
                    if name not in manifest['changed']:self.assertEqual(old.read(name),new.read(name))
                compile_lua=self.s.robot.lua.eval('function(s) local f,e=loadstring(s); assert(f,e); return true end')
                for name in manifest['changed']:self.assertTrue(compile_lua(new.read(name).decode()))

    def test_bioyond_payload_offsets_are_relative_to_stripped_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'candidate.bin'
            build(output=path)
            raw=path.read_bytes()
            self.assertEqual(raw[:7],b'byrobot')
            payload=raw[7:]
            eocd=payload.rfind(b'PK\x05\x06')
            _,_,_,count,total,size,start,comment=struct.unpack('<4s4H2LH',payload[eocd:eocd+22])
            self.assertEqual(count,total)
            self.assertEqual(start+size,eocd)
            self.assertEqual(payload[start:start+4],b'PK\x01\x02')
            cursor=start
            for _ in range(total):
                self.assertEqual(payload[cursor:cursor+4],b'PK\x01\x02')
                name_len,extra_len,comment_len=struct.unpack_from('<3H',payload,cursor+28)
                local_offset=struct.unpack_from('<L',payload,cursor+42)[0]
                self.assertEqual(payload[local_offset:local_offset+4],b'PK\x03\x04')
                cursor+=46+name_len+extra_len+comment_len
            self.assertEqual(cursor,eocd)
            with zipfile.ZipFile(io.BytesIO(payload)) as z, zipfile.ZipFile(CONTROLLER_DIR/'main_hostpoint_trq.bin') as old:
                self.assertIsNone(z.testzip())
                for n in old.namelist():
                    before,after=old.getinfo(n),z.getinfo(n)
                    for attr in ('create_system','external_attr','compress_type','date_time'):
                        self.assertEqual(getattr(before,attr),getattr(after,attr))


if __name__=='__main__':unittest.main()
