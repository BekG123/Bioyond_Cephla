"""Touchscreen mirror tests: fake device only, no instrument or arm traffic."""
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hamilton_touchscreen import TouchscreenRecorder,read_snapshot
from researcher_teaching import TeachingError
import test_hamilton_prep as fixtures


class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.PrepTests('test_decoding_nested_json');self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.adapter=self.fixture.adapter;self.device=self.fixture.device
        self.root=self.fixture.root/'mirror';self.adapter.touchscreen_root=self.root
        self.rec=TouchscreenRecorder(self.adapter,self.root)
        self.rec.state['connected']=True

    def prompt(self,kind=None,identifier='native'):
        self.rec.event('instinctevents',dict(code='calibrationdata',data=dict(id=identifier,
            inputType=kind,spinnerShown=False,buttonText='Next',textSections=[['Clear the deck.']])) )
        self.rec.publish()
        return self.adapter.touchscreen_status()['prompt']

    def answer(self,prompt,**kwargs):
        return self.adapter.respond_touchscreen(prompt['id'],'Ok',self.rec.session,prompt['token'],**kwargs)

    def test_passive_prompt_and_trace_logging_never_writes_to_device(self):
        prompt=self.prompt()
        self.assertEqual(prompt['text'],'Clear the deck.')
        self.assertEqual(prompt['data']['buttonText'],'Next')
        self.assertFalse(self.device.calls)
        log=(self.rec.folder/'recording.jsonl').read_text()
        self.assertIn('calibrationdata',log)

    def test_windows_snapshot_lock_does_not_stop_recording(self):
        with patch.object(Path,'replace',side_effect=PermissionError('reader holds file')):
            self.assertFalse(self.rec.publish())
        self.assertTrue(self.rec.state['recording'])
        self.assertTrue(self.rec.publish())
        self.assertTrue(read_snapshot(self.root)['fresh'])
        self.assertFalse(self.device.calls)

    def test_one_operator_answer_only_acknowledges_native_view(self):
        prompt=self.prompt()
        self.assertTrue(self.answer(prompt)['ok'])
        self.assertEqual([p for m,p,_ in self.device.calls if m!='GET'],['calibration/close-view'])
        self.assertIsNone(self.adapter.touchscreen_status()['prompt'])
        with self.assertRaises(TeachingError):self.answer(prompt)
        self.assertEqual(sum(m=='POST' for m,_,_ in self.device.calls),1)

    def test_touchscreen_advancing_invalidates_previous_answer(self):
        old=self.prompt()
        self.rec.event('instinctevents',dict(code='calibrationdata',data=dict(id='calibration',spinnerShown=True)))
        self.rec.publish()
        with self.assertRaises(TeachingError):self.answer(old)
        self.assertFalse(self.device.calls)

    def test_stale_or_lost_observer_never_sends_answer(self):
        prompt=self.prompt()
        with patch('hamilton_touchscreen.time.time',return_value=time.time()+9):
            with self.assertRaises(TeachingError):self.answer(prompt)
        self.rec.event('connection_lost','disconnected');self.rec.publish()
        with self.assertRaises(TeachingError):self.answer(prompt)
        self.assertFalse(self.device.calls)

    def test_error_event_removes_instruction_without_abort(self):
        prompt=self.prompt()
        self.rec.event('instincterrors',dict(message='tool not detected'));self.rec.publish()
        with self.assertRaises(TeachingError):self.answer(prompt)
        self.assertFalse(self.device.calls)

    def test_changed_token_even_with_same_native_id_rejects_old_answer(self):
        old=self.prompt();new=self.prompt()
        self.assertNotEqual(old['token'],new['token'])
        with self.assertRaises(TeachingError):self.answer(old)
        self.assertTrue(self.answer(new)['ok'])

    def test_lacry_owned_instruction_cannot_be_answered_as_touchscreen(self):
        self.adapter.folder.mkdir(parents=True)
        (self.adapter.folder/'active.json').write_text(json.dumps(dict(request_id='owned')))
        prompt=self.prompt()
        self.assertEqual(prompt['owner_request'],'owned')
        with self.assertRaises(TeachingError):self.answer(prompt)
        self.assertFalse(self.device.calls)

    def test_active_host_operation_excludes_relay(self):
        prompt=self.prompt();self.adapter.operation_lock.acquire()
        try:
            with self.assertRaises(TeachingError):self.answer(prompt)
        finally:self.adapter.operation_lock.release()
        self.assertFalse(self.device.calls)

    def test_native_rack_prompt_requires_explicit_site_and_verified_rack(self):
        prompt=self.prompt('tiprack')
        with self.assertRaisesRegex(TeachingError,'Select the site'):self.answer(prompt)
        self.device.rack_site=4
        with self.assertRaisesRegex(TeachingError,'camera'):self.answer(prompt,tip_site=7)
        self.assertFalse(any(m!='GET' for m,_,_ in self.device.calls))
        self.assertTrue(self.answer(prompt,tip_site=4)['ok'])
        self.assertIn(('POST','calibration/close-labware-view',dict(viewId='native',viewResult='Ok',labwareId='273',labwarePosition=4)),self.device.calls)

    def test_unknown_selection_keeps_touchscreen_in_control(self):
        prompt=self.prompt('unknown')
        with self.assertRaisesRegex(TeachingError,'touchscreen'):self.answer(prompt)
        self.assertFalse(any(m!='GET' for m,_,_ in self.device.calls))

    def test_lost_ack_is_consumed_without_retry_abort_or_fault_reset(self):
        prompt=self.prompt();original=self.adapter.request
        def lost(method,path,body):
            result=original(method,path,body)
            if method=='POST':raise TimeoutError('lost response')
            return result
        self.adapter.request=lost
        with self.assertRaisesRegex(TeachingError,'uncertain'):self.answer(prompt)
        with self.assertRaises(TeachingError):self.answer(prompt)
        self.assertEqual([p for m,p,_ in self.device.calls if m!='GET'],['calibration/close-view'])

    def test_new_prompt_during_validation_is_not_acknowledged(self):
        prompt=self.prompt();original=self.adapter.request
        def changed(method,path,body):
            if path=='instruments/global-run-state':self.prompt(identifier='new')
            return original(method,path,body)
        self.adapter.request=changed
        with self.assertRaisesRegex(TeachingError,'changed'):self.answer(prompt)
        self.assertFalse(any(m!='GET' for m,_,_ in self.device.calls))

    def test_observer_run_uses_only_gets_and_does_not_acknowledge_events(self):
        original=self.adapter.request
        def fake(method,path,body):
            if path.startswith('traces?'):return dict(items=[dict(id='trace',message='MoveAbsolute')])
            return original(method,path,body)
        self.adapter.request=fake
        self.device.events=[('instinctevents',dict(code='calibrationdata',data=dict(id='native',spinnerShown=False,textSections=[['Next']])))]
        fake.events=self.device.events
        with patch('hamilton_prep.PrepEvents',fixtures.Events):self.rec.run(seconds=.3)
        self.assertTrue(all(m=='GET' for m,_,_ in self.device.calls))
        self.assertEqual(self.rec.state['trace_count'],1)
        self.assertFalse(read_snapshot(self.root)['fresh'])
        self.assertIn('MoveAbsolute',(self.rec.folder/'recording.jsonl').read_text())


if __name__=='__main__':unittest.main()
