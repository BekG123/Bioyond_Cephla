"""Question answers retain context and never act as approval of a future plan."""
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lacry_agent import LacryAgent,PLAN_SECONDS
from sequences import Runner
from researcher_teaching import TeachingError


class QuestionTests(unittest.TestCase):
    def setUp(self):
        self.runner=Runner();self.backend=Mock();self.client=Mock()
        self.agent=LacryAgent(self.backend,Mock(),lambda:self.runner,client=self.client)
        self.agent.public=Mock(return_value={'ok':True})
        self.agent.credentials.model='fixture'

    def reply(self,text):return dict(content=[dict(type='text',text=text)])

    def test_exact_setup_question_yes_proposes_but_does_not_start(self):
        question=('I am asking what you need to do before calibration. Specifically:\n\n'
                  '1. **Is a 300 µL tip rack loaded at site 7 with the lid off?**\n'
                  '2. **Is the teaching needle seated in its holder?**\n'
                  'Once you confirm both, I can propose the full Hamilton calibration.')
        self.client.complete.return_value=self.reply(question)
        self.agent.send('Full Hamilton calibration')
        self.assertEqual(self.agent.question['options'],['Yes','No'])
        qid=self.agent.question['id']
        workflow=Mock()
        def propose(**kwargs):
            plan=dict(id='new-plan',at=time.time(),summary='Full Hamilton calibration',
                steps=[dict(kind='hamilton',label='Self-calibration then channels')],requirements=['Native setup instructions'])
            self.agent.pending=plan;return plan
        workflow.propose.side_effect=propose;self.agent.hamilton_workflow=Mock(return_value=workflow)
        self.client.complete.side_effect=[dict(stop_reason='tool_use',content=[dict(type='tool_use',
            name='plan_hamilton',id='plan',input=dict(action='full_calibration'))]),self.reply('Ready.')]
        self.agent.send('Yes')
        self.assertEqual(self.agent.pending['id'],'new-plan')
        self.assertIsNone(self.agent.question)
        self.assertFalse(self.runner.active)
        self.backend.execute_step.assert_not_called()
        self.backend.verify_confirmation.assert_not_called()
        calls=self.client.complete.call_args_list
        self.assertTrue(any(isinstance(m.get('content'),str) and 'Answer to your question: '+question in m['content']
                            for m in calls[1].args[0]['messages']))
        with self.assertRaisesRegex(TeachingError,'already answered or changed'):
            self.agent.answer_question(dict(question_id=qid,answer='Yes'))
        self.backend.verify_confirmation.assert_not_called()

    def test_structured_question_stops_for_human_without_extra_model_round(self):
        self.client.complete.return_value=dict(stop_reason='tool_use',content=[dict(type='tool_use',
            name='ask_researcher',id='ask',input=dict(question='Which instrument?',options=['Hamilton','Squid']))])
        self.agent.send('Calibrate it')
        self.client.complete.assert_called_once()
        self.assertEqual(self.agent.question['options'],['Hamilton','Squid'])
        self.assertEqual(self.agent.transcript[-1]['text'],'Which instrument?')

    def test_button_answer_keeps_question_context_and_rejects_duplicate(self):
        q=self.agent.ask_researcher('Which rack site?', ['Site 4','Site 7'])
        self.client.complete.return_value=self.reply('Recorded site 7.')
        self.agent.answer_question(dict(question_id=q['id'],answer='Site 7'))
        content=self.client.complete.call_args.args[0]['messages'][-1]['content']
        self.assertIn('Which rack site?',content);self.assertIn('Site 7',content)
        with self.assertRaises(TeachingError):self.agent.answer_question(dict(question_id=q['id'],answer='Site 7'))
        self.client.complete.assert_called_once()

    def test_open_questions_have_written_answer_button_contract(self):
        self.client.complete.return_value=self.reply('What is the rack part number?')
        self.agent.send('Identify tips')
        self.assertEqual(self.agent.question['options'],[])

    def test_no_does_not_start_or_repeat_the_setup_question(self):
        q=self.agent.ask_researcher('Are both items ready?', ['Yes','No'])
        self.client.complete.return_value=self.reply('Load the rack and seat the needle when ready.')
        self.agent.answer_question(dict(question_id=q['id'],answer='No'))
        self.assertIsNone(self.agent.pending);self.assertIsNone(self.agent.question)
        self.backend.execute_step.assert_not_called()

    def test_stale_question_cannot_approve_existing_plan(self):
        q=self.agent.ask_researcher('Which site?', ['4','7'])
        self.agent.pending=dict(id='plan',at=time.time(),steps=[],requirements=[])
        with self.assertRaises(TeachingError):self.agent.answer_question(dict(question_id=q['id'],answer='Yes'))
        self.backend.verify_confirmation.assert_not_called()

    def test_expired_question_is_not_answered(self):
        q=self.agent.ask_researcher('Ready?', ['Yes','No'])
        self.agent.question['at']=time.time()-PLAN_SECONDS-1
        with self.assertRaises(TeachingError):self.agent.answer_question(dict(question_id=q['id'],answer='Yes'))
        self.client.complete.assert_not_called()

    def test_question_answer_http_endpoint(self):
        from flask import Flask
        from researcher import register_researcher
        q=self.agent.ask_researcher('Which plate?', [])
        self.client.complete.return_value=self.reply('Recorded the plate.')
        app=Flask(__name__);register_researcher(app,lambda:{},lacry=self.agent)
        response=app.test_client().post('/researcher/api/lacry/question/answer',json=dict(question_id=q['id'],answer='96 wells'))
        self.assertEqual(response.status_code,200)
        self.backend.execute_step.assert_not_called()


if __name__=='__main__':unittest.main()
