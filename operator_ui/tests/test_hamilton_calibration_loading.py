"""Observed native calibration loading lifecycle; fake device only."""
import json
import unittest
from itertools import count
from unittest.mock import patch
from test_hamilton_prep import PrepTests,Events
from researcher_teaching import TeachingError


class LoadingTests(unittest.TestCase):
    def setUp(self):
        self.fixture=PrepTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.adapter=self.fixture.adapter;self.device=self.fixture.device
        self.ticket=dict(request_id='loading',action='full_calibration',step='channel_calibration',
            status='running',rack_confirmed=True,calibration_setup=self.adapter.calibration_setup())
        self.original=self.device.__call__
        def request(method,path,body):
            if path in ('calibration/begin-load','calibration/end-load','calibration/begin-cleanup','calibration/end-cleanup'):
                self.device.calls.append((method,path,body));return None
            return self.original(method,path,body)
        request.events=self.device.events;self.adapter.request=request

    def event(self,name,payload,source='Loads'):
        self.device.events.append(('instinctevents',dict(code='generic',data=json.dumps(
            dict(Name=name,Payload=payload,Source=source)))))
        self.adapter.consume(Events(self.adapter),self.ticket)

    def test_native_loading_sequence_and_duplicates(self):
        self.event('ShowDialog','load-id');self.event('ShowDialog','load-id')
        self.event('Status','PrepareLoadingFinished');self.event('Status','PrepareLoadingFinished')
        self.event('Status','LoadingFinished')
        self.assertEqual(self.ticket['calibration_loading'],dict(id='load-id',phase='complete'))
        writes=[p for m,p,_ in self.device.calls if m!='GET']
        self.assertEqual(writes,['calibration/begin-load','calibration/end-load'])
        self.assertIn(('GET','deck/scan/3',None),self.device.calls)
        self.assertNotIn('protocol-run/load-complete',writes)

    def test_no_loading_without_confirmed_rack(self):
        self.ticket['rack_confirmed']=False
        with self.assertRaisesRegex(TeachingError,'confirmed tip-rack'):self.event('ShowDialog','load-id')
        self.assertFalse(any(m!='GET' for m,_,_ in self.device.calls))

    def test_wrong_rack_or_open_door_never_completes_loading(self):
        for wrong_rack in (True,False):
            self.ticket.pop('calibration_loading',None);self.device.calls.clear()
            self.device.rack_site=4 if wrong_rack else 7;self.device.door=wrong_rack
            self.event('ShowDialog','load-id')
            with self.assertRaises(TeachingError):self.event('Status','PrepareLoadingFinished')
            self.assertNotIn('calibration/end-load',[p for m,p,_ in self.device.calls if m!='GET'])

    def test_unowned_or_uncertain_events_never_write(self):
        for key,value in [('step','self_calibration'),('status','uncertain')]:
            previous=self.ticket[key];self.ticket[key]=value
            self.event('ShowDialog','load-id');self.ticket[key]=previous
        self.event('Status','PrepareLoadingFinished')
        self.event('ShowDialog','other',source='Dialogs')
        self.assertFalse(any(m!='GET' for m,_,_ in self.device.calls))

    def test_failed_write_is_not_replayed(self):
        def fail(method,path,body):raise TimeoutError('lost response')
        fail.events=self.device.events;self.adapter.request=fail
        with self.assertRaisesRegex(TeachingError,'no retry'):self.event('ShowDialog','load-id')
        self.assertEqual(self.ticket['status'],'uncertain')
        self.event('ShowDialog','load-id')

    def test_unloading_waits_for_operator_and_reads_parked_once(self):
        self.adapter.active=self.ticket
        with self.adapter.polling_comparison('reduced'):
            self.event('ShowDialog','unload-id',source='Unloads')
            self.event('ShowDialog','unload-id',source='Unloads')
            self.event('Status','UnloadStarted',source='Unloads')
            self.event('Status','UnloadStarted',source='Unloads')
            self.assertEqual(self.adapter.prompt['kind'],'calibration_cleanup')
            self.assertNotIn('calibration/end-cleanup',[p for m,p,_ in self.device.calls if m!='GET'])
            self.device.door=False
            with self.assertRaisesRegex(TeachingError,'Close the Hamilton door'):self.adapter.respond('unload-id','Ok')
            self.device.door=True
            self.event('Status','UnloadFinished',source='Unloads')
            self.assertEqual(self.ticket['calibration_cleanup']['phase'],'awaiting_operator')
            self.adapter.respond('unload-id','Ok')
            # The observed native order is UnloadFinished -> end-cleanup ->
            # CleanupStarted -> CleanupFinished. Earlier or duplicate unload
            # events must never complete the final handshake.
            self.event('Status','UnloadFinished',source='Unloads')
            self.assertEqual(self.ticket['calibration_cleanup']['phase'],'completing')
            self.event('Status','CleanupStarted',source='Unloads')
            self.event('Status','CleanupFinished',source='Unloads')
            self.event('Status','CleanupFinished',source='Unloads')
            self.assertEqual(self.ticket['calibration_cleanup']['phase'],'complete')
            self.assertIsNone(self.adapter.prompt)
            with self.assertRaisesRegex(TeachingError,'no longer active'):self.adapter.respond('unload-id','Ok')
        self.assertEqual([p for m,p,_ in self.device.calls if m!='GET'],
            ['calibration/begin-cleanup','calibration/end-cleanup'])
        self.assertEqual(sum(p=='service-software-api/is-parked' for _,p,_ in self.device.calls),1)

    def test_cleanup_completion_requires_owned_stage_source_and_operator_response(self):
        self.ticket['calibration_cleanup']=dict(id='unload-id',phase='awaiting_operator')
        self.event('Status','CleanupFinished',source='Unloads')
        self.assertEqual(self.ticket['calibration_cleanup']['phase'],'awaiting_operator')
        self.ticket['calibration_cleanup']['phase']='completing'
        for key,value in [('step','self_calibration'),('status','uncertain')]:
            previous=self.ticket[key];self.ticket[key]=value
            self.event('Status','CleanupFinished',source='Unloads');self.ticket[key]=previous
            self.assertEqual(self.ticket['calibration_cleanup']['phase'],'completing')
        self.event('Status','CleanupFinished',source='Loads')
        self.assertEqual(self.ticket['calibration_cleanup']['phase'],'completing')
        self.assertFalse(any(m!='GET' for m,_,_ in self.device.calls))

    def test_recorded_cleanup_order_releases_monitor_even_when_result_missing(self):
        # Exercise the whole worker, including the missing-result deadline that
        # was previously unreachable because cleanup remained 'completing'.
        config=json.loads(self.adapter.config.read_text());config['timeout_s']=10000
        self.adapter.config.write_text(json.dumps(config))
        self.device.emit_channel_result=False
        old=self.adapter.request
        def native(name,payload):
            return ('instinctevents',dict(code='generic',data=json.dumps(
                dict(Name=name,Payload=payload,Source='Unloads'))))
        def request(method,path,body):
            result=old(method,path,body)
            if path=='calibration/channel-height-squeeze':
                self.device.events.extend([native('ShowDialog','cleanup-id'),
                    native('Status','UnloadStarted'),native('Status','UnloadFinished')])
            if path=='calibration/end-cleanup':
                self.device.events.extend([native('Status','CleanupStarted'),
                    native('Status','CleanupFinished'),('instinctevents',dict(code='finished'))])
            return result
        request.events=self.device.events;self.adapter.request=request
        with patch('hamilton_prep.time.monotonic',side_effect=count()):
            with self.assertRaisesRegex(TeachingError,'did not publish'):
                self.adapter.run_action('channel_calibration',progress=self.fixture.operator_answers)
        self.assertEqual(self.adapter.active['calibration_cleanup']['phase'],'complete')
        self.assertEqual(self.adapter.active['status'],'finished_unverified')
        writes=[p for m,p,_ in self.device.calls if m!='GET']
        self.assertEqual(writes,['calibration/channel-height-squeeze',
            'calibration/begin-cleanup','calibration/end-cleanup'])
        self.assertTrue((self.adapter.folder/'active.json').exists())

    def test_unloading_waits_until_parked_without_abort_or_repeated_writes(self):
        old=self.adapter.request
        readiness={'parked':False,'tips':True}
        def request(method,path,body):
            if path=='service-software-api/is-parked':return readiness['parked']
            if path=='service-software-api/has-tips':return readiness['tips']
            return old(method,path,body)
        request.events=self.device.events;self.adapter.request=request
        self.event('ShowDialog','unload-id',source='Unloads')
        self.event('Status','UnloadStarted',source='Unloads')
        self.event('Status','UnloadStarted',source='Unloads')
        for _ in range(3):self.adapter.consume(Events(self.adapter),self.ticket)
        self.assertEqual(self.ticket['calibration_cleanup']['phase'],'waiting_for_parking')
        self.assertIsNone(self.adapter.prompt)
        readiness['parked']=True
        self.adapter.consume(Events(self.adapter),self.ticket)
        self.assertIsNone(self.adapter.prompt)  # Attached tips still prevent access.
        readiness['tips']=False
        self.adapter.consume(Events(self.adapter),self.ticket)
        self.assertEqual(self.adapter.prompt['kind'],'calibration_cleanup')
        self.assertEqual(self.ticket['calibration_cleanup']['phase'],'awaiting_operator')
        self.assertEqual([p for m,p,_ in self.device.calls if m!='GET'],['calibration/begin-cleanup'])

    def test_native_fault_remains_visible_while_waiting_for_parking(self):
        self.ticket['calibration_cleanup']=dict(id='unload-id',phase='waiting_for_parking')
        self.device.events.append(('instincterrors',dict(id='fault',message='Motor fault',handled=False)))
        with self.assertRaisesRegex(TeachingError,'Motor fault'):
            self.adapter.consume(Events(self.adapter),self.ticket)
        self.assertIsNone(self.adapter.prompt)

    def test_finished_without_result_stops_monitor_without_redundant_abort(self):
        config=json.loads(self.adapter.config.read_text());config['timeout_s']=10000
        self.adapter.config.write_text(json.dumps(config))
        self.device.emit_channel_result=False
        old=self.adapter.request
        def request(method,path,body):
            result=old(method,path,body)
            if path=='calibration/channel-height-squeeze':
                self.device.events.append(('instinctevents',dict(code='finished')))
            return result
        request.events=self.device.events;self.adapter.request=request
        with patch('hamilton_prep.time.monotonic',side_effect=count()):
            with self.assertRaisesRegex(TeachingError,'did not publish'):
                self.adapter.run_action('channel_calibration')
        self.assertEqual(self.adapter.active['status'],'finished_unverified')
        self.assertNotIn('calibration/abort',[p for _,p,_ in self.device.calls])
        self.assertTrue((self.adapter.folder/'active.json').exists())
        self.assertIsNone(self.adapter.polling_trial)


if __name__=='__main__':unittest.main()
