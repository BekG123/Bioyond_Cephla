"""Plan the actual saved routes without a controller or any motion calls."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lacry_backend import LacryBackend, ROOT
from latest_hamilton import LatestHamilton
from scope_compact137 import accepted


class TravelTests(unittest.TestCase):
    def setUp(self):
        plan,self.forward,_,self.trials=accepted()
        self.cfg=plan['params']
        self.service=SimpleNamespace(envelope=deepcopy(plan['envelope']))
        self.ham=LatestHamilton(ROOT/'demonstrations/return_home_20261016_130748',
                                None,None,lambda:self.cfg,None,None)
        # Geometry tests must not read mutable live robot trial outcomes.
        self.attempts=tempfile.TemporaryDirectory()
        self.addCleanup(self.attempts.cleanup)
        self.ham.attempts=Path(self.attempts.name)
        self.backend=LacryBackend(self.service,None,None,None,
            SimpleNamespace(target=lambda:(self.forward[0],'fixture-home')),self.ham,
            None,None,lambda:self.cfg,None,None,None)
        original,_,_=self.ham.reviewed()
        from hamilton_true_home import station_reference
        self.stations={
            'Home':(self.forward[0],self.trials['reverse']['final_robot']['joints']),
            'Squid':(self.forward[-1],self.trials['forward']['final_robot']['joints']),
            'Hamilton':station_reference(original)}

    def route(self,origin,action):
        pose,q=deepcopy(self.stations[origin])
        return self.backend.plan_travel(action,pose,q)

    def test_home_to_both_taught_stations(self):
        for action,destination in [('move_scope','Squid'),('move_hamilton','Hamilton')]:
            stages,end,_=self.route('Home',action)
            for axis in ('X','Y','Z','Rz'):
                self.assertAlmostEqual(end[axis],self.stations[destination][0][axis],delta=.02)
            self.assertTrue(stages)

    def reset_fixture(self):
        pose,q=deepcopy(self.stations['Squid'])
        state=dict(connected=True,ok=True,errors=[],enabled=False,
                   control_mode={'mode':'auto'},program_state={'state':'stopped'},
                   pose_mm=pose,joints=q,external_axes={'E1':0.02})
        self.service.status=Mock(return_value=state)
        self.backend.healthy=Mock(return_value=state)
        self.backend.run=SimpleNamespace(active=False)
        return state

    def test_reset_allows_read_only_home_plan_with_confirmed_startup(self):
        from lacry_agent import LacryAgent, PREPARE_NOTE
        from sequences import Runner
        state=self.reset_fixture()
        run=Runner();prepare=Mock()
        agent=LacryAgent(self.backend,Mock(),lambda:run,client=Mock(),prepare=prepare)
        with patch('lacry_backend.LuaTrajectory') as lua:
            lua.return_value.capability.return_value=dict(available=False,needs_initialization=True)
            plan=agent.propose(['move_home'])
        self.assertTrue(plan['prepare'])
        self.assertIn(PREPARE_NOTE,plan['requirements'])
        self.assertEqual(plan['steps'][-1]['points'][-1],self.forward[0])
        self.assertFalse(run.active)
        prepare.assert_not_called()
        lua.return_value.execute.assert_not_called()

    def test_queue_deferral_is_not_allowed_for_execution_or_running_uninitialized_app(self):
        from researcher_teaching import TeachingError
        state=self.reset_fixture()
        with patch('lacry_backend.LuaTrajectory') as lua:
            lua.return_value.capability.return_value=dict(available=False,needs_initialization=True)
            with self.assertRaisesRegex(TeachingError,'not initialized'):
                self.backend.compile(['move_home'],prepared=True)
            state['program_state']['state']='running'
            with self.assertRaisesRegex(TeachingError,'not initialized'):
                self.backend.compile(['move_home'],prepared=False)
            with self.assertRaisesRegex(TeachingError,'not initialized'):
                self.backend.execute_step(SimpleNamespace(stopped=lambda:False),dict(kind='travel'),{})
            lua.return_value.execute.assert_not_called()

    def test_old_or_missing_published_code_still_blocks_planning(self):
        from researcher_teaching import TeachingError
        self.reset_fixture()
        for cap,reason in [(dict(available=True,max_speed_mm_s=40),'requires 137'),
                           (dict(available=False,message='Queue read failed'),'Queue read failed')]:
            with patch('lacry_backend.LuaTrajectory') as lua:
                lua.return_value.capability.return_value=cap
                with self.assertRaisesRegex(TeachingError,reason):
                    self.backend.compile(['move_home'],prepared=False)

    def test_squid_pickup_lift_uses_existing_home_route(self):
        pose,q=deepcopy(self.stations['Squid'])
        pose['Z']+=5;q['J1']+=5
        self.assertEqual(self.backend.station(pose,q),'Squid')
        stages,end,_=self.backend.plan_travel('move_home',pose,q)
        self.assertEqual(len(stages),1)
        self.assertEqual(stages[0]['points'],list(reversed(self.forward))[1:])
        self.assertEqual(stages[0]['profile'],dict(scope_compact=True))
        self.assertEqual(end,self.forward[0])
        for axis in ('J2','J3','J4'):
            wrong=dict(q);wrong[axis]+=360
            self.assertEqual(self.backend.station(pose,wrong),'Other position')
        self.assertEqual(self.backend.station({**pose,'X':pose['X']+1},q),'Other position')

    def test_camera_plate_workflows_are_not_station_handling(self):
        for station in ('Hamilton','Squid'):
            pose,q=self.stations[station]
            for action in ('full_calibration','plate_calibration','align','descend','grip','camera_calibration'):
                with self.assertRaisesRegex(Exception,'not station handling'):
                    self.backend.camera_plate_only([action],dict(pose_mm=pose,joints=q))
        pose,q=self.stations['Home']
        self.backend.camera_plate_only(['full_calibration'],dict(pose_mm=pose,joints=q))
        self.backend.camera_plate_only(['move_scope'],dict(pose_mm=self.stations['Squid'][0]))

    def test_station_transfers_reach_saved_home_before_next_departure(self):
        for origin,action in [('Hamilton','transfer_hamilton_squid'),('Squid','move_hamilton')]:
            stages,_,_=self.route(origin,action)
            home_index=next(i for i,s in enumerate(stages)
                if all(abs(s['points'][-1][k]-self.forward[0][k])<.02 for k in ('X','Y','Z','Rz')))
            self.assertLess(home_index,len(stages)-1)
            self.assertEqual(stages[home_index]['points'][-1],stages[home_index+1]['start'])

    def test_box_exception_is_bound_to_exact_hamilton_route(self):
        stages,_,_=self.route('Home','move_hamilton')
        from hamilton_true_home import configured,segment_envelope,check_route
        review=configured()
        path=review['forward']
        self.assertIs(segment_envelope(path[0],path[1],self.service.envelope,review),self.service.envelope)
        self.assertIsNone(segment_envelope(path[1],path[2],self.service.envelope,review))
        leg=stages[-1]
        self.assertIsNone(self.backend.travel_envelope(leg['start'],leg['points'],leg['profile']))
        changed=deepcopy(leg['points']);changed[1]['Y']-=1
        with self.assertRaises(Exception):
            self.backend.travel_envelope(leg['start'],changed,leg['profile'])
        small=deepcopy(self.service.envelope);small['Z']=[70,220]
        with self.assertRaises(Exception):
            check_route(leg['start'],leg['points'],leg['joints'],self.cfg,small,review)

    def test_five_rounds_keep_plate_and_finish_each_round_at_home(self):
        pose,q=deepcopy(self.stations['Home'])
        self.backend.healthy=Mock(return_value=dict(pose_mm=pose,joints=q,external_axes={'E1':3.8}))
        self.backend.run=SimpleNamespace(active=False)
        with patch('lacry_backend.LuaTrajectory') as lua:
            lua.return_value.capability.return_value=dict(available=True,max_speed_mm_s=137)
            plan=self.backend.transport_rehearsal(5)
        self.assertFalse(plan['prepare'])
        self.assertEqual(plan['actions'],['move_hamilton','move_scope','move_home']*5)
        self.assertTrue(all(s['kind']=='travel' for s in plan['steps']))
        self.assertEqual(plan['e1'],3.8)
        for cycle in range(1,6):
            steps=[s for s in plan['steps'] if s['cycle']==cycle]
            self.assertEqual(len(steps),4)
            for axis in ('X','Y','Z','Rz'):
                self.assertAlmostEqual(steps[-1]['points'][-1][axis],pose[axis],delta=.02)

    def test_no_home_area_target_in_either_hamilton_direction(self):
        original,_,route=self.ham.reviewed()
        self.assertEqual(self.backend.station(route['start'],original['trajectory'][-1]['joints']),
                         'Other position')
        for origin,action in [('Home','move_hamilton'),('Hamilton','move_home'),
                              ('Hamilton','transfer_hamilton_squid')]:
            stages,_,_=self.route(origin,action)
            for stage in stages:
                self.assertNotIn('Home-area',stage['label'])
                self.assertNotIn(route['start'],stage['points'])
                self.assertNotIn({**route['start'],'Z':212.},stage['points'])
            self.assertEqual(len(stages[0]['points']),3)

    def test_rehearsal_requires_home_and_already_ready_controller(self):
        pose,q=deepcopy(self.stations['Squid'])
        self.backend.healthy=Mock(return_value=dict(pose_mm=pose,joints=q))
        with self.assertRaisesRegex(Exception,'saved Home'):
            self.backend.transport_rehearsal(5)
        self.backend.healthy.side_effect=RuntimeError('Auto is not ready')
        with self.assertRaisesRegex(RuntimeError,'Auto is not ready'):
            self.backend.transport_rehearsal(5)

    def test_failed_rehearsal_step_stops_remaining_rounds(self):
        from lacry_agent import LacryAgent
        from sequences import Runner
        backend=Mock();run=Runner()
        backend.execute_step.side_effect=[dict(ok=True),dict(ok=False,error='controller fault')]
        agent=LacryAgent(backend,Mock(),lambda:run,client=Mock())
        plan=dict(labels=['5 rounds'],steps=[dict(kind='travel',label=f'Round {i}/5',cycle=i) for i in range(1,6)])
        result=agent._execute(run,plan)
        self.assertFalse(result['ok']);self.assertEqual(backend.execute_step.call_count,2)
        self.assertIn('Round 2/5',agent.run_state['message'])


if __name__=='__main__':unittest.main()
