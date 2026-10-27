"""Current-run native completion is distinct from historical numeric reports."""
from copy import deepcopy
from itertools import count
import json
import unittest
from unittest.mock import patch

import test_hamilton_calibration_loading as loading_fixture
from hamilton_prep import HamiltonPrep
from researcher_teaching import TeachingError


class ChannelCompletionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=loading_fixture.LoadingTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.adapter=self.fixture.adapter;self.device=self.fixture.device

    def install_native_run(self, new_result=False, fault=False, activity=True):
        config=json.loads(self.adapter.config.read_text());config['timeout_s']=10000
        self.adapter.config.write_text(json.dumps(config))
        self.device.emit_channel_result=new_result
        self.device.selection_required=True
        old=self.adapter.request
        def native(source,name,payload):
            return ('instinctevents',dict(code='generic',data=json.dumps(
                dict(Name=name,Payload=payload,Source=source))))
        def request(method,path,body):
            result=old(method,path,body)
            if path=='calibration/close-labware-view':
                self.device.events.extend([native('Loads','ShowDialog','load-id'),
                    native('Loads','Status','PrepareLoadingFinished'),native('Loads','Status','LoadingFinished')])
                if activity:
                    self.device.events.extend([
                        native('Xsl','ActivityStarted',json.dumps(dict(ActivityID='28',ActivityViewName='Calibrate'))),
                        native('Xsl','ActivityEnded',json.dumps(dict(ActivityID='28')))])
                self.device.events.extend([native('Unloads','ShowDialog','cleanup-id'),
                    native('Unloads','Status','UnloadStarted'),native('Unloads','Status','UnloadFinished')])
            if path=='calibration/end-cleanup':
                self.device.events.extend([native('Unloads','Status','CleanupStarted'),
                    native('Unloads','Status','CleanupFinished'),('instinctevents',dict(code='finished'))])
                if fault:self.device.events.append(('instincterrors',dict(id='new-fault',message='Motor fault',handled=False)))
            return result
        request.events=self.device.events;self.adapter.request=request

    def run_action(self):
        with patch('hamilton_prep.time.monotonic',side_effect=count()):
            return self.adapter.run_action('full_calibration',progress=self.fixture.fixture.operator_answers)

    def test_full_run_completes_with_native_evidence_without_inventing_history(self):
        self.install_native_run()
        before=deepcopy(self.device.channel_results)
        result=self.run_action()
        self.assertTrue(result['ok'])
        self.assertEqual(result['completed_steps'],['self_calibration','channel_calibration'])
        self.assertIsNone(result['channel_result'])
        self.assertFalse(result['channel_completion']['numerical_result_verified'])
        self.assertEqual(self.device.channel_results,before)
        self.assertFalse((self.adapter.folder/'active.json').exists())
        self.assertNotIn('calibration/abort',[p for _,p,_ in self.device.calls])
        self.assertNotIn(('POST','calibration/channel-results'),[(m,p) for m,p,_ in self.device.calls])

    def test_actual_fresh_failure_cannot_be_replaced_by_lifecycle(self):
        self.install_native_run(new_result=True)
        self.device.channel_outcome='Fail'
        with self.assertRaisesRegex(TeachingError,'did not pass'):self.run_action()

    def test_native_fault_cannot_be_replaced_by_lifecycle(self):
        self.install_native_run(fault=True)
        with self.assertRaisesRegex(TeachingError,'Motor fault'):self.run_action()

    def test_idle_and_cleanup_alone_are_not_enough(self):
        self.install_native_run(activity=False)
        with self.assertRaisesRegex(TeachingError,'did not publish'):self.run_action()

    def test_activity_requires_matching_identity(self):
        ticket=dict(status='running',step='channel_calibration')
        HamiltonPrep.track_channel_activity(ticket,dict(Source='Xsl',Name='ActivityStarted',
            Payload=json.dumps(dict(ActivityID='28',ActivityViewName='Calibrate'))))
        HamiltonPrep.track_channel_activity(ticket,dict(Source='Xsl',Name='ActivityEnded',Payload='{"ActivityID":"29"}'))
        self.assertFalse(ticket['channel_activity']['ended'])
        HamiltonPrep.track_channel_activity(ticket,dict(Source='Xsl',Name='ActivityEnded',Payload='{"ActivityID":"28"}'))
        self.assertTrue(ticket['channel_activity']['ended'])

    def test_each_completion_condition_is_required(self):
        ticket=dict(status='running',step='channel_calibration',rack_confirmed=True,
            calibration_loading={'phase':'complete'},calibration_cleanup={'phase':'complete'},
            channel_activity={'ended':True},channel_finished_after_cleanup=True)
        state=dict(connected=True,initialized=True,global_state='Idle',
            run={'isRunInProgress':False},pending_errors=[])
        self.assertTrue(HamiltonPrep.channel_lifecycle_completed(ticket,state,None))
        for key in ticket:
            altered=deepcopy(ticket);altered.pop(key)
            self.assertFalse(HamiltonPrep.channel_lifecycle_completed(altered,state,None),key)
        for key in state:
            altered=deepcopy(state);altered.pop(key)
            self.assertFalse(HamiltonPrep.channel_lifecycle_completed(ticket,altered,None),key)
        self.assertFalse(HamiltonPrep.channel_lifecycle_completed(ticket,state,{'id':'unanswered'}))


if __name__=='__main__':unittest.main()
