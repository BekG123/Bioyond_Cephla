import copy
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import run_home as cli


class HomeCommandTests(unittest.TestCase):
    def setUp(self):
        self.home = dict(X=312.5,Y=-66.3,Z=105.72,Rz=89.84)
        self.start = dict(self.home,Z=150)
        self.state = dict(robot=dict(pose_mm=self.start,joints={'J1':100}))
        self.native = dict(external_axes={'E1':0})
        self.g = dict(home=self.home,cfg={},envelope={})
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.report_patch=patch.object(cli,'REPORTS',Path(folder.name))
        self.report_patch.start()
        self.addCleanup(self.report_patch.stop)

    def test_disconnected_preview_does_not_connect(self):
        with patch.object(cli,'api',return_value={'robot':{'connected':False}}) as api:
            with self.assertRaisesRegex(RuntimeError,'Console disconnected'):
                cli.checked_state()
        self.assertEqual(api.call_count,1)

    def test_initial_connection_once_then_reports_real_blockers(self):
        connected=dict(robot=dict(connected=True,ok=True,enabled=False,
            control_mode={'mode':'auto'},program_state={'state':'stopped'},errors=[]),
            envelope={'enabled':True},sequence={'active':False})
        with patch.object(cli,'api',side_effect=[{'robot':{'connected':False}}, {'ok':True},connected]) as api:
            with self.assertRaisesRegex(RuntimeError,'servos disabled; Lua program=stopped'):
                cli.checked_state(connect_if_needed=True)
        self.assertEqual([c.args[0] for c in api.call_args_list],['state','connect','state'])

    def test_lost_connection_during_run_does_not_reconnect(self):
        with patch.object(cli,'api',return_value={'robot':{'connected':False}}) as api:
            with self.assertRaisesRegex(RuntimeError,'Console disconnected'):
                cli.checked_state()
        api.assert_called_once_with('state')

    def test_execution_requires_explicit_empty_payload(self):
        with self.assertRaises(SystemExit):
            cli.parse_args(['--execute'])

    def test_saved_review_rejects_stale_or_changed_routes(self):
        plan=dict(schema='empty-home-connector-v1',destination='HOME',at=time.time(),
            start=self.start,start_joints={'J1':100},points=[self.home],endpoint=self.home,
            speed=5,cfg={},envelope={})
        cli.validate_review(plan,copy.deepcopy(plan))
        expired=dict(plan,at=time.time()-601)
        with self.assertRaisesRegex(RuntimeError,'expired'):
            cli.validate_review(expired,plan)
        changed=dict(plan,speed=137)
        with self.assertRaisesRegex(RuntimeError,'changed'):
            cli.validate_review(plan,changed)
        moved=dict(plan,start=dict(self.start,X=300))
        with self.assertRaises(Exception):
            cli.validate_review(plan,moved)

    def test_candidate_does_not_raise_from_below_home_clearance(self):
        robot={'pose_mm':dict(self.home,Z=75)}
        with self.assertRaisesRegex(RuntimeError,'station-specific retreat'):
            cli.connector(robot,self.g)

    def test_preview_never_sends_commands(self):
        with patch.object(cli,'checked_state',return_value=(self.state,self.native)), \
             patch.object(cli,'geometry',return_value=self.g), \
             patch.object(cli,'connector',return_value=([self.home],{})), \
             patch.object(cli,'api') as api, patch('builtins.print'):
            result=cli.main([])
        api.assert_not_called()
        self.assertEqual(result['destination'],'HOME')
        self.assertEqual(result['endpoint'],self.home)

    def test_unreviewed_new_route_rejected_before_any_command(self):
        state=copy.deepcopy(self.state)
        state['robot']['pose_mm']=dict(X=224.65,Y=-135.35,Z=296,Rz=-.65)
        with patch.object(cli,'checked_state',return_value=(state,self.native)), \
             patch.object(cli,'geometry',return_value=self.g), \
             patch.object(cli,'connector',return_value=([self.home],{})), \
             patch.object(cli,'api') as api:
            with self.assertRaisesRegex(RuntimeError,'physical clearance review'):
                cli.main(['--execute','--empty-gripper'])
        api.assert_not_called()

    def test_failed_move_stops_without_retry(self):
        calls=[]
        def api(path,body=None):
            calls.append((path,body))
            if path=='move':
                return {'ok':True,'recovered':True}
            return {'ok':True}
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(cli,'REPORTS',Path(folder)), \
             patch.object(cli,'checked_state',return_value=(self.state,self.native)), \
             patch.object(cli,'geometry',return_value=self.g), \
             patch.object(cli,'connector',return_value=([self.home],{})), \
             patch.object(cli,'api',side_effect=api), patch('builtins.print'):
            with self.assertRaisesRegex(RuntimeError,'no retry'):
                cli.main(['--execute','--empty-gripper'])
        self.assertEqual([p for p,b in calls],['move','program'])
        self.assertEqual(calls[-1][1],{'action':'stop'})

    def test_success_ends_at_holder_not_idle(self):
        state=copy.deepcopy(self.state)
        calls=[]
        def api(path,body=None):
            calls.append(path)
            if path=='move':
                state['robot']['pose_mm']={k:body[k.lower()] for k in self.home}
            return {'ok':True}
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(cli,'REPORTS',Path(folder)), \
             patch.object(cli,'checked_state',side_effect=lambda **kwargs:(copy.deepcopy(state),self.native)), \
             patch.object(cli,'geometry',return_value=self.g), \
             patch.object(cli,'connector',return_value=([self.home],{})), \
             patch.object(cli,'api',side_effect=api), patch('builtins.print'):
            result=cli.main(['--execute','--empty-gripper'])
        self.assertEqual(calls,['move'])
        self.assertEqual(result['status'],'completed_empty_HOME_clearance')
        self.assertEqual(result['final']['robot']['pose_mm'],self.home)


if __name__=='__main__':
    unittest.main()
