"""Parking control tests; all instrument connections are fake."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import test_hamilton_prep as fixture
from hamilton_park import run,preflight,native_park
from researcher_teaching import TeachingError


class ParkTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.PrepTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.h=self.fixture.adapter;self.d=self.fixture.device
        self.parked=False;self.tips=False;self.verification={}
        original=self.h.request
        def request(method,path,body):
            if path=='service-software-api/is-parked':return self.parked
            if path=='service-software-api/has-tips':return self.tips
            if path=='verification/status':return self.verification
            return original(method,path,body)
        request.events=self.d.events;self.h.request=request
        self.sent=[]

    async def sender(self,adapter,ticket,stopped,baseline):
        ticket['write_attempted']=True;self.sent.append('PrepPark');self.parked=True

    def test_one_park_and_feedback_no_initialize_or_fault_clear(self):
        result=run(self.h,lambda:False,Mock(),sender=self.sender)
        self.assertTrue(result['parked']);self.assertEqual(self.sent,['PrepPark'])
        self.assertTrue(all(m=='GET' for m,_,_ in self.d.calls))
        self.assertFalse((self.h.folder/'active.json').exists())

    def test_already_parked_does_not_send_motion(self):
        self.parked=True
        result=run(self.h,lambda:False,Mock(),sender=self.sender)
        self.assertTrue(result['already_parked']);self.assertEqual(self.sent,[])

    def test_uninitialized_state_does_not_block_native_park(self):
        self.d.info=[v.replace('Initialization Status: Initialized',
            'Initialization Status: Not Initialized') for v in self.d.info]
        self.assertFalse(preflight(self.h)['initialized'])
        result=run(self.h,lambda:False,Mock(),sender=self.sender)
        self.assertTrue(result['parked']);self.assertEqual(self.sent,['PrepPark'])
        self.assertTrue(all(m=='GET' for m,_,_ in self.d.calls))

    def test_native_rejection_does_not_initialize_or_retry(self):
        self.d.info=[v.replace('Initialization Status: Initialized',
            'Initialization Status: Not Initialized') for v in self.d.info]
        async def reject(adapter,ticket,stopped,baseline):
            ticket['write_attempted']=True;self.sent.append('PrepPark')
            raise TeachingError('Native controller rejected parking.')
        with self.assertRaisesRegex(TeachingError,'Native controller rejected'):
            run(self.h,lambda:False,Mock(),sender=reject)
        self.assertEqual(self.sent,['PrepPark'])
        self.assertTrue(all(m=='GET' for m,_,_ in self.d.calls))
        self.assertTrue((self.h.folder/'active.json').exists())

    def test_stop_before_start_sends_nothing(self):
        with self.assertRaisesRegex(TeachingError,'cancelled'):run(self.h,lambda:True,Mock(),sender=self.sender)
        self.assertEqual(self.sent,[])

    def test_abort_uses_native_worker_not_rest_protocol_abort(self):
        self.h.active=dict(action='park',status='running')
        self.assertTrue(self.h.abort_owned()['ok'])
        self.assertTrue(self.h.active['park_stop_requested'])
        self.assertEqual(self.d.calls,[])

    def test_unknown_arrival_retains_ownership_without_retry(self):
        async def no_arrival(adapter,ticket,stopped,baseline):
            ticket['write_attempted']=True;self.sent.append('PrepPark')
        with self.assertRaisesRegex(TeachingError,'not confirmed'):run(self.h,lambda:False,Mock(),sender=no_arrival)
        self.assertEqual(self.sent,['PrepPark']);self.assertTrue((self.h.folder/'active.json').exists())

    def test_interlocks_and_active_service_block(self):
        self.d.door=False
        with self.assertRaisesRegex(TeachingError,'door'):preflight(self.h)
        self.d.door=True;self.tips=True
        with self.assertRaisesRegex(TeachingError,'tips or tools'):preflight(self.h)
        self.tips=False;self.verification={'isWorkflowInProgress':True}
        with self.assertRaisesRegex(TeachingError,'service routine'):preflight(self.h)
        self.assertEqual(self.sent,[])

    def test_native_transport_opens_without_high_level_setup_and_sends_only_park(self):
        calls=[]
        class Park:pass
        class Abort:pass
        class Driver:
            def __init__(self,**kwargs):pass
            async def _open(self):calls.append('open')
            async def _close(self):calls.append('close')
            async def send_command(self,command,**kwargs):calls.append(type(command).__name__)
        ticket=dict(request_id='transport',status='running')
        with patch('hamilton_park.driver_types',return_value=(Driver,SimpleNamespace(PrepPark=Park,PrepMethodAbort=Abort),Mock(),Mock())):
            asyncio.run(native_park(self.h,ticket,lambda:False,set()))
        self.assertEqual(calls,['open','Park','close'])


if __name__=='__main__':unittest.main()
