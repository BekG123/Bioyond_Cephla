"""Explicit human yes uses the same confirmation path, never a model tool."""
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lacry_agent import LacryAgent, PLAN_SECONDS
from researcher_teaching import TeachingError
from sequences import Runner


class ChatConfirmationTests(unittest.TestCase):
    def test_recovery_acknowledgement_is_not_enabled_feedback(self):
        self.backend.s.clear_errors.return_value={'ok':True}
        self.backend.s.set_enable.return_value={'ok':True}
        self.backend.s.status.return_value=dict(connected=True,ok=True,errors=[],enabled=False)
        with self.assertRaisesRegex(TeachingError,'did not confirm'):
            self.agent._start_recovery({})
        self.assertIsNone(self.agent.pending)
        self.backend.s.program.assert_not_called()

    def test_recovery_reports_stopped_program_without_starting_it(self):
        self.backend.s.clear_errors.return_value={'ok':True}
        self.backend.s.set_enable.return_value={'ok':True}
        self.backend.s.status.return_value=dict(connected=True,ok=True,errors=[],enabled=True,
                                              program_state={'state':'stopped'})
        self.agent._start_recovery({})
        self.assertIn('motion program is stopped',self.agent.run_state['message'])
        self.assertIn('empty gripper',self.agent.run_state['message'])
        self.backend.s.program.assert_not_called()

    def test_refused_home_confirmation_discards_stale_yes(self):
        self.agent.reviewed_home = Mock()
        self.agent.reviewed_home.start.side_effect = TeachingError('Hand status unavailable')
        plan = dict(self.agent.pending)
        with self.assertRaisesRegex(TeachingError, 'Hand status'):
            self.agent._start_reviewed_home(plan)
        self.assertIsNone(self.agent.pending)
        self.agent.send('yes')
        self.agent.reviewed_home.start.assert_called_once()
        self.assertFalse(self.run.active)

    def test_home_refusal_is_reported_without_invented_reset_advice(self):
        self.agent.pending = None
        self.agent.credentials.model = 'fixture'
        reason = 'Saved Home attempt needs review; resetting the controller does not resolve it.'
        self.agent.propose = Mock(side_effect=TeachingError(reason))
        self.client.complete.side_effect = [
            dict(stop_reason='tool_use', content=[dict(type='tool_use', id='home',
                 name='propose_actions', input=dict(actions=['move_home']))]),
            dict(content=[dict(type='text', text='Reset the system and try again.')])]
        self.agent.send('Send the arm home')
        self.assertEqual(self.agent.transcript[-1]['text'], reason+' No Home movement was started.')
        self.backend.execute_step.assert_not_called()

    def setUp(self):
        self.run=Runner();self.backend=Mock();self.client=Mock()
        self.agent=LacryAgent(self.backend,Mock(),lambda:self.run,client=self.client)
        self.agent.public=Mock(return_value={'ok':True})
        self.agent.pending=dict(id='current-plan',at=time.time(),actions=['move_home'],
            labels=['Transport rehearsal'],requirements=['Route clear; plate secure; E-stop supervised'],
            steps=[dict(kind='travel',label='Round 1/5: Return Home')])
        self.backend.execute_step.return_value=dict(ok=True)

    def test_yes_starts_current_plan_once_without_model_call(self):
        self.agent.send('Yes, start!')
        self.run._thread.join(3)
        self.assertFalse(self.run._thread.is_alive())
        self.backend.verify_confirmation.assert_called_once()
        approved=self.backend.verify_confirmation.call_args.args[0]
        self.assertEqual(approved['id'],'current-plan')
        self.assertEqual(approved['confirmation_source'],'researcher_chat')
        self.backend.execute_step.assert_called_once()
        self.assertEqual(self.agent.run_meta['total_steps'], 1)
        self.assertIsNone(self.agent.pending)
        self.agent.send('yes')
        self.backend.execute_step.assert_called_once()
        self.client.complete.assert_not_called()

    def squid_plan_fixture(self, tool, arguments):
        self.agent.pending = None
        self.agent.credentials.model = 'fixture'
        workflow = Mock()
        def propose(*args, **kwargs):
            plan = dict(id='squid-plan', at=time.time(), summary='Retrieve plate to Home',
                        steps=[dict(kind='travel', label='Retrieve plate to Home')], requirements=['Route clear'])
            self.agent.pending = plan
            return plan
        workflow.propose.side_effect = propose
        self.client.complete.side_effect = [
            dict(stop_reason='tool_use', content=[dict(type='tool_use', id='plan',
                 name=tool, input=arguments)]),
            dict(content=[dict(type='text', text='Ready to run.')])]
        return workflow

    def test_complete_squid_request_includes_retrieval_even_if_model_omits_it(self):
        workflow = self.squid_plan_fixture('plan_squid_experiment', dict(retrieve=False))
        self.agent.automatic_workflow = Mock(return_value=workflow)
        self.agent.send('Yes, use the complete Squid experiment workflow')
        self.assertTrue(workflow.propose.call_args.kwargs['retrieve'])
        self.assertIn('Retrieve plate to Home', self.agent.transcript[-1]['text'])
        workflow.start.assert_not_called()
        self.backend.execute_step.assert_not_called()

    def test_explicit_leave_after_imaging_is_preserved(self):
        for message in ('Run the Squid experiment without retrieval',
                        'Run the Squid experiment, leave the plate at Squid after imaging',
                        "Run the Squid experiment but don't retrieve the plate"):
            with self.subTest(message=message):
                name, args = self.agent._squid_request_tool(
                    'plan_squid_experiment', dict(retrieve=False), message)
                self.assertEqual(name, 'plan_squid_experiment')
                self.assertFalse(args['retrieve'])

    def test_dropoff_during_experiment_does_not_mean_leave_after_imaging(self):
        _, args = self.agent._squid_request_tool('plan_squid_experiment', dict(retrieve=False),
            'Run full calibration then the Squid experiment, drop it there and wait till imaging finishes')
        self.assertTrue(args['retrieve'])

    def test_forgotten_retrieval_cannot_restart_calibration(self):
        workflow = self.squid_plan_fixture('plan_squid_experiment', dict(pickup_from_calibration=True))
        self.agent.retrieval_workflow = Mock(return_value=workflow)
        self.agent.automatic_workflow = Mock()
        self.agent.send('You forgot to return the plate home')
        workflow.propose.assert_called_once_with()
        self.agent.automatic_workflow.assert_not_called()
        workflow.start.assert_not_called()
        self.backend.execute_step.assert_not_called()

    def test_bring_plate_home_after_tracked_imaging_uses_retrieval(self):
        workflow = self.squid_plan_fixture('propose_actions', dict(actions=['full_calibration']))
        self.agent.retrieval_workflow = Mock(return_value=workflow)
        self.agent.propose = Mock()
        self.backend.squid.job_status.return_value = dict(status='completed', job=dict(run_id='current'))
        self.agent.send('Bring the plate home')
        workflow.propose.assert_called_once_with()
        self.agent.propose.assert_not_called()
        self.backend.execute_step.assert_not_called()

    def test_refused_retrieval_never_falls_back_to_calibration(self):
        workflow = self.squid_plan_fixture('plan_squid_experiment', {})
        workflow.propose.side_effect = TeachingError('This job already had a successful retrieval.')
        self.agent.retrieval_workflow = Mock(return_value=workflow)
        self.agent.automatic_workflow = Mock()
        self.agent.send('You forgot to return the plate')
        self.assertIn('already had a successful retrieval', self.agent.transcript[-1]['text'])
        self.assertIsNone(self.agent.pending)
        self.agent.automatic_workflow.assert_not_called()
        self.client.complete.assert_called_once()

    def test_unrelated_hardware_and_new_pickup_requests_are_not_rewritten(self):
        self.backend.squid.job_status.return_value = dict(status='completed', job=dict(run_id='old'))
        for message in ('Run full calibration and bring the plate home', 'Bring the arm home'):
            name, args = self.agent._squid_request_tool('propose_actions', dict(actions=['move_home']), message)
            self.assertEqual(name, 'propose_actions')
        self.backend.squid.job_status.return_value = dict(status='idle', job=None)
        name, _ = self.agent._squid_request_tool('propose_actions', {}, 'Bring the plate home')
        self.assertEqual(name, 'propose_actions')

    def test_inline_yes_records_acknowledgement_and_starts_only_once(self):
        self.agent.confirm_from_button(dict(ready=True,plan_id='current-plan'))
        self.run._thread.join(3)
        self.assertIn(dict(role='researcher',text='Yes'),
            [{k:m[k] for k in ('role','text')} for m in self.agent.transcript])
        self.assertTrue(any(m['role']=='lacry' and 'Running.' in m['text'] for m in self.agent.transcript))
        self.assertFalse(any('Reply' in m['text'] for m in self.agent.transcript))
        self.assertEqual(self.backend.verify_confirmation.call_args.args[0]['confirmation_source'],'researcher_button')
        with self.assertRaises(TeachingError):
            self.agent.confirm_from_button(dict(ready=True,plan_id='current-plan'))
        self.backend.execute_step.assert_called_once()
        self.client.complete.assert_not_called()

    def test_inline_yes_cannot_approve_stale_id_or_false_ready(self):
        for body in (dict(ready=True,plan_id='old-plan'),dict(ready=False,plan_id='current-plan'),dict(ready=True)):
            with self.assertRaises(TeachingError):self.agent.confirm_from_button(body)
        self.backend.verify_confirmation.assert_not_called()
        self.assertFalse(self.agent.transcript)

    def test_inline_yes_http_endpoint_uses_chat_acknowledgement(self):
        from flask import Flask
        from researcher import register_researcher
        app=Flask(__name__)
        register_researcher(app,lambda:{},lacry=self.agent)
        response=app.test_client().post('/researcher/api/lacry/confirm',
            json=dict(ready=True,plan_id='current-plan'))
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json['ok'])
        self.run._thread.join(3)
        self.assertTrue(any(m['role']=='lacry' and 'Running.' in m['text'] for m in self.agent.transcript))
        self.backend.execute_step.assert_called_once()

    def test_active_classic_progress_overrides_stale_model_confirmation(self):
        self.agent.pending=None
        self.agent.classic=Mock()
        self.agent.classic.public.return_value=dict(active=True,step='Align',done=['Calibrate'],
            ok=None,error='',message='Aligning with the plate.')
        # The shared runner may be between two stages while the workflow is active.
        self.assertFalse(self.run.active)
        reply=self.agent._ground_plan_reply('Reply Yes to confirm and start.')
        self.assertEqual(reply,'Aligning with the plate.')

    def test_expired_or_missing_plan_never_moves(self):
        self.agent.pending['at']=time.time()-PLAN_SECONDS-1
        self.agent.send('yes')
        self.agent.send('yes')
        self.assertFalse(self.run.active)
        self.backend.verify_confirmation.assert_not_called()
        self.client.complete.assert_not_called()

    def test_preview_only_cannot_be_started_by_chat(self):
        self.agent.pending.update(executable=False,blockers=['Hamilton control Coming Soon.'])
        with self.assertRaisesRegex(TeachingError,'preview only'):
            self.agent.send('Yes')
        self.backend.verify_confirmation.assert_not_called()
        self.assertFalse(self.run.active)

    def test_existing_readiness_failure_is_not_bypassed(self):
        self.backend.verify_confirmation.side_effect=TeachingError('The arm moved since this plan.')
        with self.assertRaisesRegex(TeachingError,'arm moved'):
            self.agent.send('yes')
        self.backend.execute_step.assert_not_called()
        self.assertFalse(self.run.active)

    def test_qualified_yes_and_questions_are_not_confirmation(self):
        for text in ('yes but do not start','yes, change speed first','can we start?',
                     'yes?','not yet','looks good','yes stop','what happens if I say yes'):
            self.assertFalse(self.agent.is_start_confirmation(text),text)
        for text in ('Yes','Yes, start','yes please','Go ahead','proceed'):
            self.assertTrue(self.agent.is_start_confirmation(text),text)

    def test_busy_or_result_review_does_not_start(self):
        self.agent.busy=True
        with self.assertRaises(TeachingError):self.agent.send('yes')
        self.agent.busy=False;self.agent.review={'id':'result-review'}
        with self.assertRaises(TeachingError):self.agent.send('yes')
        self.backend.verify_confirmation.assert_not_called()

    def test_chat_receives_async_failure_and_cannot_invent_pending_plan(self):
        self.agent.pending=None
        self.agent.credentials.model='fixture'
        self.agent.run_state.update(ok=False,error='Gripper feedback changed.',
                                    message='Stopped during travel.')
        self.agent._say('lacry','Stopped during travel: Gripper feedback changed.')
        self.client.complete.return_value=dict(content=[
            dict(type='text',text='The plan is ready and waiting. Reply Yes to start.')])
        self.agent.send('Drop the plate off at Squid')
        prompt=self.client.complete.call_args.args[0]['system']
        self.assertIn('Current host state',prompt)
        self.assertIn('"pending": null',prompt)
        self.assertIn('Gripper feedback changed.',prompt)
        answer=self.agent.transcript[-1]['text']
        self.assertIn('There is no plan waiting',answer)
        self.assertIn('Gripper feedback changed.',answer)
        self.assertNotIn('Reply Yes',answer)
        self.backend.execute_step.assert_not_called()

    def test_review_reply_uses_actual_inspection_not_start_confirmation(self):
        self.agent.pending=None
        self.agent.review=dict(label='Confirm the plate is supported.')
        reply=self.agent._ground_plan_reply('The plan is waiting. Reply Yes.')
        self.assertEqual(reply,'Waiting for your inspection: Confirm the plate is supported.')

    def test_cannot_confirm_phantom_pending_scope_plan(self):
        self.agent.pending=None
        reply=self.agent._ground_plan_reply(
            'Confirm the pending move_scope plan with "Yes", then I can help you drop it off.')
        self.assertIn('There is no plan waiting',reply)
        self.assertNotIn('pending move_scope',reply)

    def test_station_tool_refusal_is_not_reinterpreted(self):
        self.agent.credentials.model='fixture'
        self.agent.plan_station_handling=Mock(side_effect=TeachingError('Not at the seated Squid position.'))
        self.client.complete.return_value=dict(stop_reason='tool_use',content=[
            dict(type='tool_use',id='drop',name='plan_station_handling',
                 input=dict(station='Squid',operation='release'))])
        self.agent.send('Drop plate at Squid')
        self.assertEqual(self.agent.transcript[-1]['text'],
                         'Not at the seated Squid position. No movement was started.')
        self.assertIsNone(self.agent.pending)
        self.client.complete.assert_called_once()

    def test_calibration_refusal_cannot_be_recast_as_hand_guiding_or_skip_pickup(self):
        self.agent.credentials.model = 'fixture'
        reason = 'The post-calibration Squid connection needs review. Calibration uses the saved automatic pickup.'
        self.agent.propose = Mock(side_effect=TeachingError(reason))
        self.client.complete.side_effect = [
            dict(stop_reason='tool_use', content=[
                dict(type='tool_use', id='full', name='propose_actions',
                     input=dict(actions=['move_home','full_calibration','move_scope'])),
                dict(type='tool_use', id='skip', name='propose_actions',
                     input=dict(actions=['move_home','move_scope']))]),
            dict(content=[dict(type='text', text='You must teach the pickup by hand.')])]
        self.agent.send('Return Home, run calibration, then go to Squid')
        self.assertEqual(self.agent.transcript[-1]['text'], reason+' No movement was started.')
        self.assertIsNone(self.agent.pending)
        self.agent.propose.assert_called_once()
        self.client.complete.assert_called_once()
        results=self.agent.history[-2]['content']
        self.assertEqual({r['tool_use_id'] for r in results},{'full','skip'})
        self.backend.execute_step.assert_not_called()


if __name__=='__main__':unittest.main()
