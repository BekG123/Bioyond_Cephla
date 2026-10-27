"""Polling experiment isolation and fault preservation, with no hardware traffic."""
import json
import sys
import threading
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_hamilton_prep import PrepTests
from researcher_teaching import TeachingError


class PollingComparisonTests(unittest.TestCase):
    def setUp(self):
        self.fixture=PrepTests('test_decoding_nested_json');self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.adapter=self.fixture.adapter;self.device=self.fixture.device
        self.adapter.status(fresh=True)

    def test_reduced_run_keeps_native_commands_and_restores_polling(self):
        self.device.calls.clear()
        with self.adapter.polling_comparison('reduced') as trial:
            result=self.adapter.run_action('self_calibration',progress=self.fixture.operator_answers)
        self.assertTrue(result['ok'])
        paths=[p for _,p,_ in self.device.calls]
        self.assertNotIn('protocols',paths)
        self.assertNotIn('service-software-api/is-parked',paths)
        self.assertIn('errors?offset=0&limit=30',paths)
        self.assertIn('service-software-api/sensor-status',paths)
        self.assertEqual([p for m,p,_ in self.device.calls if m!='GET'],['calibration/self-calibration','calibration/close-view'])
        rows=[json.loads(s) for s in (trial['folder']/'requests.jsonl').read_text().splitlines()]
        self.assertEqual(sum(r['kind']=='send' for r in rows),len(self.device.calls))
        self.assertEqual(sum(r['kind']=='response' for r in rows),len(self.device.calls))
        self.assertIsNone(self.adapter.polling_trial)
        self.adapter.status(fresh=True)
        self.assertIn('service-software-api/is-parked',[p for _,p,_ in self.device.calls])

    def test_background_detail_is_cached_and_camera_not_sent(self):
        with self.adapter.polling_comparison('reduced') as trial:
            before=len(self.device.calls);results=[]
            thread=threading.Thread(target=lambda:results.append(self.adapter.detail()))
            thread.start();thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(self.device.calls),before)
            self.assertTrue(results[0]['background_polling_suspended'])
            self.assertFalse(results[0]['ready_for_robot'])
            with self.assertRaisesRegex(TeachingError,'paused'):
                self.adapter.call('GET','camera/true',binary=True)
            self.assertEqual(len(self.device.calls),before)

    def test_normal_comparator_preserves_queries(self):
        with self.adapter.polling_comparison('normal'):
            self.device.calls.clear();self.adapter.status(fresh=True)
            self.assertIn('service-software-api/is-parked',[p for _,p,_ in self.device.calls])
            self.assertIn('protocols',[p for _,p,_ in self.device.calls])

    def test_closed_door_check_cannot_be_skipped_in_either_test(self):
        self.device.door=False
        for mode in ('normal','reduced'):
            with self.adapter.polling_comparison(mode):
                with self.assertRaisesRegex(TeachingError,'Close the Hamilton door'):
                    self.adapter.run_action('self_calibration')
            self.assertIsNone(self.adapter.polling_trial)
        self.assertTrue(all(m=='GET' for m,_,_ in self.device.calls))

    def test_native_fault_still_aborts_once_and_is_recorded(self):
        self.device.self_success=False
        original=self.device.__call__
        def request(method,path,body):
            result=original(method,path,body)
            if path=='calibration/self-calibration':
                self.device.errors.append(dict(id='new',message='The calibration tool was not detected.'))
            return result
        self.adapter.request=request
        # Events fake accesses request.events, just as the ordinary fake Device does.
        request.events=self.device.events
        with self.adapter.polling_comparison('reduced'):
            with self.assertRaisesRegex(TeachingError,'calibration tool was not detected'):
                self.adapter.run_action('self_calibration')
        writes=[p for m,p,_ in self.device.calls if m!='GET']
        self.assertEqual(writes,['calibration/self-calibration','calibration/abort'])
        self.assertEqual(self.adapter.active['status'],'aborted')

    def test_actual_native_finish_dialog_completes_after_acknowledgment(self):
        original=self.device.__call__
        def request(method,path,body):
            result=original(method,path,body)
            if path=='calibration/self-calibration':
                self.device.events[-1][1]['data']['textSections']=[['Calibration is complete.',None,None],[None,None,None]]
            return result
        request.events=self.device.events;self.adapter.request=request
        with self.adapter.polling_comparison('reduced'):
            result=self.adapter.run_action('self_calibration',progress=self.fixture.operator_answers)
        self.assertTrue(result['ok'])
        self.assertEqual(result['completed_steps'],['self_calibration'])
        self.assertEqual([p for m,p,_ in self.device.calls if m!='GET'],['calibration/self-calibration','calibration/close-view'])

    def test_default_full_calibration_reduces_polling_and_keeps_channel_checks(self):
        self.device.selection_required=True
        modes=[]
        def progress(state):
            modes.append(self.adapter.polling_status())
            self.fixture.operator_answers(state)
        self.device.calls.clear()
        result=self.adapter.run_action('full_calibration',progress=progress)
        self.assertEqual(result['completed_steps'],['self_calibration','channel_calibration'])
        self.assertTrue(modes)
        self.assertTrue(all(m['mode']=='reduced' and m['purpose']=='calibration' for m in modes))
        paths=[p for _,p,_ in self.device.calls]
        self.assertNotIn('service-software-api/is-parked',paths)
        self.assertNotIn('protocols',paths)
        self.assertIn('calibration/channel-results',paths)
        self.assertIn('deck/scan/3',paths)
        self.assertIn('calibration/close-labware-view',paths)
        self.assertEqual(self.adapter.polling_status()['mode'],'normal')

    def test_default_channel_failure_restores_polling_and_does_not_succeed(self):
        self.device.channel_outcome='Fail'
        with self.assertRaisesRegex(TeachingError,'did not pass'):
            self.adapter.run_action('channel_calibration')
        self.assertIsNone(self.adapter.polling_trial)
        self.assertNotEqual(self.adapter.active['status'],'completed')

    def test_background_channel_results_cannot_poll_worker_results(self):
        errors=[]
        with self.adapter.polling_comparison('reduced'):
            def read():
                try:self.adapter.call('GET','calibration/channel-results')
                except TeachingError as error:errors.append(str(error))
            before=len(self.device.calls)
            thread=threading.Thread(target=read);thread.start();thread.join(2)
            self.assertEqual(len(self.device.calls),before)
            self.assertEqual(len(errors),1)
            self.assertTrue(self.adapter.call('GET','calibration/channel-results'))

    def test_incomplete_or_failed_dialog_is_not_success(self):
        from test_hamilton_prep import Events
        for message,spinner,button in [('Calibration is not complete.',False,'Finish'),
                ('Calibration is complete. Error detected.',False,'Finish'),
                ('Calibration is complete.',True,'Finish'),('Calibration is complete.',False,'Next')]:
            ticket=dict(request_id='negative',action='self_calibration')
            self.device.events.append(('instinctevents',dict(code='calibrationdata',data=dict(
                id='dialog',textSections=[[message]],spinnerShown=spinner,buttonText=button))))
            self.adapter.consume(Events(self.adapter),ticket)
            self.assertFalse(ticket.get('stage_success_display',False),message)


if __name__=='__main__':unittest.main()
