"""Regression tests for pickup orchestration. Fake robot only; no network."""
from pathlib import Path
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sequences import Runner
from classic_pickup import ClassicPickup, STEPS, TRANSPORT_STEPS
from lacry_agent import LacryAgent
from researcher_teaching import TeachingError


class PickupTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.run = Runner(event_sink=lambda event, **kw:self.events.append((event, kw)))
        self.calls = []
        self.preview = Mock(return_value={'checked':True})
        self.fail = None
        self.after = None
        def start(action, job):
            self.calls.append(action)
            def execute(run):
                if action == 'Calibrate':
                    run.target = dict(x=300, y=-68, z_calibrated=70.5, rz=86)
                if self.after:
                    self.after(action)
                return dict(ok=action != self.fail, error='test failure' if action == self.fail else '')
            return self.run.start(job, execute)
        teaching = SimpleNamespace(public=lambda:dict(draft=dict(id='draft', revision=1)))
        plate = SimpleNamespace(start=lambda action, body:start(action, 'researcher_'+action.lower()))
        descent = SimpleNamespace(start=lambda body:start('Descend','researcher_descend'),
                                  preview_after_alignment=self.preview)
        grip = SimpleNamespace(public=lambda robot:dict(can_start=True,descent_id='receipt'),
                               start=lambda body:start('Grip','position_grip'))
        self.pickup = ClassicPickup(teaching, plate, descent, grip,
                                   lambda:SimpleNamespace(status=lambda:{}), lambda:self.run)
        self.poll = patch('classic_pickup.POLL_S', .001)
        self.poll.start();self.addCleanup(self.poll.stop)

    def finish(self):
        self.pickup.thread.join(5)
        self.assertFalse(self.pickup.thread.is_alive())
        self.assertFalse(self.run.reserved)
        return self.pickup.public()

    def test_all_four_legacy_entry_points_and_results_are_retained(self):
        self.pickup.start()
        state = self.finish()
        self.assertTrue(state['ok'],state)
        self.assertEqual(self.calls,['Calibrate','Align','Descend','Grip'])
        self.preview.assert_not_called()
        self.assertEqual(len(state['results']),4)
        self.assertTrue(any(e=='classic_pickup_finished' for e,_ in self.events))

    def test_old_stop_does_not_poison_new_explicit_start(self):
        self.run.request_stop()
        self.pickup.start()
        self.assertTrue(self.finish()['ok'])

    def test_added_descent_preview_does_not_block_original_four_step_order(self):
        self.preview.side_effect = TeachingError('Reference differs by 20.4 mm')
        self.pickup.start()
        state=self.finish()
        self.assertEqual(self.calls,['Calibrate','Align','Descend','Grip'])
        self.assertTrue(state['ok'])
        self.preview.assert_not_called()

    def test_original_descent_refusal_still_stops_before_grip(self):
        self.pickup.descent.start=Mock(side_effect=TeachingError('Alignment is outside the taught plate region.'))
        self.pickup.start()
        state=self.finish()
        self.assertEqual(self.calls,['Calibrate','Align'])
        self.assertFalse(state['ok'])
        self.assertEqual(state['step'],STEPS[2][2])
        self.assertEqual(state['done'],[STEPS[0][2],STEPS[1][2]])

    def test_failure_never_advances_or_retries(self):
        self.fail='Descend'
        self.pickup.start()
        state=self.finish()
        self.assertEqual(self.calls,['Calibrate','Align','Descend'])
        self.assertEqual(state['step'],STEPS[2][2])
        self.assertEqual(len(state['results']),3)
        self.assertIn('test failure',state['message'])

    def test_stop_in_gap_is_persistent_and_external_dispatch_is_blocked(self):
        reached,release = threading.Event(),threading.Event()
        await_step=self.pickup._await
        def pause_between_steps(job,label):
            result=await_step(job,label)
            if job=='researcher_calibrate':
                reached.set()
                self.assertTrue(release.wait(3))
            return result
        self.pickup._await=pause_between_steps
        self.pickup.start()
        self.assertTrue(reached.wait(3))
        self.assertFalse(self.run.active)
        self.assertTrue(self.pickup.public()['active'])
        self.assertFalse(self.run.start('intruder',lambda run:{'ok':True})['ok'])
        self.run.request_stop()  # Developer Stop must also stop the whole chain.
        release.set()
        self.assertFalse(self.finish()['ok'])
        self.assertEqual(self.calls,['Calibrate'])

    def test_stop_during_step_prevents_next_step(self):
        self.after=lambda action:self.pickup.stop() if action=='Calibrate' else None
        self.pickup.start()
        self.assertFalse(self.finish()['ok'])
        self.assertEqual(self.calls,['Calibrate'])

    def enable_transport(self):
        def dispatch(action,job,previous):
            self.calls.append(action)
            def execute(run):
                if self.after:self.after(action)
                return dict(ok=action != self.fail,error='test failure' if action == self.fail else '')
            return self.run.start(job,execute)
        self.pickup.transport=SimpleNamespace(
            configuration_ready=lambda:None,
            start_lift=lambda previous:dispatch('Lift','pickup_slow_lift',previous),
            start_home=lambda previous:dispatch('Home','researcher_home',previous),
            finish_home=Mock())
        self.pickup.steps=STEPS+TRANSPORT_STEPS

    def test_slow_lift_immediately_followed_by_home(self):
        self.enable_transport()
        self.pickup.start()
        result=self.finish()
        self.assertTrue(result['ok'])
        self.assertEqual(self.calls,['Calibrate','Align','Descend','Grip','Lift','Home'])
        self.assertEqual(len(result['results']),6)
        self.pickup.transport.finish_home.assert_called_once()
        self.assertIn('at Home',result['message'])

    def test_failed_lift_blocks_home_and_does_not_retry(self):
        self.enable_transport();self.fail='Lift'
        self.pickup.start()
        result=self.finish()
        self.assertFalse(result['ok'])
        self.assertEqual(self.calls,['Calibrate','Align','Descend','Grip','Lift'])
        self.pickup.transport.finish_home.assert_not_called()

    def test_failed_grip_blocks_lift(self):
        self.enable_transport();self.fail='Grip'
        self.pickup.start()
        self.assertFalse(self.finish()['ok'])
        self.assertEqual(self.calls,['Calibrate','Align','Descend','Grip'])

    def test_stop_after_slow_lift_blocks_home(self):
        self.enable_transport()
        self.after=lambda action:self.pickup.stop() if action=='Lift' else None
        self.pickup.start()
        self.assertFalse(self.finish()['ok'])
        self.assertNotIn('Home',self.calls)

    def test_failed_home_is_recorded_and_reported(self):
        self.enable_transport();self.fail='Home'
        self.pickup.start()
        result=self.finish()
        self.assertFalse(result['ok'])
        self.assertEqual(result['step'],'Return Home')
        self.pickup.transport.finish_home.assert_called_once()


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.run=Runner()
        self.backend=Mock()
        self.classic=Mock()
        self.classic.public.return_value=dict(can_start=True,active=False)
        self.classic.labels.return_value=[s[2] for s in STEPS]
        self.agent=LacryAgent(self.backend,Mock(),lambda:self.run,client=Mock(),classic_pickup=self.classic)

    def test_chat_full_calibration_and_button_share_legacy_workflow(self):
        for plan in [self.agent.button('full_calibration'),
                     self.agent.propose(['full_calibration']),
                     self.agent.propose(['plate_calibration','align','descend','grip'])]:
            self.assertEqual(plan['dispatch'],'classic_pickup')
            self.assertEqual(len(plan['steps']),4)
        self.backend.compile.assert_not_called()
        self.classic.start.assert_not_called()  # Proposals never move hardware.

    def test_integrated_plan_discloses_slow_lift_and_loaded_home(self):
        self.classic.labels.return_value=[s[2] for s in STEPS+TRANSPORT_STEPS]
        plan=self.agent.button('full_calibration')
        self.assertEqual(len(plan['steps']),6)
        self.assertIn('upward path',' '.join(plan['requirements']))
        self.assertIn('immediately returns Home',' '.join(plan['requirements']))
        self.classic.start.assert_not_called()

    def test_classic_activity_and_stop_visible_between_jobs(self):
        self.classic.public.return_value=dict(active=True,step='Align',done=['Calibrate'],ok=None,error='',message='Aligning')
        self.assertTrue(self.agent.public()['running']['active'])
        self.assertEqual(self.agent.public()['running']['step'],'Align')
        self.classic.stop.return_value=dict(ok=True,message='Stop requested')
        self.assertEqual(self.agent.stop()['message'],'Stop requested')

    def test_fast_completion_is_not_overwritten_as_running(self):
        plan=self.agent.button('full_calibration')
        def immediate(on_finish):
            on_finish(dict(active=False,ok=False,step='Calibrate',done=[],error='Camera disconnected',message='Camera disconnected'))
            return {'ok':True}
        self.classic.start.side_effect=immediate
        self.agent.confirm(dict(ready=True,plan_id=plan['id']))
        self.assertFalse(self.agent.run_state['active'])
        self.assertFalse(self.agent.run_state['ok'])
        self.assertIsNone(self.agent.pending)

    def test_confirmation_required(self):
        plan=self.agent.button('full_calibration')
        with self.assertRaises(TeachingError):self.agent.confirm(dict(plan_id=plan['id']))
        self.classic.start.assert_not_called()

    def test_missing_recorded_home_route_does_not_fall_back_to_new_ik(self):
        self.agent.home_return=Mock()
        self.backend.compile.side_effect=TeachingError('No accepted connection from this position.')
        with self.assertRaisesRegex(TeachingError,'No accepted connection'):
            self.agent.propose(['move_home'])
        self.assertEqual(self.agent.home_return.mock_calls,[])
        self.assertIsNone(self.agent.pending)

    def test_old_generated_home_plan_cannot_be_confirmed(self):
        import time
        self.agent.home_return=Mock()
        self.agent.pending=dict(id='old',at=time.time(),dispatch='home_return')
        with self.assertRaisesRegex(TeachingError,'newly generated route'):
            self.agent.confirm(dict(ready=True,plan_id='old'))
        self.agent.home_return.start.assert_not_called()

    def test_explicit_review_proposes_and_confirmed_result_is_reported(self):
        import time
        connection=Mock()
        self.agent.reviewed_home=connection
        self.backend.compile.side_effect=TeachingError('No reviewed connecting route.')
        connection.propose.return_value=dict(actions=['move_home'],dispatch='reviewed_home_return',
            steps=[dict(kind='home_return',label='Return Home')],requirements=['Route clear'],labels=['Return Home'])
        plan=self.agent.propose(['move_home'])
        connection.start.assert_not_called()
        with self.assertRaises(TeachingError):self.agent.confirm(dict(plan_id=plan['id']))
        def start(_):
            self.run.start('researcher_home',lambda run:dict(ok=True))
            return dict(ok=True),'attempt.json'
        connection.start.side_effect=start
        self.agent.confirm(dict(ready=True,plan_id=plan['id']))
        deadline=time.monotonic()+2
        while self.agent.run_state['active'] and time.monotonic()<deadline:time.sleep(.01)
        self.assertTrue(self.agent.run_state['ok'])
        self.assertEqual(self.agent.run_state['message'],'Returned to saved Home.')
        connection.finish.assert_called_once()
        self.assertEqual(self.agent.transcript[-1]['text'],'Returned to saved Home.')

    def test_failure_reports_actual_stage(self):
        self.backend.execute_step.side_effect=[{'ok':True},{'ok':False,'error':'bad marker'}]
        result=self.agent._execute(self.run,dict(labels=['Camera calibration'],steps=[
            dict(label='Find plate',kind='disk_find'),dict(label='Check marker',kind='disk_id')]))
        self.assertFalse(result['ok'])
        self.assertEqual(self.agent.run_state['step'],'Check marker')
        self.assertIn('Check marker',self.agent.run_state['message'])


if __name__=='__main__':unittest.main()
