"""Calibration plans bind rack selection and share the existing confirmation path."""
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_hamilton_prep
from hamilton_workflow import HamiltonWorkflow
from lacry_agent import TOOLS
from researcher_teaching import TeachingError


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_hamilton_prep.PrepTests('test_decoding_nested_json');self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.adapter=self.fixture.adapter
        home=dict(X=0,Y=0,Z=0,Rz=0)
        self.runner=Mock(active=False,reserved=False)
        self.agent=SimpleNamespace(lock=threading.RLock(),review=None,pending=None,
            backend=SimpleNamespace(instrument=self.adapter,healthy=lambda **kw:dict(pose_mm=home),
                                    home=SimpleNamespace(target=lambda:(home,None))),
            get_runner=lambda:self.runner,_announce_plan=Mock(),_say=Mock())
        self.workflow=HamiltonWorkflow(self.agent)

    def test_full_plan_is_read_only_and_displays_all_stages_and_site(self):
        plan=self.workflow.propose('full_calibration',tip_site=4)
        self.assertTrue(plan['executable'],plan['blockers'])
        self.assertEqual(len(plan['steps']),2)
        self.assertNotIn('Initialize',plan['summary'])
        self.assertIn('site 4',plan['summary'])
        self.assertEqual(plan['calibration_setup']['reference_id'],'235903')
        self.assertTrue(all(m=='GET' for m,_,_ in self.fixture.device.calls))
        self.assertEqual(self.agent._announce_plan.call_count,1)
        self.assertIn('After self-calibration, when requested, load',' '.join(plan['requirements']))

    def test_one_execution_runs_all_stages_with_selected_site(self):
        self.fixture.device.rack_site=4
        run_action=self.adapter.run_action
        def with_operator(action,stopped,progress,**kwargs):
            def observe(state):
                progress(state)
                self.fixture.operator_answers(state)
            return run_action(action,stopped,observe,**kwargs)
        self.adapter.run_action=with_operator
        plan=self.workflow.propose('full_calibration',tip_site=4)
        self.agent.run_state={}
        result=self.workflow.execute(SimpleNamespace(stopped=lambda:False),plan)
        self.assertTrue(result['ok'],result)
        self.assertEqual(len(result['done']),2)
        self.assertFalse(any(p=='instruments/initialize' for _,p,_ in self.fixture.device.calls))
        self.assertEqual(sum(p=='calibration/channel-height-squeeze' for _,p,_ in self.fixture.device.calls),1)
        self.assertEqual(self.agent._announce_plan.call_count,1)

    def test_changed_settings_invalidate_confirmation(self):
        plan=self.workflow.propose('full_calibration')
        self.fixture.settings['timeout_s']=20
        import json
        self.fixture.config.write_text(json.dumps(self.fixture.settings))
        with self.assertRaisesRegex(TeachingError,'settings changed'):self.workflow.start(plan)
        self.assertTrue(all(m=='GET' for m,_,_ in self.fixture.device.calls))

    def test_agent_tool_exposes_channel_and_site(self):
        tool=next(t for t in TOOLS if t['name']=='plan_hamilton')['input_schema']['properties']
        self.assertIn('channel_calibration',tool['action']['enum'])
        self.assertEqual(tool['tip_site']['maximum'],8)
        self.assertNotIn('tip_labware_id',tool)


if __name__=='__main__':unittest.main()
