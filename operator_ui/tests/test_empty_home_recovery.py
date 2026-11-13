"""Offline fault/payload/route checks; no hardware calls."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import empty_home_recovery as recovery

POSE=dict(X=311.895,Y=-67.58,Z=118.139,Rz=171.894)
JOINTS=dict(J1=79.5396,J2=40.3855,J3=59.27284,J4=72.2358)

class Service:
    def __init__(self):
        self.envelope={'X':(200,450),'Y':(-250,380),'Z':(70,400)}
        self.envelope_enabled=True;self.e1=0.;self.e2=90.69;self.calls=[]
        self.s=dict(connected=True,ok=True,enabled=False,errors=[],program_state={'state':'stopped'},pose_mm=deepcopy(POSE),joints=deepcopy(JOINTS))
    def status(self):return deepcopy(self.s)
    def clear_errors(self,confirmed):self.calls.append('clear');self.s['errors']=[];return {'ok':True}
    def set_enable(self,value,confirmed):self.calls.append('enable');self.s['enabled']=value;return {'ok':True}
    def program(self,action,force=False):
        self.calls.append(action)
        self.s['program_state']['state']='running' if action=='start' else 'stopped'
        if action=='start':self.e1=0
        return {'ok':True}
    def move_gripper(self,value,speed):self.calls.append('open');self.e1=value;return {'ok':True}
    def native(self):return dict(moving=False,emergency=False,drag=False,manual=False,error=bool(self.s['errors']),external_axes={'E1':self.e1,'E2':self.e2})

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.s=Service();self.cfg=recovery.build()['config']
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        for p in (patch.object(recovery,'raw',lambda s:s.native()),patch.object(recovery,'FOLDER',Path(self.tmp.name)),patch.object(recovery.time,'sleep',lambda _:None)):
            p.start();self.addCleanup(p.stop)
        self.run=SimpleNamespace(stopped=lambda:False,say=Mock())
    def plan(self):return json.loads(json.dumps(recovery.preview(self.s,self.cfg)))
    def queue(self,run,start,joints,points,cfg,speed,progress,**kwargs):
        self.assertEqual(speed,5);self.s.calls.append('travel')
        progress();self.s.s['pose_mm']=deepcopy(points[-1]);return {'ok':True}
    def test_preview_is_read_only_and_terminal_above_holder(self):
        p=self.plan();self.assertEqual(self.s.calls,[])
        self.assertEqual(p['points'][-1],recovery.HOME)
        self.assertTrue(all(x['Z']>=105.72 for x in p['points']))
    def test_empty_clearance_binds_current_holder_without_rotating(self):
        self.s.e2=91.628;p=self.plan()
        self.assertEqual(p['external_axes']['E2'],91.628)
        self.s.e2+=.2
        with self.assertRaisesRegex(Exception,'holder feedback changed'):
            recovery.execute(self.run,self.s,self.cfg,p,True)
        self.assertEqual(self.s.calls,[])
    def test_unconfirmed_payload_never_enables_or_starts(self):
        with self.assertRaisesRegex(Exception,'empty-jaw'):
            recovery.execute(self.run,self.s,self.cfg,self.plan(),False)
        self.assertEqual(self.s.calls,[])
    def test_unknown_region_and_nonfinite_pose_rejected(self):
        for p in (dict(POSE,Z=77),dict(POSE,X=370),dict(POSE,Rz=float('nan'))):
            self.s.s['pose_mm']=p
            with self.assertRaises(Exception):self.plan()
        self.assertEqual(self.s.calls,[])
    def test_changed_start_or_expired_plan_rejected_before_reset(self):
        p=self.plan();self.s.s['pose_mm']['X']+=.2
        with self.assertRaises(Exception):recovery.execute(self.run,self.s,self.cfg,p,True)
        self.assertEqual(self.s.calls,[])
        self.s.s['pose_mm']=deepcopy(POSE);p=self.plan();p['at']-=301
        with self.assertRaisesRegex(Exception,'expired'):recovery.execute(self.run,self.s,self.cfg,p,True)
    def test_json_plan_executes_clear_start_return_open_in_order(self):
        self.s.s['errors']=[{'errCode':3873}];p=self.plan()
        with patch.object(recovery,'LuaTrajectory') as q:
            q.return_value.execute.side_effect=self.queue
            result=recovery.execute(self.run,self.s,self.cfg,p,True)
        self.assertEqual(self.s.calls,['clear','enable','start','travel','open'])
        self.assertTrue(result['ok']);self.assertFalse(result['experiment_retried'])
        saved=json.loads(Path(result['record']).read_text());self.assertEqual(saved['status'],'completed')
    def test_start_failure_stops_no_travel_no_retry(self):
        self.s.program=Mock(return_value={'ok':False,'error':'startup uncertain'})
        with patch.object(recovery,'LuaTrajectory') as q:
            with self.assertRaisesRegex(Exception,'startup uncertain'):
                recovery.execute(self.run,self.s,self.cfg,self.plan(),True)
            q.assert_not_called()
        self.assertEqual(self.s.program.call_count,2)
        self.assertEqual(self.s.program.call_args.args,('stop',))
    def test_travel_failure_never_opens_or_retries(self):
        with patch.object(recovery,'LuaTrajectory') as q:
            q.return_value.execute.return_value={'ok':False,'error':'collision'}
            with self.assertRaisesRegex(Exception,'collision'):
                recovery.execute(self.run,self.s,self.cfg,self.plan(),True)
            self.assertEqual(q.return_value.execute.call_count,1)
        self.assertNotIn('open',self.s.calls);self.assertEqual(self.s.calls[-1],'stop')
    def test_stop_before_start_sends_no_motion(self):
        self.run.stopped=lambda:True
        with self.assertRaisesRegex(Exception,'stopped'):
            recovery.execute(self.run,self.s,self.cfg,self.plan(),True)
        self.assertEqual(self.s.calls,[])

    def test_agent_button_and_chat_tool_propose_without_motion(self):
        from lacry_agent import LacryAgent,TOOLS
        from sequences import Runner
        backend=Mock();backend.s=self.s;backend.params=lambda:self.cfg
        agent=LacryAgent(backend,Mock(),lambda:Runner(),client=Mock())
        agent._announce_plan=Mock();agent.note=Mock()
        plan=agent.button('recover')
        self.assertEqual(plan['dispatch'],'empty_home_recovery')
        self.assertTrue(any('removed from the jaws' in x for x in plan['requirements']))
        response,error=agent._run_legacy_tool('plan_robot_recovery',{})
        self.assertFalse(error);self.assertTrue(json.loads(response)['awaiting_confirmation'])
        self.assertIn('plan_robot_recovery',[t['name'] for t in TOOLS])
        self.assertEqual(self.s.calls,[])

    def test_agent_confirmation_consumed_once(self):
        from lacry_agent import LacryAgent
        from sequences import Runner
        runner=Runner();backend=Mock();backend.s=self.s;backend.params=lambda:self.cfg
        agent=LacryAgent(backend,Mock(),lambda:runner,client=Mock())
        agent._announce_plan=Mock();agent.note=Mock();agent._say=Mock()
        plan=agent.button('recover')
        with patch.object(recovery,'LuaTrajectory') as q:
            q.return_value.execute.side_effect=self.queue
            result=agent.confirm({'ready':True,'plan_id':plan['id']})
            runner._thread.join(3)
        self.assertEqual(result['started'],'empty_home_recovery')
        self.assertEqual(runner.state,'done');self.assertIsNone(agent.pending)
        with self.assertRaises(Exception):agent.confirm({'ready':True,'plan_id':plan['id']})
        self.assertEqual(self.s.calls.count('start'),1)

    def test_researcher_status_shows_recovery_active(self):
        from lacry_agent import LacryAgent
        runner=SimpleNamespace(active=True,name='empty_home_recovery')
        agent=LacryAgent(Mock(),Mock(),lambda:runner,client=Mock())
        agent.links=Mock(return_value={});agent.plate_session_status=Mock(return_value={})
        self.assertTrue(agent.public()['running']['active'])
        runner.active=False
        self.assertFalse(agent.public()['running']['active'])

if __name__=='__main__':unittest.main()
