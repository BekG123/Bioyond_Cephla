"""Station travel chains the existing IK Home executor with one reservation."""
from copy import deepcopy
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_home_then_calibration as fixtures
import test_lacry_travel as travel_fixtures
from ik_home import IKHomeConnection
from sequences import Runner
from lacry_backend import StationConnectionRequired
from researcher_teaching import TeachingError
from station_via_home import continuation


class StationChainTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.CompoundTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.agent=self.fixture.agent;self.backend=self.fixture.backend
        self.run=self.fixture.run;self.calls=[]
        self.backend.compile.side_effect=StationConnectionRequired('Connect through Home')
        prefix=dict(dispatch='ik_home_return',home=self.fixture.home,target_id='saved-home',
            checked=[dict(pose=self.fixture.home,joints=dict(J1=1,J2=2,J3=3,J4=4))],
            steps=[dict(kind='home_return',label='Checked return Home')],requirements=['IK sweep clear'],
            preserve_gripper=True,e1=3.7,cfg={},envelope={})
        self.agent.reviewed_home=Mock()
        self.agent.reviewed_home.propose.side_effect=lambda:deepcopy(prefix)
        self.follow=dict(actions=['move_hamilton'],start=self.fixture.home,requirements=['Station clear'],
            steps=[dict(kind='travel',label='Taught Hamilton route')],e1=3.7)
        self.patch=patch('station_via_home.continuation',side_effect=lambda *a:deepcopy(self.follow))
        self.patch.start();self.addCleanup(self.patch.stop)
        cap=patch('station_via_home.LuaTrajectory');cap.start();self.addCleanup(cap.stop)
        blocker=patch('station_via_home.travel_program_blocker',return_value=None)
        blocker.start();self.addCleanup(blocker.stop)
        self.backend.healthy.return_value={}
        self.backend.healthy.side_effect=None
        def home_start(plan):
            def move(worker):self.calls.append('Home');return dict(ok=True)
            self.run.start('researcher_home',move)
            return dict(ok=True),'attempt.json'
        self.agent.reviewed_home.start.side_effect=home_start
        def destination(worker,step,plan):
            self.assertEqual(self.agent.reviewed_home.finish.call_count,1)
            self.calls.append('Hamilton');return dict(ok=True)
        self.backend.execute_step.side_effect=destination

    def propose(self,actions=None):
        return self.agent.propose(actions or ['move_hamilton'])

    def confirm(self,plan):
        self.agent.confirm(dict(ready=True,plan_id=plan['id']))
        self.fixture.pickup.thread.join(4)
        self.assertFalse(self.fixture.pickup.thread.is_alive())
        return self.fixture.pickup.public()

    def test_implicit_home_one_confirmation_and_no_pickup(self):
        plan=self.propose()
        self.assertEqual(plan['dispatch'],'station_via_home')
        self.assertEqual(plan['actions'],['move_home','move_hamilton'])
        self.assertEqual(self.calls,[])
        result=self.confirm(plan)
        self.assertTrue(result['ok'],result)
        self.assertEqual(self.calls,['Home','Hamilton'])
        self.assertFalse(self.run.reserved)
        with self.assertRaises(TeachingError):self.agent.confirm(dict(ready=True,plan_id=plan['id']))

    def test_explicit_home_and_squid_are_supported(self):
        for actions in (['move_home','move_hamilton'],['move_scope'],['move_home','move_scope']):
            self.assertEqual(self.propose(actions)['destination_action'],actions[-1])
        self.assertEqual(self.calls,[])

    def test_fault_or_other_refusal_does_not_trigger_fallback(self):
        self.backend.compile.side_effect=TeachingError('Robot fault')
        with self.assertRaisesRegex(TeachingError,'Robot fault'):self.propose()
        self.agent.reviewed_home.propose.assert_not_called()

    def test_failed_home_never_starts_station(self):
        def start(plan):
            self.run.start('researcher_home',lambda run:dict(ok=False,error='arrival unknown'))
            return dict(ok=True),'attempt.json'
        self.agent.reviewed_home.start.side_effect=start
        result=self.confirm(self.propose())
        self.assertFalse(result['ok'])
        self.backend.execute_step.assert_not_called()
        self.agent.reviewed_home.finish.assert_called_once()

    def test_home_arrival_or_gripper_mismatch_blocks_destination(self):
        self.backend.verify_confirmation.side_effect=TeachingError('Home arrival mismatch')
        result=self.confirm(self.propose())
        self.assertFalse(result['ok']);self.assertEqual(self.calls,['Home'])

    def test_stop_and_reservation_between_stages(self):
        entered,release=threading.Event(),threading.Event()
        def finish(*args):entered.set();self.assertTrue(release.wait(3))
        self.agent.reviewed_home.finish.side_effect=finish
        self.agent.confirm(dict(ready=True,plan_id=self.propose()['id']))
        self.assertTrue(entered.wait(3))
        self.assertFalse(self.run.start('intruder',lambda run:dict(ok=True))['ok'])
        self.agent.stop();release.set();self.fixture.pickup.thread.join(4)
        self.assertFalse(self.fixture.pickup.public()['ok'])
        self.assertEqual(self.calls,['Home'])

    def test_stale_route_is_rejected_before_home(self):
        plan=self.propose();self.follow['steps'][0]['label']='changed'
        with self.assertRaisesRegex(TeachingError,'route changed'):self.confirm(plan)
        self.agent.reviewed_home.start.assert_not_called()


class RecordedGeometryTests(unittest.TestCase):
    def test_reported_intermediate_pose_connects_to_both_saved_routes(self):
        fixture=travel_fixtures.TravelTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        backend=fixture.backend;service=fixture.service
        state=dict(connected=True,ok=True,errors=[],enabled=True,
            control_mode={'mode':'auto'},program_state={'state':'running'},external_axes={'E1':3.7},
            pose_mm=dict(X=262.091,Y=-62.724,Z=188.414,Rz=8.218),
            joints=dict(J1=149.8148004169095,J2=43.25394713358848,J3=44.0025278995151,J4=-79.03817868679097))
        service.status=lambda:deepcopy(state);service.envelope_enabled=True
        geometry_dir=Path(fixture.attempts.name)/'geometry';geometry_dir.mkdir()
        home_file=geometry_dir/'home.json';home_file.write_text('{}')
        home=SimpleNamespace(get_service=lambda:service,get_runner=lambda:Runner(),
            get_draggo=lambda:SimpleNamespace(public=lambda state:{'state':'off'}),
            target=backend.home.target,params=lambda:fixture.cfg,path=home_file)
        prefix=IKHomeConnection(home,geometry_dir/'ik').propose()
        for action in ('move_hamilton','move_scope'):
            follow=continuation(backend,prefix,action)
            self.assertEqual(follow['start'],prefix['home'])
            self.assertTrue(follow['steps'])
            self.assertEqual(follow['e1'],3.7)


if __name__=='__main__':unittest.main()
