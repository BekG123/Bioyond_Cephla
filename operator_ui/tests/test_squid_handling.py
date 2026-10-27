"""Full real planner/Lua execution against fake hardware only."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import squid_handling as handling
from lacry_agent import LacryAgent
from lacry_backend import LacryBackend, ROOT
from latest_hamilton import LatestHamilton
import test_scope_compact137 as scope_fixture


class SquidHandlingTests(unittest.TestCase):
    def setUp(self):
        scope_fixture.Scope137Tests.setUp(self)
        _, _, _, trials = handling_backend_evidence()
        self.s.pose = dict(self.path[0])
        self.s.q = dict(trials['reverse']['final_robot']['joints'])
        finish=self.s.robot.finish
        def finish_with_linear_axis():
            offset=self.s.q['J1']-self.s.pose['Z']
            finish()
            self.s.q['J1']=self.s.pose['Z']+offset
        self.s.robot.finish=finish_with_linear_axis
        self.s.robot.lua.globals().MOVFINISH=finish_with_linear_axis
        self.e1 = 3.7
        status = self.s.status
        self.s.status = lambda: {**status(), 'external_axes': {'E1':self.e1}}
        self.s.torque_report = lambda: dict(ok=True,telemetry_live=True,e1_position=self.e1,e1_torque=55.)
        self.s.move_gripper = self.jaw
        ham = LatestHamilton(ROOT/'demonstrations/return_home_20261016_130748',
                             None,None,lambda:self.cfg,None,None)
        ham.attempts = Path(self.temp.name)/'isolated_hamilton_attempts'
        self.backend = LacryBackend(self.s,self.run,None,SimpleNamespace(blocks_motion=False),
            SimpleNamespace(target=lambda:(self.path[0],'test-home')),ham,None,None,
            lambda:self.cfg,None,None,None)
        self.agent = LacryAgent(self.backend,Mock(),lambda:self.run,client=Mock())

    def stop(self, action):
        return scope_fixture.Scope137Tests.stop(self, action)

    def jaw(self, target, speed):
        self.assertEqual(speed, 5)
        self.s.grips.append(target)
        self.e1 = target
        return dict(ok=True)

    def test_dropoff_and_retrieval_use_actual_lua_and_preserve_grip_per_leg(self):
        for action, start_e1, end_e1 in [('squid_dropoff',3.7,5),('squid_retrieve',5,3.7)]:
            with self.subTest(action=action):
                self.e1=start_e1
                plan=self.agent.button(action)
                self.assertTrue(plan['executable'])
                self.assertFalse(plan['prepare'])
                self.backend.verify_confirmation(plan)
                before=len(self.s.robot.calls)
                self.agent.confirm(dict(ready=True,plan_id=plan['id']))
                result=self.run.finish()
                self.assertTrue(result['ok'],result)
                self.assertEqual(len(self.s.robot.calls)-before,9)
                speeds=[call[1] for call in self.s.robot.calls[before:]]
                self.assertEqual(speeds,[137]*3+[10]+[5]+[137]*4)
                self.assertEqual(self.e1,end_e1)
                for key in ('X','Y','Z','Rz'):
                    self.assertAlmostEqual(self.s.pose[key],self.path[0][key],delta=.01)
        self.assertEqual(self.s.grips,[5.,3.7])
        self.assertFalse(self.stops)

    def test_station_tool_proposes_executable_without_movement(self):
        result,error=self.agent._run_tool('plan_station_handling',
                                         dict(station='Squid',operation='release'))
        result=json.loads(result)
        self.assertFalse(error)
        self.assertTrue(result['executable'])
        self.assertTrue(result['awaiting_confirmation'])
        self.assertFalse(self.s.robot.calls)
        self.assertFalse(self.s.grips)

    def test_wrong_payload_start_fault_and_unready_controller_block(self):
        with self.assertRaisesRegex(Exception,'jaws at 5'):
            handling.plan(self.backend,'squid_retrieve')
        self.s.pose=dict(handling.SEATED)
        with self.assertRaisesRegex(Exception,'Return Home'):
            handling.plan(self.backend,'squid_dropoff')
        self.s.pose=dict(self.path[0])
        self.s.robot.program_state='stopped'
        with self.assertRaisesRegex(Exception,'not ready'):
            handling.plan(self.backend,'squid_dropoff')
        self.assertFalse(self.s.robot.calls)

    def test_changed_plan_and_evidence_are_rejected(self):
        plan=self.agent.button('squid_dropoff')
        bad=deepcopy(plan);bad['steps'][1]['target_e1']=7
        with self.assertRaisesRegex(Exception,'steps changed'):
            self.backend.verify_confirmation(bad)
        bad=deepcopy(plan);bad['steps'][2]['points'][0]['Z']+=1
        with self.assertRaisesRegex(Exception,'steps changed'):
            self.backend.verify_confirmation(bad)
        with patch.object(handling,'evidence',return_value={'changed':'hash'}):
            with self.assertRaisesRegex(Exception,'settings changed'):
                self.backend.verify_confirmation(plan)
        self.assertFalse(self.s.robot.calls)

    def test_failed_jaw_stops_before_lift_and_return(self):
        plan=self.agent.button('squid_dropoff')
        self.s.move_gripper=lambda *a,**kw:dict(ok=False,error='fixture fault')
        result=self.agent._execute(self.run,plan)
        self.assertFalse(result['ok'])
        self.assertEqual(len(self.s.robot.calls),4)

    def test_stop_after_arrival_prevents_jaw_and_return(self):
        plan=self.agent.button('squid_dropoff')
        original=self.backend.execute_step
        def execute(*args):
            result=original(*args)
            self.run.cancelled=True
            return result
        self.backend.execute_step=execute
        result=self.agent._execute(self.run,plan)
        self.assertFalse(result['ok'])
        self.assertFalse(self.s.grips)
        self.assertEqual(len(self.s.robot.calls),4)

    def test_jaw_telemetry_uncertainty_prevents_lift(self):
        plan=self.agent.button('squid_dropoff')
        self.s.torque_report=lambda:dict(ok=True,telemetry_live=True,e1_position=5,e1_torque=float('nan'))
        result=self.agent._execute(self.run,plan)
        self.assertFalse(result['ok'])
        self.assertEqual(len(self.s.robot.calls),4)

    def set_seated(self):
        _,pose,joints=self.backend.plan_travel('move_scope',self.s.pose_mm(),self.s.joints())
        self.s.pose=deepcopy(pose)
        self.s.q=deepcopy(joints)

    def test_already_seated_release_and_pickup_skip_outbound_travel(self):
        for action,opening,after in [('squid_dropoff',3.7,5.),('squid_retrieve',5.,3.7)]:
            with self.subTest(action=action):
                self.set_seated()
                self.e1=opening
                plan=self.agent.button(action)
                self.assertTrue(plan['seated_start'])
                self.assertEqual(plan['start_station'],'Squid')
                self.assertEqual([s['kind'] for s in plan['steps']],['squid_jaw','squid_lift','travel'])
                if action=='squid_dropoff':
                    self.assertIn('fully supported',' '.join(plan['requirements']))
                before=len(self.s.robot.calls)
                self.backend.verify_confirmation(plan)
                self.agent.confirm(dict(ready=True,plan_id=plan['id']))
                result=self.run.finish()
                self.assertTrue(result['ok'],result)
                self.assertEqual([call[1] for call in self.s.robot.calls[before:]],[5]+[137]*4)
                self.assertEqual(self.e1,after)
                for axis in self.path[0]:
                    self.assertAlmostEqual(self.s.pose[axis],self.path[0][axis],places=3)
        self.assertEqual(self.s.grips,[5.,3.7])

    def test_near_but_not_seated_never_opens(self):
        self.set_seated()
        base=deepcopy(self.s.pose)
        joints=deepcopy(self.s.q)
        for axis,amount in [('Z',5),('X',.1)]:
            self.s.pose={**base,axis:base[axis]+amount}
            self.s.q={**joints,'J1':joints['J1']+(amount if axis=='Z' else 0)}
            with self.assertRaisesRegex(Exception,'not at its taught seated'):
                handling.plan(self.backend,'squid_dropoff')
        self.assertFalse(self.s.grips)
        self.assertFalse(self.s.robot.calls)

    def test_changed_seated_pose_after_confirmation_does_not_open(self):
        self.set_seated()
        plan=self.agent.button('squid_dropoff')
        self.s.pose['X']+=.04
        with self.assertRaisesRegex(Exception,'not at its taught seated'):
            self.agent.confirm(dict(ready=True,plan_id=plan['id']))
        self.assertFalse(self.s.grips)

    def test_seated_wrong_joint_winding_is_not_accepted(self):
        self.set_seated()
        self.s.q['J4']+=360
        with self.assertRaisesRegex(Exception,'Return Home'):
            handling.plan(self.backend,'squid_dropoff')
        self.assertFalse(self.s.grips)

    def test_seated_failed_jaw_or_missing_feedback_blocks_retreat(self):
        self.set_seated()
        plan=self.agent.button('squid_dropoff')
        self.s.move_gripper=lambda *a,**kw:dict(ok=False,error='fixture fault')
        self.assertFalse(self.agent._execute(self.run,plan)['ok'])
        self.assertFalse(self.s.robot.calls)
        self.s.move_gripper=self.jaw
        self.s.torque_report=lambda:dict(ok=False)
        self.assertFalse(self.agent._execute(self.run,plan)['ok'])
        self.assertEqual(self.s.grips,[5.])
        self.assertFalse(self.s.robot.calls)

    def test_seated_stop_after_release_blocks_lift_and_return(self):
        self.set_seated()
        plan=self.agent.button('squid_dropoff')
        original=self.backend.execute_step
        def execute(*args):
            result=original(*args)
            self.run.cancelled=True
            return result
        self.backend.execute_step=execute
        self.assertFalse(self.agent._execute(self.run,plan)['ok'])
        self.assertEqual(self.s.grips,[5.])
        self.assertFalse(self.s.robot.calls)


def handling_backend_evidence():
    from scope_compact137 import accepted
    return accepted()


if __name__=='__main__':
    unittest.main()
