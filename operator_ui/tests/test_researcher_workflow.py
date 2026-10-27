"""Offline staged teaching. No robot connections or automatic manual actions."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from researcher_teaching import StationTeaching, TeachingError, PLATE_WORKFLOW
from researcher_workflow import PlateTeaching


class FakeService:
    def __init__(self):
        self.pose = dict(X=250., Y=0., Z=310., Rz=0.)
        self.robot = SimpleNamespace(connected=True, get_joint_info=lambda: {'external': {'E1': 15.}})
        self.external_axes = lambda: {'E1': 15.}
        self.pose_mm = lambda: self.pose.copy()
        self.joints = lambda: dict(J1=310., J2=10., J3=20., J4=30.)
        self.status = lambda: dict(connected=True, ok=True, errors=[])


class FakeRunner:
    active = False
    state = 'idle'
    cancelled = False
    def start(self, name, fn, *args):
        self.name = name
        self.active, self.state, self.cancelled = True, 'running', False
        self.task = (fn, args)
        return {'ok':True}
    def finish(self):
        fn, args = self.task
        self.result = fn(self, *args)
        self.active = False
        return self.result
    def say(self, *args): pass
    def audit(self, *args, **kwargs): pass
    def stopped(self): return self.cancelled
    def request_stop(self):
        self.cancelled = True
        return {'ok':True}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.svc = FakeService()
        self.teaching = StationTeaching(Path(self.tmp.name)/'demo.json', lambda:self.svc, settle_seconds=0)
        self.teaching.start({'name':'Plate to Hamilton','workflow':'plate_pick_hamilton'})
        self.runner = FakeRunner()
        self.calibrate = Mock(return_value=dict(ok=True,target=dict(x=250,y=0,z_calibrated=200,rz=0,converged=True)))
        self.align = Mock(return_value=dict(ok=True))
        self.hand = SimpleNamespace(public=lambda state:dict(active=True))
        self.flow = PlateTeaching(self.teaching,lambda:self.runner,lambda:SimpleNamespace(info=lambda:dict(enabled=True)),lambda:self.hand,self.calibrate,self.align)
        self.flow._prepare = Mock()

    def body(self, **extra):
        draft = self.teaching.public()['draft']
        return dict(draft_id=draft['id'], revision=draft['revision'], **extra)

    def capture(self, station, **extra):
        return self.teaching.capture(self.body(station=station, **extra))

    def run_step(self, name):
        self.flow.start(name,self.body(ready=True))
        return self.runner.finish()

    def through_align(self):
        self.capture('Home')
        self.assertTrue(self.run_step('Calibrate')['ok'])
        self.assertTrue(self.run_step('Align')['ok'])

    def test_complete_order_manual_recording_and_export(self):
        self.through_align()
        self.svc.pose['Z'] = 200
        self.capture('Descend',performed=True)
        self.capture('Grip',performed=True)
        self.svc.pose['X'] = 320
        self.capture('Waypoint')
        self.capture('Hamilton')
        self.teaching.edit('save',self.body(reviewed=True))
        summary = self.teaching.public()['routines'][0]
        saved = self.teaching.export(summary['id'])
        self.assertEqual([p['station'] for p in saved['waypoints']],PLATE_WORKFLOW[:-1]+['Waypoint','Hamilton'])
        for point in saved['waypoints'][3:5]:
            self.assertEqual(point['kind'],'manual_action')
            self.assertEqual(point['gripper']['E1'],15)
            self.assertIsNone(point['command'])
            self.assertFalse(point['grip_verified'])
        self.assertFalse(saved['execution']['ready'])
        self.calibrate.assert_called_once()
        self.align.assert_called_once()
        self.assertEqual(self.flow._prepare.call_count, 2)

    def test_calibration_prepares_automatic_mode_after_explicit_click(self):
        self.capture('Home')
        self.assertTrue(self.run_step('Calibrate')['ok'])
        self.flow._prepare.assert_called_once()

    def test_recalibrate_archives_previous_attempt_without_undo(self):
        self.through_align()
        self.capture('Descend', performed=True)
        self.capture('Grip', performed=True)
        previous = self.teaching._load()['draft']['waypoints']
        self.assertTrue(self.flow.public()['can_calibrate'])
        self.assertTrue(self.run_step('Calibrate')['ok'])
        draft = self.teaching._load()['draft']
        self.assertEqual(draft['history'][0]['waypoints'], previous)
        self.assertEqual([p['station'] for p in draft['waypoints']], ['Home','Calibrate'])
        self.assertEqual(draft['waypoints'][0], previous[0])
        self.assertTrue(self.flow.public()['can_align'])
        self.assertTrue(self.run_step('Align')['ok'])

    def test_repeat_align_uses_verified_final_pose(self):
        self.align.side_effect = lambda *args: (self.svc.pose.update(X=260.) or dict(ok=True))
        self.through_align()
        self.assertEqual(self.flow.context['pose']['X'],260.)
        self.assertTrue(self.run_step('Align')['ok'])
        draft = self.teaching._load()['draft']
        self.assertEqual([p['station'] for p in draft['waypoints']], ['Home','Calibrate','Align'])
        self.assertEqual(len(draft['history']),1)

    def test_failed_repeat_keeps_history_and_removes_stale_completion(self):
        self.through_align()
        self.calibrate.return_value = dict(ok=False,error='missing disks')
        self.assertFalse(self.run_step('Calibrate')['ok'])
        draft = self.teaching._load()['draft']
        self.assertEqual([p['station'] for p in draft['waypoints']], ['Home'])
        self.assertEqual(len(draft['history'][0]['waypoints']),3)
        self.assertFalse(self.flow.public()['can_align'])

    def test_stale_align_repeat_does_not_edit_records(self):
        self.through_align()
        before = self.teaching._load()
        self.flow.invalidate()
        with self.assertRaises(TeachingError): self.flow.start('Align',self.body(ready=True))
        self.assertEqual(before,self.teaching._load())
        self.assertTrue(self.flow.public()['can_calibrate'])

    def test_calibration_does_not_require_draggo_to_be_active(self):
        self.capture('Home')
        self.hand.public = lambda state: dict(active=False)
        self.assertTrue(self.run_step('Calibrate')['ok'])
        self.calibrate.assert_called_once()
        self.flow._prepare.assert_called_once()

    def preparation_controller(self, mode='manual', enabled=True, program='stopped', drag=True):
        """Enforce the actual controller rule missed by the old permissive mocks."""
        calls = []
        state = dict(connected=True,ok=True,errors=[],control_mode={'mode':mode},
                     enabled=enabled,program_state={'state':program})
        hand = dict(blocked=drag, state='active' if drag else 'off')
        self.hand.public = lambda state: hand.copy()
        def exit_drag(value):
            calls.append(('draggo',value))
            self.assertFalse(value)
            state['enabled'] = False
            hand.update(blocked=False,state='off')
            return {'ok':True}
        def program_action(action):
            if action == 'start':
                self.assertEqual(state['control_mode']['mode'],'auto')
                self.assertTrue(state['enabled'])
            calls.append(('program',action))
            state['program_state']['state'] = 'running' if action == 'start' else 'stopped'
            return {'ok':True}
        def enable(value, ready):
            self.assertEqual(state['control_mode']['mode'],'auto', 'remoteEnable/remoteDisable sent in Manual')
            calls.append(('enable',value))
            state['enabled'] = value
            return {'ok':True}
        def switch(mode):
            self.assertFalse(state['enabled'],'Mode changed before confirmed disable')
            calls.append(('mode',mode))
            state['control_mode']['mode'] = mode
            return {'ok':True}
        self.hand.change = exit_drag
        self.svc.status = lambda: state
        self.svc.program = program_action
        self.svc.set_enable = enable
        self.svc.switch_mode = switch
        self.svc._preflight = lambda: None
        return state, calls

    def test_prepare_exits_draggo_before_enabling_program(self):
        state, calls = self.preparation_controller(program='paused')
        PlateTeaching._prepare(self.flow, self.runner, self.svc)
        self.assertEqual(calls, [('draggo',False),('program','stop'),
                                 ('mode','auto'),('enable',True),('program','start')])

    def test_manual_already_disabled_never_calls_remote_disable(self):
        state, calls = self.preparation_controller(enabled=False,drag=False)
        PlateTeaching._prepare(self.flow, self.runner, self.svc)
        self.assertEqual(calls,[('mode','auto'),('enable',True),('program','start')])

    def test_manual_enabled_uses_native_disable_before_switch(self):
        state, calls = self.preparation_controller(drag=False)
        PlateTeaching._prepare(self.flow, self.runner, self.svc)
        self.assertEqual(calls,[('draggo',False),('mode','auto'),('enable',True),('program','start')])

    def test_auto_enabled_stopped_program_can_use_remote_disable(self):
        state, calls = self.preparation_controller(mode='auto',drag=False)
        PlateTeaching._prepare(self.flow, self.runner, self.svc)
        self.assertEqual(calls,[('enable',False),('enable',True),('program','start')])

    def test_mode_acknowledgement_without_mode_change_never_enables(self):
        state, calls = self.preparation_controller(enabled=False,drag=False)
        self.svc.switch_mode = lambda mode: calls.append(('mode',mode)) or {'ok':True}
        with patch('researcher_workflow.time.monotonic',side_effect=[0,0,5]):
            with self.assertRaisesRegex(RuntimeError, 'did not confirm Auto mode'):
                PlateTeaching._prepare(self.flow, self.runner, self.svc)
        self.assertEqual(calls,[('mode','auto')])

    def test_stop_after_mode_switch_never_enables(self):
        state, calls = self.preparation_controller(enabled=False,drag=False)
        switch = self.svc.switch_mode
        def switch_and_stop(mode):
            result = switch(mode)
            self.runner.request_stop()
            return result
        self.svc.switch_mode = switch_and_stop
        with self.assertRaisesRegex(RuntimeError,'Stopped'):
            PlateTeaching._prepare(self.flow,self.runner,self.svc)
        self.assertEqual(calls,[('mode','auto')])

    def test_existing_fault_prevents_all_preparation_commands(self):
        state, calls = self.preparation_controller(enabled=False,drag=False)
        state['errors'] = [{'errCode':3885}]
        with self.assertRaisesRegex(RuntimeError,'active alert'):
            PlateTeaching._prepare(self.flow,self.runner,self.svc)
        self.assertEqual(calls,[])

    def test_prepare_does_not_restart_already_ready_program(self):
        state, calls = self.preparation_controller(mode='auto',program='running',drag=False)
        PlateTeaching._prepare(self.flow, self.runner, self.svc)
        self.assertEqual(calls,[])

    def test_setup_failure_preserves_home_and_persists_failure_log(self):
        import json
        self.capture('Home')
        self.flow.calibration_logs = Path(self.tmp.name)/'logs'
        self.flow._prepare.side_effect = RuntimeError('test setup failure')
        self.assertFalse(self.run_step('Calibrate')['ok'])
        self.calibrate.assert_not_called()
        events = [json.loads(line) for line in next(self.flow.calibration_logs.glob('*.jsonl')).read_text().splitlines()]
        self.assertEqual([e['event'] for e in events], ['start','setup','failed'])
        self.assertEqual(self.teaching.public()['draft']['next_station'],'Calibrate')

    def test_hamilton_and_recorded_algorithms_cannot_skip_steps(self):
        self.capture('Home')
        for station in ('Hamilton','Descend','Grip','Calibrate','Align','Waypoint'):
            with self.assertRaises(TeachingError):
                self.capture(station,performed=True)
        self.assertFalse(self.calibrate.called)

    def test_explicit_confirmation_and_manual_only(self):
        self.capture('Home')
        with self.assertRaises(TeachingError):
            self.flow.start('Calibrate',self.body())
        with self.assertRaises(TeachingError):
            self.flow.start('Descend',self.body(ready=True))
        self.run_step('Calibrate'); self.run_step('Align')
        with self.assertRaises(TeachingError):
            self.capture('Descend')

    def test_failure_does_not_advance_and_can_retry(self):
        self.capture('Home')
        self.calibrate.return_value = dict(ok=False,error='no disk')
        self.assertFalse(self.run_step('Calibrate')['ok'])
        self.assertEqual(self.teaching.public()['draft']['next_station'],'Calibrate')

    def test_stopped_step_not_recorded(self):
        self.capture('Home')
        self.flow.start('Calibrate',self.body(ready=True))
        self.flow.stop()
        self.assertFalse(self.runner.finish()['ok'])
        self.assertEqual(self.teaching.public()['draft']['next_station'],'Calibrate')

    def test_align_rejects_stale_target_after_other_control(self):
        self.capture('Home'); self.run_step('Calibrate')
        self.flow.invalidate()
        with self.assertRaises(TeachingError):
            self.flow.start('Align',self.body(ready=True))
        self.align.assert_not_called()

    def test_alignment_fails_if_pose_changed_since_calibration(self):
        self.capture('Home'); self.run_step('Calibrate')
        self.svc.pose['X'] += 5
        self.assertFalse(self.run_step('Align')['ok'])
        self.align.assert_not_called()

    def test_adopt_existing_home_without_overwriting_it(self):
        self.teaching.edit('discard',self.body())
        self.teaching.start({'name':'Existing Home'})
        self.capture('Home')
        prior = self.teaching._load()['draft']['waypoints'][0].copy()
        self.flow.adopt(self.body())
        self.assertEqual(self.teaching.public()['draft']['next_station'],'Calibrate')
        self.assertEqual(self.teaching._load()['draft']['waypoints'][0],prior)

    def test_missing_gripper_read_does_not_save_manual_action(self):
        self.through_align()
        self.svc.external_axes = lambda: {}
        with self.assertRaisesRegex(TeachingError, 'Gripper position could not be read'):
            self.capture('Descend',performed=True)
        self.assertEqual(self.teaching.public()['draft']['next_station'],'Descend')

    def test_moving_gripper_does_not_save_manual_action(self):
        self.through_align()
        self.svc.external_axes = Mock(side_effect=[{'E1':15}, {'E1':16}])
        with self.assertRaisesRegex(TeachingError, 'gripper is still moving'):
            self.capture('Descend',performed=True)
        self.assertEqual(self.teaching.public()['draft']['next_station'],'Descend')

    def test_manual_capture_with_empty_legacy_external_feedback(self):
        self.through_align()
        self.svc.robot.get_joint_info = lambda: {'external': {}}
        self.svc.external_axes = Mock(return_value={'E1': 12.5})
        self.capture('Descend', performed=True)
        point = self.teaching._load()['draft']['waypoints'][-1]
        self.assertEqual(point['gripper'], {'E1': 12.5})
        self.assertEqual(point['gripper_units'], {'E1': 'mm'})
        self.assertEqual(point['gripper_source'], 'native_motion_status')
        self.assertEqual(self.svc.external_axes.call_count, 2)

    def test_native_feedback_timeout_preserves_draft(self):
        self.through_align()
        before = self.teaching._load()
        self.svc.external_axes = Mock(side_effect=TimeoutError('native read timed out'))
        with self.assertRaisesRegex(TeachingError, 'Gripper position could not be read'):
            self.capture('Descend', performed=True)
        self.assertEqual(self.teaching._load(), before)


if __name__ == '__main__':
    unittest.main()
