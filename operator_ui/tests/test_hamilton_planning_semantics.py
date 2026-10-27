"""Route evidence and count scope, without instrument writes."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hamilton_handling import travel_status,handling_history
from hamilton_tip_experiment import propose
from lacry_agent import LacryAgent,TOOLS
from researcher_teaching import TeachingError
from sequences import Runner


class PlanningSemantics(unittest.TestCase):
    def setUp(self):
        self.runner=Runner();self.backend=Mock();self.client=Mock()
        self.agent=LacryAgent(self.backend,Mock(),lambda:self.runner,client=self.client)
        self.engine=Mock()
        self.engine.catalog.return_value=dict(blockers=['Unattended door access is not commissioned.'])
        self.engine.hamilton.calibration_setup.return_value=dict(tip_site=7,tip_labware_id=273)
        self.engine.imaging.prepare.return_value=dict(profile={'selection_source':'current'},simulation=True)
        self.agent.roundtrip=self.engine
        self.agent.links=Mock(return_value={})

    def test_real_evidence_distinguishes_travel_supervised_handling_and_automation(self):
        travel=travel_status();history=handling_history()
        self.assertTrue(travel['travel_verified'],travel)
        self.assertFalse(travel['payload_verified'])
        self.assertFalse(travel['motion_authorized'])
        self.assertFalse(history['completed_supervised'],history)
        self.assertIn('differs from the current setup',history['message'])
        self.assertFalse(history['automatic_acceptance'])
        with patch('hamilton_true_home.configured',side_effect=ValueError('source changed')):
            self.assertFalse(travel_status()['empty_travel_verified'])

    def test_five_pairs_one_image_preserves_whole_request_and_cannot_start(self):
        plan=propose(self.agent,5,hamilton_calibration=True,arm_calibration=True)
        self.assertEqual(plan['counts'],dict(tip_pairs=5,tips=10,imaging_runs=1,complete_roundtrips=0))
        phases=[s['phase'] for s in plan['steps']]
        self.assertEqual(phases[:3],['hamilton_calibration','arm_calibration','hamilton_dropoff'])
        self.assertEqual(phases.count('tip_pair'),5)
        self.assertEqual(phases.count('image_start'),1)
        self.assertEqual(phases.count('hamilton_dropoff'),1)
        self.assertNotIn('squid_retrieve',phases)
        self.assertEqual(plan['final_plate'],'Squid')
        self.engine.hamilton.prepare.assert_not_called()
        self.engine.imaging.prepare.assert_called_once_with(None,allow_loading_return=True)
        with self.assertRaises(TeachingError):self.agent.confirm(dict(ready=True,plan_id=plan['id']))
        self.backend.execute_step.assert_not_called()
        self.assertFalse(self.runner.active)
        self.assertIn('no pair-count parameter',' '.join(plan['blockers']))

    def test_invalid_count_or_review_does_not_replace_plan(self):
        self.agent.pending={'id':'old'}
        for bad in (True,0,1.5,101):
            with self.assertRaises(TeachingError):propose(self.agent,bad,False,False)
        self.agent.review={'id':'inspection'}
        with self.assertRaises(TeachingError):propose(self.agent,5,False,False)
        self.assertEqual(self.agent.pending,{'id':'old'})

    def test_tool_reply_has_explicit_units_and_grounded_blockers(self):
        result,error=self.agent._run_tool('plan_tip_waste_experiment',dict(pair_count=5,hamilton_calibration=False,arm_calibration=False))
        self.assertFalse(error)
        self.assertEqual(json.loads(result)['counts']['imaging_runs'],1)
        reply=self.agent._ground_plan_reply('Ready! Five imaging loops.',proposed=True)
        self.assertIn('exactly 5 two-tip',reply)
        self.assertIn('Preview only',reply)
        self.assertNotIn('Five imaging loops',reply)
        self.assertEqual(self.agent._plan_view(self.agent.pending)['counts']['tip_pairs'],5)
        self.assertIn('plan_tip_waste_experiment',{x['name'] for x in TOOLS})

    def test_calibration_choices_cannot_silently_default_to_omitted(self):
        result,error=self.agent._run_tool('plan_tip_waste_experiment',dict(pair_count=5))
        self.assertTrue(error)
        self.assertIsNone(self.agent.pending)
        schema=next(t['input_schema'] for t in TOOLS if t['name']=='plan_tip_waste_experiment')
        self.assertTrue({'hamilton_calibration','arm_calibration'}<=set(schema['required']))

    def test_wrong_loop_tool_is_rejected_before_publishing_or_motion(self):
        self.agent.credentials.model='fixture'
        self.client.complete.return_value=dict(stop_reason='tool_use',content=[dict(
            type='tool_use',id='wrong',name='plan_lab_roundtrip',input=dict(repetitions=5,hamilton_protocol='Protocol'))])
        self.agent.send('Hamilton pick and waste exactly 5 two-tip pairs, then image once at Squid')
        self.engine.propose.assert_not_called()
        self.backend.execute_step.assert_not_called()
        self.assertIsNone(self.agent.pending)
        self.assertIn('not a dispensing/imaging loop',self.agent.transcript[-1]['text'])
        prompt=self.client.complete.call_args.args[0]['system']
        self.assertIn('"travel_verified": true',prompt)
        self.assertIn('"completed_supervised": false',prompt)


if __name__=='__main__':unittest.main()
