"""GUI-started scans: exact-job stage return + actual robot plans, fake hardware."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_squid_stage as stage_fixture
import test_squid_handling as travel_fixture
from squid_retrieval import SquidRetrieval
from researcher_teaching import TeachingError


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.f=stage_fixture.StageTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.agent=self.f.agent;self.run=self.f.runner
        ref=self.f.engine.saved();ref['accepted_for_robot_loading']=True
        self.f.engine.reference.write_text(json.dumps(ref))
        self.f.scanning();self.f.state.update(status='completed',completion_confirmed=True)
        self.robot_calls=[]
        self.plan=dict(actions=['squid_retrieve'],steps=[dict(kind='travel',label='Retrieve the plate to Home')])
        self.agent.automatic_workflow=Mock(return_value=Mock(projected_handling=Mock(return_value=self.plan)))
        self.f.backend.execute_step.side_effect=lambda r,s,p:self.robot_calls.append(s['label']) or dict(ok=True)
        self.engine=SquidRetrieval(self.agent,self.f.engine,self.f.root/'retrieval')
        self.agent.retrieval=self.engine
    def finish(self,plan):
        self.agent.confirm(dict(ready=True,plan_id=plan['id']))
        self.engine.thread.join(5);self.assertFalse(self.engine.active)
        return self.agent.run_state
    def test_already_completed_scan_returns_stage_then_retrieves_once(self):
        plan=self.engine.propose()
        self.assertFalse(self.robot_calls)
        self.assertFalse(any(n=='return_to_recorded_dropoff' for n,p in self.f.calls))
        self.assertTrue(self.finish(plan)['ok'])
        self.assertEqual(self.f.pose,self.f.target)
        self.assertEqual(self.robot_calls,['Retrieve the plate to Home'])
        self.assertFalse(any(n=='home' for n,p in self.f.calls))
        events=[fields for name,fields in self.f.audit_events if name=='squid_stage_scan_completed']
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['squid_run_id'],'scan1')
        self.assertEqual(events[0]['squid_experiment_id'],'exp1')
        self.assertNotEqual(events[0]['run_id'],events[0]['squid_run_id'])
        with self.assertRaises(TeachingError):self.engine.propose()

    def test_stage_completion_does_not_claim_entire_retrieval_is_complete(self):
        def pickup(r,s,p):
            self.assertTrue(self.agent.run_state['active'])
            self.assertIsNone(self.agent.run_state['ok'])
            self.assertFalse(any(m['text']=='Squid is at its saved drop-off location.' for m in self.agent.transcript))
            return dict(ok=True)
        self.f.backend.execute_step.side_effect=pickup
        self.assertTrue(self.finish(self.engine.propose())['ok'])
        self.assertEqual(self.agent.transcript[-1]['text'],'Plate retrieved from Squid and returned Home.')
    def test_running_scan_waits_under_one_confirmation(self):
        self.f.state.update(status='running',completion_confirmed=False)
        entered,release=threading.Event(),threading.Event()
        def wait(_):
            if self.f.state['status']=='running':
                entered.set();self.assertTrue(release.wait(3))
                self.f.state.update(status='completed',completion_confirmed=True)
        self.f.engine.sleep=wait
        plan=self.engine.propose();self.agent.confirm(dict(ready=True,plan_id=plan['id']))
        self.assertTrue(entered.wait(3));self.assertFalse(self.robot_calls)
        self.assertFalse(any(n=='return_to_recorded_dropoff' for n,p in self.f.calls))
        self.assertFalse(self.run.start('intruder',lambda r:dict(ok=True))['ok'])
        release.set();self.engine.thread.join(5)
        self.assertTrue(self.agent.run_state['ok'],self.agent.run_state)
    def test_failed_scan_during_wait_never_moves_stage_or_robot(self):
        self.f.state.update(status='running',completion_confirmed=False)
        self.f.engine.sleep=lambda _:self.f.state.update(status='failed')
        self.assertFalse(self.finish(self.engine.propose())['ok'])
        self.assertFalse(self.robot_calls)
        self.assertFalse(any(n=='return_to_recorded_dropoff' for n,p in self.f.calls))
    def test_stop_during_wait_never_moves_or_aborts_external_imaging(self):
        self.f.state.update(status='running',completion_confirmed=False)
        self.f.engine.sleep=lambda _:self.agent.stop()
        self.assertFalse(self.finish(self.engine.propose())['ok'])
        self.assertFalse(self.robot_calls)
        self.assertFalse(any(n not in ('get_position','get_stage_reference') for n,p in self.f.calls))
    def test_changed_job_rejected_before_motion(self):
        plan=self.engine.propose();self.f.state['job']['run_id']='other'
        with self.assertRaises(TeachingError):self.engine.start(plan)
        self.assertFalse(self.robot_calls)
    def test_stage_return_failure_blocks_robot(self):
        original=self.f.engine.command
        def command(name,params):
            if name=='return_to_recorded_dropoff':return dict(at_dropoff=False)
            return original(name,params)
        self.f.engine.command=command
        self.assertFalse(self.finish(self.engine.propose())['ok'])
        self.assertFalse(self.robot_calls)
    def test_unsolicited_suggestion_never_replaces_pending_plan(self):
        self.agent.pending={'id':'other'}
        self.assertIsNone(self.engine.propose(only_if_idle=True))
        self.assertEqual(self.agent.pending['id'],'other')
    def test_completion_notification_offers_plan_but_never_starts_it(self):
        self.agent.run_meta=dict(name='Leave plate at Squid')
        self.agent.run_state.update(active=False,ok=True)
        ready=threading.Event();original=self.engine.propose
        def propose(**kw):
            try:return original(**kw)
            finally:ready.set()
        self.engine.propose=propose
        event=dict(self.f.state,message='Imaging complete')
        self.agent._squid_event(event)
        self.assertTrue(ready.wait(3))
        self.assertEqual(self.agent.pending['dispatch'],'squid_retrieval')
        self.assertFalse(self.robot_calls);self.assertFalse(self.run.active)
    def test_real_robot_planner_and_lua_after_stage_return(self):
        f=travel_fixture.SquidHandlingTests();f.setUp();self.addCleanup(f.doCleanups)
        f.e1=5.;f.backend.run=self.run
        self.agent.backend=f.backend;self.engine.backend=f.backend
        # Stage now reads the real fixture's Home/robot health.
        del self.agent.automatic_workflow
        self.assertTrue(self.finish(self.engine.propose())['ok'],self.agent.run_state)
        self.assertEqual(f.s.grips,[3.7])
        for axis in ('X','Y','Z','Rz'):self.assertAlmostEqual(f.s.pose[axis],f.path[0][axis],delta=.02)


if __name__=='__main__':unittest.main()
