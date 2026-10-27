"""Execute the host state machine with fake robot/instruments, never hardware."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lacry_agent import LacryAgent,TOOLS
from lab_roundtrip import LabRoundTrip,phases
from hamilton_adapter import HamiltonAdapter
from sequences import Runner
from researcher_teaching import TeachingError


class Instruments:
    def __init__(self,events):self.events=events;self.n=0;self.failure=None;self.on_wait=None
    def status(self):return dict(available=True,protocols=['dispense'])
    def prepare(self,name=None,**kwargs):return dict(protocol=name,simulation=False)
    def prepare_loading(self,plan,stopped,home):
        home();self.events.append('stage_prepare');return dict(ok=True)
    def prepare_imaging(self,plan,stopped,home):
        home();self.events.append('scan_entry');return dict(ok=True)
    def verify(self,*a,**kw):return dict(connected=True)
    def start(self,plan,identity,save,*args):
        self.n+=1;ticket=dict(job_id=str(self.n),experiment_id=str(self.n),status='running')
        self.events.append('instrument_start');save(ticket);return ticket
    def wait(self,plan,ticket,save,stopped,progress):
        self.events.append('instrument_wait');progress({})
        if self.on_wait:self.on_wait()
        if stopped():raise TeachingError('Stopped')
        if self.failure:raise TeachingError(self.failure)
        ticket['status']='completed';save(ticket);return dict(ok=True)
    def completed_for_pickup(self,plan,ticket):
        if ticket['status']!='completed':raise TeachingError('Not completed')
    def observe(self,plan,ticket,save):return dict(completion_confirmed=ticket['status']=='completed')
    def restore_loading(self,plan,ticket,save,stopped,home):
        home();self.completed_for_pickup(plan,ticket);self.events.append('stage_return');return dict(ok=True)
    def abort_owned(self,*args):self.events.append('abort_owned')


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.events=[];self.run=Runner();self.backend=Mock()
        self.home=dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88)
        self.backend.home.target.return_value=(self.home,'home')
        self.backend.healthy.return_value=dict(pose_mm=self.home,external_axes={'E1':3.7})
        self.backend.execute_step.side_effect=self.motion
        self.agent=LacryAgent(self.backend,Mock(),lambda:self.run,client=Mock())
        self.ham=Instruments(self.events);self.squid=Instruments(self.events)
        self.engine=LabRoundTrip(self.agent,self.squid,self.ham,lambda:'accepted',Path(self.tmp.name))
        self.agent.roundtrip=self.engine
        self.engine.projected=lambda action:dict(actions=[action],steps=[dict(kind='travel',label=action)])
    def motion(self,r,step,plan):self.events.append(step['label']);return dict(ok=True)
    def finish(self,plan):
        self.agent.confirm(dict(ready=True,plan_id=plan['id']));self.engine.thread.join(5)
        self.assertFalse(self.engine.active);return self.agent.run_state
    def test_three_cycles_one_confirmation_correct_plate_order(self):
        plan=self.engine.propose(3,'dispense')
        self.assertTrue(plan['executable']);self.assertFalse(self.events)
        state=self.finish(plan);self.assertTrue(state['ok'],state)
        cycle=['instrument_start','instrument_wait','hamilton_retrieve','stage_prepare','squid_dropoff','scan_entry',
               'instrument_start','instrument_wait','stage_return','squid_retrieve','hamilton_dropoff']
        self.assertEqual(self.events,['hamilton_dropoff']+cycle*3)
        record=json.loads(next(Path(self.tmp.name).glob('*/workflow.json')).read_text())
        self.assertEqual(record['plate_location'],'hamilton');self.assertEqual(record['status'],'completed')
        self.assertEqual(len(state['done']),34);self.assertFalse(self.run.reserved)
        with self.assertRaises(TeachingError):self.agent.confirm(dict(ready=True,plan_id=plan['id']))

    def test_25_cycles_with_hamilton_calibration_once_one_confirmation(self):
        self.ham.run_action=lambda action,stopped,progress: self.events.append('hamilton_calibration') or dict(ok=True)
        plan=self.engine.propose(25,'dispense',hamilton_calibration=True)
        state=self.finish(plan)
        self.assertTrue(state['ok'],state)
        self.assertEqual(self.events[0],'hamilton_calibration')
        self.assertEqual(self.events.count('hamilton_calibration'),1)
        self.assertEqual(self.ham.n,25);self.assertEqual(self.squid.n,25)
    def test_hamilton_failure_stops_before_pickup(self):
        self.ham.failure='Dispensing failed';result=self.finish(self.engine.propose(2,'dispense'))
        self.assertFalse(result['ok']);self.assertNotIn('hamilton_retrieve',self.events)
        self.assertEqual(self.ham.n,1);self.assertEqual(self.squid.n,0)
    def test_imaging_failure_stops_before_retrieval_or_next_cycle(self):
        self.squid.failure='Imaging uncertain';result=self.finish(self.engine.propose(2,'dispense'))
        self.assertFalse(result['ok']);self.assertNotIn('squid_retrieve',self.events)
        self.assertEqual(self.ham.n,1)
    def test_reservation_blocks_other_motion_and_stop_blocks_pickup(self):
        def interrupt():
            self.assertFalse(self.run.start('competing',lambda r:dict(ok=True))['ok'])
            self.agent.stop()
        self.ham.on_wait=interrupt
        result=self.finish(self.engine.propose(2,'dispense'))
        self.assertFalse(result['ok']);self.assertNotIn('hamilton_retrieve',self.events)
    def test_uncommissioned_hamilton_returns_full_blocked_preview(self):
        self.engine.acceptance=Mock(side_effect=TeachingError('Loaded handling not accepted'))
        plan=self.engine.propose(5,'dispense')
        self.assertFalse(plan['executable']);self.assertEqual(len(plan['phases']),56)
        with self.assertRaises(TeachingError):self.agent.confirm(dict(ready=True,plan_id=plan['id']))
        self.assertFalse(self.events)
    def test_missing_connector_cannot_start_partial_robot_route(self):
        self.ham.status=lambda:dict(available=False,message='Coming Soon')
        self.ham.prepare=Mock(side_effect=TeachingError('Coming Soon'))
        plan=self.engine.propose(1,'dispense');self.assertIn('Coming Soon',plan['blockers'])
        with self.assertRaises(TeachingError):self.engine.start(plan)
        self.assertFalse(self.events)
    def test_changed_routes_and_acceptance_block_before_start(self):
        plan=self.engine.propose(1,'dispense');self.engine.acceptance=lambda:'changed'
        with self.assertRaises(TeachingError):self.engine.start(plan)
        self.assertFalse(self.events)
    def test_stale_no_does_not_cancel_new_plan(self):
        plan=self.engine.propose(1,'dispense')
        with self.assertRaises(TeachingError):self.agent.cancel('old-id')
        self.assertEqual(self.agent.pending['id'],plan['id'])
        self.agent.cancel(plan['id']);self.assertIsNone(self.agent.pending)
    def test_typed_tool_counts_whole_cycles(self):
        self.assertIn('plan_lab_roundtrip',{t['name'] for t in TOOLS})
        for count in (True,0,101,1.5):
            with self.assertRaises(TeachingError):phases(count)

    def calibration_fixture(self):
        import test_home_then_calibration as compound
        fixture=compound.CompoundTests('test_complete_chain_one_yes_and_single_reservation')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        engine=LabRoundTrip(fixture.agent,self.squid,self.ham,lambda:'accepted',Path(self.tmp.name))
        fixture.agent.roundtrip=engine
        engine.projected=self.engine.projected
        original=fixture.backend.execute_step.side_effect
        fixture.backend.execute_step.side_effect=lambda r,s,p: self.motion(r,s,p) if s['label']!='Return Home' else original(r,s,p)
        return fixture,engine

    def test_complete_cycle_uses_actual_station_planner_and_lua_on_fake_arm(self):
        import test_squid_handling as travel
        fixture=travel.SquidHandlingTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.backend.run=self.run
        agent=LacryAgent(fixture.backend,Mock(),lambda:self.run,client=Mock())
        engine=LabRoundTrip(agent,self.squid,self.ham,lambda:'accepted',Path(self.tmp.name))
        agent.roundtrip=engine
        plan=engine.propose(1,'dispense')
        self.assertTrue(plan['executable'],plan['blockers'])
        self.assertFalse(fixture.s.robot.calls)
        agent.confirm(dict(ready=True,plan_id=plan['id']));engine.thread.join(8)
        self.assertFalse(engine.active)
        self.assertTrue(agent.run_state['ok'],agent.run_state)
        self.assertEqual(fixture.s.grips,[5.,3.7,5.,3.7,5.])
        for axis in ('X','Y','Z','Rz'):
            self.assertAlmostEqual(fixture.s.pose[axis],fixture.path[0][axis],delta=.02)

    def test_calibration_once_then_two_cycles_under_same_confirmation(self):
        fixture,engine=self.calibration_fixture()
        plan=engine.propose(2,'dispense',pickup_from_calibration=True)
        self.assertTrue(plan['executable'],plan['blockers'])
        fixture.agent.confirm(dict(ready=True,plan_id=plan['id']))
        fixture.pickup.thread.join(5)
        self.assertFalse(engine.active)
        self.assertTrue(fixture.agent.run_state['ok'],fixture.agent.run_state)
        self.assertEqual(fixture.calls,['Initial Home','Calibrate','Align','Descend','Grip','Lift','Home'])
        self.assertEqual(self.ham.n,2);self.assertEqual(self.squid.n,2)
        self.assertFalse(fixture.run.reserved)

    def test_stop_during_calibration_gap_cancels_entire_roundtrip(self):
        fixture,engine=self.calibration_fixture()
        original=fixture.pickup._await
        def stop_after_calibration(job,label,*args,**kwargs):
            result=original(job,label,*args,**kwargs)
            if job=='researcher_calibrate':fixture.agent.stop()
            return result
        fixture.pickup._await=stop_after_calibration
        plan=engine.propose(2,'dispense',pickup_from_calibration=True)
        fixture.agent.confirm(dict(ready=True,plan_id=plan['id']))
        fixture.pickup.thread.join(5)
        self.assertFalse(engine.active);self.assertFalse(fixture.agent.run_state['ok'])
        self.assertEqual(fixture.calls,['Initial Home','Calibrate']);self.assertFalse(self.events)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        cfg=Path(self.tmp.name)/'config.json';cfg.write_text(json.dumps(dict(enabled=True,base_url='http://127.0.0.1:5055',timeout_s=1)))
        self.calls=[];self.last=None;self.bad=False;self.lost=False
        self.adapter=HamiltonAdapter(cfg,self.request,sleep=lambda s:None)
    def request(self,method,path,body):
        self.calls.append((method,path,body))
        if path=='/status':return dict(ok=True,session_id='session',simulation=False,state='completed' if self.last else 'idle',
            ready_for_robot=True,protocols=['dispense'],job_id='job' if self.last else None)
        if method=='POST':
            self.last=dict(body,ok=True,job_id='job')
            if self.lost:raise TimeoutError('Lost acknowledgement')
            return self.last
        return dict(self.last,status='completed',success=True,ready_for_robot=True,plate_id='wrong' if self.bad else self.last['plate_id'])
    def test_job_matching_and_pickup_confirmation(self):
        plan=self.adapter.prepare('dispense');saved=[]
        ticket=self.adapter.start(plan,'plate',saved.append)
        self.assertEqual(saved[0]['status'],'start_requested')
        self.assertTrue(self.adapter.wait(plan,ticket,saved.append,lambda:False,lambda s:None)['ok'])
        self.adapter.completed_for_pickup(plan,ticket)
    def test_wrong_plate_blocks_completion(self):
        plan=self.adapter.prepare('dispense');ticket=self.adapter.start(plan,'plate',lambda t:None);self.bad=True
        with self.assertRaises(TeachingError):self.adapter.wait(plan,ticket,lambda t:None,lambda:False,lambda s:None)
    def test_lost_ack_never_restarts(self):
        plan=self.adapter.prepare('dispense');self.lost=True;saved=[]
        with self.assertRaises(TimeoutError):self.adapter.start(plan,'plate',saved.append)
        self.assertEqual(sum(m=='POST' for m,p,b in self.calls),1)
        self.assertEqual(saved[-1]['status'],'uncertain')


if __name__=='__main__':unittest.main()
