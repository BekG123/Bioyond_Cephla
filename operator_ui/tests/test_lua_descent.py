"""Real Lua 5.1, simulated vendor calls. No hardware or Flask connection."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lupa.lua51 import LuaRuntime
from test_transfer import FakeService, PARAMS
from test_trajectory_queue import Controller
from sequences import Runner
from pick_and_hold.Descend.lua_executor import LuaDescent, make_plan, VERSION
from autonomy import TransferError
from build_descent_program import build, ROOT, CONTROLLER_DIR


class DescentController(Controller):
    def __init__(self, service):
        super().__init__(service)
        self.e1 = 28
        self.torque_calls = 0
        self.spike_at = None
        self.zero_at = None
        self.nan_at = None
        self.change_jaws_at = None
        self.wrong_version = False
        self.no_arrival = False
        self.after_finish = None
        self.last_z = service.pose['Z']
        self.lua.globals().GetCJoints = lambda: self.lua.table_from(
            [service.q[k] for k in ('J1','J2','J3','J4')]+[0,0,self.e1,-2,0,0,0,0])
        self.lua.globals().GetCJointsNormTrq = self.read_torque
        self.lua.globals().DelayMS = lambda _: None
        self.lua.execute((ROOT/'operator_ui/lua/mod_Descent.lua').read_text())
        self.lua.globals().DescentInit()

    def read_torque(self):
        self.torque_calls += 1
        values = [.350, .010, .020, .030]
        if self.spike_at and self.torque_calls >= self.spike_at:
            values[2] = .300
        if self.zero_at == self.torque_calls:
            values = [0,0,0,0]
        if self.nan_at == self.torque_calls:
            values[0] = float('nan')
        if self.change_jaws_at == self.torque_calls:
            self.e1 = 0
        return self.lua.table_from(values)

    def finish(self):
        if self.no_arrival:
            return
        super().finish()
        if self.after_finish:
            self.after_finish()

    def set_sys_var_i(self, values, reply_timeout=10):
        self.jobs.append(values.copy())
        self.vars.update(values)
        for k,v in values.items():
            setattr(self.lua.globals(), f'SYSINVAR{k}', v)
        self.reply = None
        if self.wrong_version and values[4] == 6:
            return {'index':1,'value':220108}
        self.lua.globals().mod_Descent()
        return self.reply


class DescentTests(unittest.TestCase):
    def setUp(self):
        self.s = FakeService()
        self.s._locked = lambda fn: fn()
        self.s.robot = DescentController(self.s)
        self.s.program = self.stop
        self.stops = 0
        self.run = Runner()
        self.target = dict(x=326.,y=0.,rz=0.,z_calibrated=71.37)
        self.executor = LuaDescent(self.s)

    def stop(self, action):
        self.assertEqual(action, 'stop')
        self.stops += 1
        self.s.robot.program_state = 'stopped'
        self.s.robot.released.set()
        return dict(ok=True)

    def execute(self):
        return self.executor.execute(self.run, self.target, PARAMS, 66)

    def test_complete_fast_approach_slow_probe_no_grip(self):
        result = self.execute()
        self.assertTrue(result['ok'])
        calls = self.s.robot.calls
        self.assertEqual(calls[0][1],137)
        self.assertAlmostEqual(calls[0][0][2],91.37,places=4)
        self.assertTrue(all(c[1]==5 for c in calls[1:]))
        self.assertAlmostEqual(self.s.pose['Z'],71.37,places=4)
        self.assertEqual(self.s.robot.barriers,len(calls))
        self.assertTrue(all(c[0][6:]==(28,-2,0,0,0,0) for c in calls))
        self.assertEqual(self.s.grips,[])
        self.assertEqual(self.stops,0)
        zs = [c[0][2] for c in calls]
        self.assertTrue(all(b<a for a,b in zip(zs,zs[1:])))
        self.assertLessEqual(len(calls),29)

    def test_closed_jaws_never_move(self):
        self.s.robot.e1 = 0
        with self.assertRaisesRegex(TransferError,'claw'):
            self.execute()
        self.assertEqual(self.s.robot.calls,[])

    def test_feedback_rounding_tolerance(self):
        self.s.robot.e1 = 27.999
        self.assertTrue(self.execute()['ok'])

    def test_torque_breach_has_no_retreat_or_remaining_steps(self):
        self.s.robot.spike_at = 8
        with self.assertRaisesRegex(TransferError,'J3 torque'):
            self.execute()
        self.assertEqual(len(self.s.robot.calls),3) # approach + two probes
        self.assertEqual(self.stops,1)
        self.assertGreater(self.s.pose['Z'],self.target['z_calibrated'])

    def test_missing_initial_torque_never_moves(self):
        self.s.robot.zero_at = 1
        with self.assertRaisesRegex(TransferError,'torque'):
            self.execute()
        self.assertEqual(self.s.robot.calls,[])

    def test_invalid_probe_feedback_stops(self):
        self.s.robot.nan_at = 7
        with self.assertRaisesRegex(TransferError,'torque'):
            self.execute()
        self.assertEqual(len(self.s.robot.calls),2)

    def test_opening_changes_during_probe_stops(self):
        self.s.robot.change_jaws_at = 7
        with self.assertRaisesRegex(TransferError,'claw'):
            self.execute()
        self.assertEqual(len(self.s.robot.calls),2)

    def test_stale_arrival_aborts_before_probe(self):
        self.s.robot.no_arrival = True
        with self.assertRaisesRegex(TransferError,'arrival'):
            self.execute()
        self.assertEqual(len(self.s.robot.calls),1)

    def test_no_automatic_lift_from_bottom(self):
        self.s.pose['Z'] = self.target['z_calibrated']
        with self.assertRaisesRegex(TransferError,'never lifts'):
            self.execute()
        self.assertEqual(self.s.robot.calls,[])

    def test_envelope_and_alignment_rejected_before_upload(self):
        for update in ({'x':300},{'rz':10},{'z_calibrated':10}):
            with self.subTest(update=update):
                with self.assertRaises(TransferError):
                    self.executor.execute(self.run,{**self.target,**update},PARAMS,66)
                self.assertEqual(self.s.robot.jobs,[])

    def test_wrong_program_no_fallback_motion(self):
        self.s.robot.wrong_version = True
        with self.assertRaisesRegex(TransferError,'Publish'):
            self.execute()
        self.assertEqual(len(self.s.robot.jobs),1)
        self.assertEqual(self.s.robot.calls,[])

    def test_duplicate_execution_never_moves_again(self):
        self.execute()
        count = len(self.s.robot.calls)
        reply = self.s.robot.set_sys_var_i(self.s.robot.jobs[-1].copy())
        self.assertEqual(reply,dict(index=1,value=-1))
        self.assertEqual(len(self.s.robot.calls),count)

    def test_stop_during_motion_stops_controller(self):
        self.s.robot.block_motion = True
        trigger = threading.Thread(target=lambda: (self.s.robot.started.wait(2), self.run.stop_event.set()))
        trigger.start()
        with self.assertRaisesRegex(TransferError,'stopped by operator'):
            self.execute()
        trigger.join(3)
        self.assertEqual(self.stops,1)
        self.assertEqual(len(self.s.robot.calls),1)

    def test_malformed_plan_rejected_on_controller(self):
        plan = make_plan(self.s.pose,self.s.q,self.target,PARAMS,self.s.envelope,66)
        for index,value in ((9,138),(10,137),(11,0),(8,-1),(15,0),(0,float('nan'))):
            with self.subTest(index=index):
                header = plan['header'].copy(); header[index]=value
                self.s.robot.set_sys_para_f(dict(enumerate(header)))
                reply=self.s.robot.set_sys_var_i({0:23,1:1,2:10,3:0,4:1,5:0,6:0})
                self.assertEqual(reply,dict(index=1,value=-1))
                self.assertEqual(self.s.robot.calls,[])

    def test_stale_pose_before_execute_never_moves(self):
        original = self.s.robot.set_sys_var_i
        def change_pose(values, **kwargs):
            if values[4] == 2:
                self.s.pose['X'] += 1
            return original(values, **kwargs)
        self.s.robot.set_sys_var_i = change_pose
        with self.assertRaisesRegex(TransferError, 'start pose'):
            self.execute()
        self.assertEqual(self.s.robot.calls, [])

    def test_unconfirmed_completion_stops_and_never_retries(self):
        original = self.s.robot.set_sys_var_i
        def lose_reply(values, **kwargs):
            reply = original(values, **kwargs)
            if values[4] == 2:
                raise TimeoutError('lost completion reply')
            return reply
        self.s.robot.set_sys_var_i = lose_reply
        with self.assertRaisesRegex(TimeoutError, 'lost completion'):
            self.execute()
        self.assertEqual(self.stops, 1)
        self.assertEqual(sum(job[4] == 2 for job in self.s.robot.jobs), 1)

    def test_disabled_envelope_never_uploads(self):
        self.s.envelope_enabled = False
        with self.assertRaisesRegex(TransferError, 'workspace'):
            self.execute()
        self.assertEqual(self.s.robot.jobs, [])

    def test_archive_preserves_existing_trajectory_and_hostpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'candidate.bin'
            manifest=build(output=output)
            self.assertFalse(manifest['hardware_tested'])
            with zipfile.ZipFile(output) as z, zipfile.ZipFile(CONTROLLER_DIR/'main_hostpoint_trajectory_137.bin') as old:
                for name in ('main/mod_Trajectory.lua','main/mod_HostPoint.lua','main/__lif.lua'):
                    self.assertEqual(z.read(name),old.read(name))
                self.assertEqual(z.read('main/mod_Descent.lua'),(ROOT/'operator_ui/lua/mod_Descent.lua').read_bytes())
                self.assertIn(b'DescentInit()',z.read('main/mod_Init.lua'))
                self.assertIn(b'mod_Descent()',z.read('main/mod_Socket.lua'))


class DescentRouteTests(unittest.TestCase):
    def test_developer_route_dispatches_new_executor_only(self):
        from test_researcher import console
        from pick_and_hold.Descend.lua_executor import seq_descend_lua
        with patch.object(console.runner, 'start', return_value={'ok':True}) as start, \
                patch.object(console, '_refuse_if_sequencing', return_value=None), \
                patch.object(console.runner, 'target', {'x':326,'y':0,'rz':0,'z_calibrated':71.37}):
            response=console.app.test_client().post('/seq/descend_lua',json={})
            self.assertTrue(response.json['ok'])
            self.assertEqual(start.call_args.args[:2], ('descend_lua',seq_descend_lua))

    def test_active_sequence_cannot_change_target(self):
        from test_researcher import console
        from types import SimpleNamespace
        target = {'x':326,'y':0,'rz':0,'z_calibrated':71.37}
        with patch.object(console,'runner',SimpleNamespace(active=True,name='descend',target=target)):
            response=console.app.test_client().post('/seq/descend_lua',json={'x':1,'y':2,'z':3,'rz':4})
            self.assertFalse(response.json['ok'])
            self.assertIs(console.runner.target,target)


if __name__ == '__main__':
    unittest.main()
