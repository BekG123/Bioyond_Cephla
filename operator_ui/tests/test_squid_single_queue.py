"""Real Lua 5.1 protocol and accepted geometry, with fake hardware only."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
from unittest.mock import patch
import test_squid_handling as fixture
from test_trajectory_queue import Controller
from trajectory_queue import LuaTrajectory,checksum
import squid_single_queue as sq
from build_segment_speed_program import candidate_lua,build,SOURCE
import test_trajectory_queue as queue_fixture
import squid_queue_client as client

class SingleQueueTests(unittest.TestCase):
    setUp=fixture.SquidHandlingTests.setUp
    stop=fixture.SquidHandlingTests.stop
    jaw=fixture.SquidHandlingTests.jaw

    def prepare(self,new=True):
        self.s.external_axes=lambda:{'E1':self.e1}
        self.s.robot=Controller(self.s,source=candidate_lua() if new else None)
        finish=self.s.robot.finish
        def with_j1():
            offset=self.s.q['J1']-self.s.pose['Z'];finish();self.s.q['J1']=self.s.pose['Z']+offset
        self.s.robot.lua.globals().MOVFINISH=with_j1
        return self.s.robot

    def test_one_execute_and_barrier_per_direction_with_exact_slow_legs(self):
        r=self.prepare()
        with patch.object(sq,'FOLDER',Path(self.temp.name)/'records'):
            for direction,speeds in [('forward',[137,137,137,5]),('reverse',[5,137,137,137])]:
                count=len(r.calls);barriers=r.barriers;jobs=len(r.jobs)
                plan=sq.review(self.s,self.cfg,direction,direction)
                self.run.start(direction,sq.execute,self.s,self.cfg,plan)
                result=self.run.finish()
                self.assertTrue(result['ok'],result)
                self.assertEqual([c[1] for c in r.calls[count:]],speeds)
                self.assertEqual(r.barriers-barriers,1)
                self.assertEqual([j[4] for j in r.jobs[jobs:]],[6,8,9,9,3,4])
                self.assertTrue(all(c[2]==-1 for c in r.calls[count:]))
                self.assertEqual(self.s.grips,[])
                data=json.loads(sq.output_path(direction).read_bytes())
                self.assertEqual(data['status'],'completed_pending_operator_assessment')
                with self.assertRaisesRegex(Exception,'already attempted'):sq.review(self.s,self.cfg,direction,direction)

    def test_old_published_program_refused_without_writes(self):
        r=self.prepare(False)
        with self.assertRaisesRegex(Exception,'220109'):sq.review(self.s,self.cfg,'forward','old')
        plan,path,speeds=sq.route('forward')
        with self.assertRaisesRegex(Exception,'220109'):
            LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,path[1:],self.cfg,137,lambda *a:None,
                reviewed=True,squid_queue=True,segment_speeds=speeds)
        self.assertFalse(r.jobs);self.assertFalse(r.calls)

    def test_wrong_speed_route_or_workspace_refused(self):
        r=self.prepare();plan,path,speeds=sq.route('forward')
        for bad in ([137]*4,[137,137,137,10],[137,137,137],[137,137,137,float('nan')]):
            with self.assertRaises(Exception):
                LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,path[1:],self.cfg,137,lambda *a:None,
                    reviewed=True,squid_queue=True,segment_speeds=bad)
        path[-1]['X']+=.1
        with self.assertRaisesRegex(Exception,'exact accepted'):sq.validate_route(path[0],path[1:])
        self.s.envelope['Y']=(-250,390)
        with self.assertRaisesRegex(Exception,'workspace'):sq.review(self.s,self.cfg,'forward','changed')
        self.assertFalse(r.jobs)

    def upload(self,speeds):
        r=self.prepare();_,path,_=sq.route('forward');points=[sq.quantize(p) for p in path[1:]]
        ex=LuaTrajectory(self.s)
        header=[4,137,-1]+[path[0][k] for k in ('X','Y','Z','Rz')]+[self.s.q[k] for k in ('J1','J2','J3','J4')]
        ex._job(8,123,dict(enumerate(header)))
        for offset in (0,3):
            batch=points[offset:offset+3]
            values=[v for i,p in enumerate(batch) for v in list(p.values())+[speeds[offset+i]]]
            ex._job(9,123,dict(enumerate(values)),offset,len(batch))
        self.assertFalse(r.calls)
        return r,ex,points

    def test_speed_is_covered_by_checksum(self):
        r,ex,points=self.upload([137,137,137,137])
        with self.assertRaises(Exception):ex._job(3,123,offset=checksum(points,[137,137,137,5]))
        with self.assertRaises(Exception):ex._job(4,123)
        self.assertFalse(r.calls)

    def test_mixed_packet_cannot_be_used_in_uniform_transaction(self):
        r=self.prepare();ex=LuaTrajectory(self.s)
        header=[1,137,-1]+[self.s.pose[k] for k in ('X','Y','Z','Rz')]+[self.s.q[k] for k in ('J1','J2','J3','J4')]
        ex._job(1,123,dict(enumerate(header)))
        with self.assertRaises(Exception):ex._job(9,123,{0:290,1:62,2:300,3:0,4:5},0,1)
        self.assertFalse(r.calls)

    def test_old_uniform_client_runs_on_new_lua(self):
        old=queue_fixture.QueueTests('test_complete_queue_one_barrier_order_external_axes_and_no_gripper')
        old.setUp()
        old.s.robot=Controller(old.s,source=candidate_lua())
        old.test_complete_queue_one_barrier_order_external_axes_and_no_gripper()

    def test_lua_rejects_invalid_segment_speeds_before_motion(self):
        for bad in (0,-5,138,float('nan'),float('inf')):
            with self.subTest(speed=bad):
                with self.assertRaises(Exception):self.upload([137,137,137,bad])
                self.assertFalse(self.s.robot.calls)

    def test_http_adapter_dispatches_once_and_records_queue_completion(self):
        _,path,speeds=sq.route('forward')
        state={'robot':dict(connected=True,ok=True,enabled=True,errors=[],
            program_state={'state':'running'},control_mode={'mode':'auto'},
            external_axes={'E1':3.9},pose_mm=path[-1])}
        result=dict(ok=True,segment_speeds=speeds,completion_barriers=1)
        calls=[]
        def api(endpoint,body=None):
            calls.append(endpoint)
            if endpoint.endswith('/start'):return {'ok':True}
            if endpoint=='seq':return dict(name='squid_single_queue',active=False,result=result)
            if endpoint=='state':return state
            raise AssertionError(endpoint)
        with patch.object(client,'api',api):
            record=client.execute({},dict(leg_speeds=speeds),path,3.9,state,
                Path(self.temp.name)/'client.json','plan.json','hash')
        self.assertEqual(calls,['developer/api/squid-queue/start','seq','state'])
        self.assertEqual(record['queue_result'],result)
        self.assertTrue(all(s['status']=='completed_in_queue' for s in record['steps']))

    def test_stop_during_mixed_queue_stops_controller(self):
        r=self.prepare();r.block_motion=True
        self.run.stopped=lambda:r.started.is_set()
        _,path,speeds=sq.route('forward')
        with self.assertRaises(Exception):
            LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,path[1:],self.cfg,137,lambda *a:None,
                reviewed=True,squid_queue=True,segment_speeds=speeds)
        self.assertTrue(r.released.is_set())

    def test_vertical_guard_preserved(self):
        _,path,_=sq.route('forward')
        for p in ({**path[-1],'X':path[-1]['X']+.3},{**path[-1],'Z':path[-1]['Z']-1},{**path[2],'Z':290}):
            with self.assertRaises(Exception):sq.check_vertical_feedback(p,path)

    def test_package_preserves_all_other_modules_and_zip_header(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'new.bin';manifest=build(output=output)
            self.assertEqual(manifest['changed'],['main/mod_Trajectory.lua'])
            self.assertFalse(manifest['hardware_tested'])
            with zipfile.ZipFile(SOURCE) as old,zipfile.ZipFile(output) as new:
                for name in old.namelist():
                    if name!='main/mod_Trajectory.lua':self.assertEqual(old.read(name),new.read(name))
                self.assertEqual(new.read('main/mod_Trajectory.lua').decode(),candidate_lua())
            raw=output.read_bytes();self.assertEqual(raw[:7],b'byrobot')
            payload=raw[7:];end=payload.rfind(b'PK\x05\x06')
            fields=struct.unpack('<4s4H2LH',payload[end:end+22]);self.assertEqual(fields[6]+fields[5],end)

if __name__=='__main__':unittest.main()
