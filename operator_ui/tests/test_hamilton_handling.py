"""Supervised Hamilton station operations through real Lua with fake hardware."""
from copy import deepcopy
import json
import unittest
import threading
import time
from unittest.mock import Mock,patch

import test_squid_handling as fixture
import hamilton_handling as geometry
import squid_handling as shared


class HamiltonHandlingTests(unittest.TestCase):
    setUp=fixture.SquidHandlingTests.setUp
    stop=fixture.SquidHandlingTests.stop
    jaw=fixture.SquidHandlingTests.jaw

    def test_live_inspection_public_state_serializes_and_approves_exact_id(self):
        self.agent.links=Mock(return_value={})
        outcome=[]
        def wait():
            try:
                self.agent._wait_review(self.run,'Inspect plate support')
                outcome.append('approved')
            except Exception as error:
                outcome.append(str(error))
        thread=threading.Thread(target=wait,daemon=True)
        thread.start()
        try:
            deadline=time.monotonic()+2
            while self.agent.review is None and time.monotonic()<deadline:
                time.sleep(.01)
            public=self.agent.public()
            json.dumps(public,allow_nan=False)
            self.assertEqual(set(public['review']),{'id','label','at'})
            self.assertEqual(public['review']['id'],self.agent.review['id'])
            with self.assertRaisesRegex(Exception,'out of date'):
                self.agent.approve_review(dict(review_id='wrong-id',approved=True))
            self.assertTrue(thread.is_alive())
            self.agent.approve_review(dict(review_id=public['review']['id'],approved=True))
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcome,['approved'])
            self.assertIsNone(self.agent.public()['review'])
            self.assertFalse(self.s.robot.calls)
        finally:
            if self.agent.review:
                self.agent.review['approved']=False
                self.agent.review['event'].set()
            thread.join(2)

    def test_roundtrip_sequences_and_inspections_use_real_queue(self):
        self.agent._wait_review=Mock()
        for action,start_e1,end_e1 in [('hamilton_dropoff',3.7,5),('hamilton_retrieve',5,3.7)]:
            self.e1=start_e1
            plan=self.agent.button(action)
            self.assertTrue(plan['supervised_trial'])
            self.assertFalse(plan['prepare'])
            self.assertFalse(plan['camera_required'])
            self.backend.verify_confirmation(plan)
            before=len(self.s.robot.calls)
            self.agent.confirm(dict(ready=True,plan_id=plan['id']))
            result=self.run.finish()
            self.assertTrue(result['ok'],result)
            self.assertEqual([c[1] for c in self.s.robot.calls[before:]],[137]*3+[5]+[137]*3)
            self.assertEqual(self.e1,end_e1)
            for axis in ('X','Y','Z','Rz'):
                self.assertAlmostEqual(self.s.pose[axis],self.path[0][axis],delta=.01)
        self.assertEqual(self.agent._wait_review.call_count,4)
        self.assertEqual(self.s.grips,[5.,3.7])
        self.assertFalse(self.stops)

    def test_chat_station_tool_is_executable_trial_without_motion(self):
        response,error=self.agent._run_tool('plan_station_handling',dict(station='Hamilton',operation='release'))
        result=json.loads(response)
        self.assertFalse(error,result)
        self.assertTrue(result['executable'])
        self.assertTrue(result['awaiting_confirmation'])
        self.assertFalse(self.s.robot.calls)
        self.assertFalse(self.s.grips)

    def test_arrival_rejection_prevents_jaw_and_lift(self):
        self.agent._wait_review=Mock(side_effect=RuntimeError('Arrival rejected'))
        result=self.agent._execute(self.run,self.agent.button('hamilton_dropoff'))
        self.assertFalse(result['ok'])
        self.assertEqual(len(self.s.robot.calls),3)
        self.assertFalse(self.s.grips)

    def test_lift_rejection_prevents_loaded_departure(self):
        self.e1=5
        self.agent._wait_review=Mock(side_effect=[None,RuntimeError('Plate slipped')])
        result=self.agent._execute(self.run,self.agent.button('hamilton_retrieve'))
        self.assertFalse(result['ok'])
        self.assertEqual(len(self.s.robot.calls),4)
        self.assertEqual(self.s.grips,[3.7])
        self.assertAlmostEqual(self.s.pose['Z'],66.22,places=4)

    def test_failed_jaw_stops_before_lift(self):
        self.agent._wait_review=Mock()
        self.s.move_gripper=Mock(return_value=dict(ok=False,error='fault'))
        result=self.agent._execute(self.run,self.agent.button('hamilton_dropoff'))
        self.assertFalse(result['ok'])
        self.assertEqual(len(self.s.robot.calls),3)

    def test_lift_exception_cannot_command_other_geometry_or_negative_joint(self):
        seated,lifted,_=geometry.reference()
        q=deepcopy(self.s.q);q['J1']=.01
        for start,target,joints in [
            ({**seated,'X':seated['X']+1},lifted,q),
            (seated,{**lifted,'Z':lifted['Z']+1},q),
            (seated,lifted,{**q,'J1':-.01}),
        ]:
            with self.assertRaises(Exception):
                geometry.check_lift(start,target,joints,self.cfg)
        self.assertFalse(self.s.robot.calls)

    def test_changed_local_settings_and_missing_evidence_refused(self):
        plan=self.agent.button('hamilton_dropoff')
        bad=deepcopy(plan)
        next(s for s in bad['steps'] if s['kind']=='hamilton_jaw')['target_e1']=7
        with self.assertRaisesRegex(Exception,'steps changed'):
            self.backend.verify_confirmation(bad)
        with patch('hamilton_accepted_route.HASHES',{'candidate.json':'invalid'}):
            with self.assertRaises(Exception):
                shared.plan(self.backend,'hamilton_dropoff')
        self.assertFalse(self.s.robot.calls)

    def test_payload_and_controller_must_be_ready_without_restart(self):
        with self.assertRaisesRegex(Exception,'jaws at 5'):
            self.agent.button('hamilton_retrieve')
        self.s.robot.program_state='stopped'
        with self.assertRaisesRegex(Exception,'not ready'):
            self.agent.button('hamilton_dropoff')
        self.assertFalse(self.s.robot.calls)


if __name__=='__main__':
    unittest.main()
