"""Counted plans and hardware boundary: no robot or instrument connections."""
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiment_plan import build_experiment, PHASES
from lacry_agent import LacryAgent, TOOLS
from researcher_teaching import TeachingError
from sequences import Runner


class ExperimentTests(unittest.TestCase):
    def test_eight_and_ten_cycles_have_ordered_wait_and_delivery_barriers(self):
        for count in (8,10):
            plan=build_experiment('hamilton_to_squid',count)
            self.assertEqual(len(plan['steps']),count*len(PHASES))
            self.assertEqual(sorted(set(s['cycle'] for s in plan['steps'])),list(range(1,count+1)))
            for cycle in range(1,count+1):
                phases=[s['phase'] for s in plan['steps'] if s['cycle']==cycle]
                self.assertEqual(phases,[p[0] for p in PHASES])
                self.assertLess(phases.index('home_before_dispense'),phases.index('start_dispense'))
                self.assertLess(phases.index('wait_dispense'),phases.index('pickup'))
                self.assertLess(phases.index('verify_delivery'),phases.index('return_home'))
            self.assertFalse(plan['executable'])
            self.assertTrue(plan['completion_policy']['job_id_match_required'])
            self.assertFalse(plan['completion_policy']['automatic_retry'])

    def test_bad_counts_and_unknown_experiment_rejected(self):
        for count in (True,0,-1,1.5,'8',None,101):
            with self.assertRaises(TeachingError):build_experiment('hamilton_to_squid',count)
        with self.assertRaises(TeachingError):build_experiment('guess',8)

    def test_tool_preserves_count_and_confirmation_cannot_execute_preview(self):
        backend=Mock();run=Runner();prepare=Mock()
        agent=LacryAgent(backend,Mock(),lambda:run,client=Mock(),prepare=prepare)
        result,error=agent._run_tool('plan_experiment',dict(recipe='hamilton_to_squid',repetitions=8))
        result=json.loads(result)
        self.assertFalse(error);self.assertEqual(result['repetitions'],8)
        self.assertTrue(result['preview_only']);self.assertFalse(result['executable'])
        view=agent._plan_view(agent.pending)
        self.assertFalse(view['executable']);self.assertTrue(view['blockers'])
        with self.assertRaisesRegex(TeachingError,'preview only'):
            agent.confirm(dict(ready=True,plan_id=agent.pending['id']))
        self.assertFalse(run.active);self.assertEqual(backend.mock_calls,[])
        prepare.assert_not_called()

    def test_model_has_typed_count_tool(self):
        schema=next(t for t in TOOLS if t['name']=='plan_experiment')['input_schema']
        self.assertEqual(schema['properties']['repetitions']['type'],'integer')
        self.assertIn('repetitions',schema['required'])


if __name__=='__main__':unittest.main()
