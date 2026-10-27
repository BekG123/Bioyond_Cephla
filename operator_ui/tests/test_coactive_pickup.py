"""Offline measured preference updates; never contacts a real robot or API."""
import json
from unittest.mock import patch
import unittest

from test_imitation_agent import ImitationTests
from coactive_pickup import CoactivePickup
from researcher_teaching import TeachingError


class CoactiveTests(unittest.TestCase):
    reply = ImitationTests.reply
    move = ImitationTests.move

    def setUp(self):
        ImitationTests.setUp(self)
        self.learning = CoactivePickup(self.refs,self.root/'learning.json',lambda:self.svc,lambda:self.run,self.agent.invalidate)
        self.agent.coactive = self.learning
        self.sleep = patch('coactive_pickup.time.sleep')
        self.sleep.start(); self.addCleanup(self.sleep.stop)

    def capture(self, action='Descend'):
        return self.learning.capture(dict(action=action,reference_id=self.learning.reference()['id'],
            manually_demonstrated=True,note='Hand correction is preferred'))['proposal']

    def accept(self,p):
        return self.learning.decide(dict(proposal_id=p['id'],decision='accept',reviewed_clear_path=True))

    def test_capture_accept_persists_preference_and_changes_next_haiku_target(self):
        self.svc.pose['Z']=102
        p=self.capture()
        self.assertEqual(self.learning.reference()['end']['Z'],100)
        self.assertEqual(self.svc.commands,[])
        self.accept(p)
        self.assertEqual(self.learning.reference()['end']['Z'],102)
        self.assertEqual(len(self.learning.context()['preferences']),1)
        reloaded=CoactivePickup(self.refs,self.root/'learning.json',lambda:self.svc,lambda:self.run,self.agent.invalidate)
        self.assertEqual(reloaded.reference()['id'],p['reference']['id'])
        self.ref=self.learning.reference();self.svc.pose['Z']=120
        self.agent.start('Descend',dict(reference_id=self.ref['id']))
        self.assertTrue(self.run.finish()['ok'])
        self.assertEqual(self.executor.call_args.args[3]['end']['Z'],102)
        payload=self.client.complete.call_args_list[0].args[0]
        evidence=json.loads(payload['messages'][0]['content'])
        self.assertEqual(len(evidence['developer_preferences']['preferences']),1)
        self.assertTrue(self.learning.public()['outcomes'][0]['result']['ok'])

    def test_grip_correction_is_stationary_and_rejection_keeps_reference(self):
        self.svc.pose['Z']=100;self.svc.e1=14.8
        p=self.capture('Grip')
        self.assertEqual(p['reference']['e1_end'],14.8)
        self.learning.decide(dict(proposal_id=p['id'],decision='reject'))
        self.assertEqual(self.learning.reference()['e1_end'],14.6)
        self.assertEqual(self.svc.commands,[])

    def test_manual_ack_review_stale_and_busy_checks(self):
        self.svc.pose['Z']=102
        with self.assertRaises(TeachingError):self.learning.capture(dict(action='Descend',reference_id=self.ref['id']))
        a=self.capture();b=self.capture()
        with self.assertRaises(TeachingError):self.learning.decide(dict(proposal_id=a['id'],decision='accept'))
        self.accept(a)
        with self.assertRaises(TeachingError):self.accept(b)
        self.run.active=True
        with self.assertRaises(TeachingError):self.capture()

    def test_unhealthy_motion_lateral_and_excessive_corrections_rejected(self):
        self.svc.pose['Z']=102
        original=self.svc.status
        with patch.object(self.svc,'status',side_effect=lambda:{**original(),'errors':['collision']}):
            with self.assertRaises(TeachingError):self.capture()
        values=[{**original(),'pose_mm':{**self.svc.pose,'Z':z}} for z in (101,102,103)]
        with patch.object(self.svc,'status',side_effect=values):
            with self.assertRaises(TeachingError):self.capture()
        self.svc.pose['X']+=2
        with self.assertRaises(TeachingError):self.capture()
        self.svc.pose['X']-=2;self.svc.pose['Z']=80
        with self.assertRaises(TeachingError):self.capture()
        self.assertEqual(self.svc.commands,[])

    def test_new_base_does_not_inherit_previous_context_and_tamper_blocks(self):
        self.svc.pose['Z']=102;self.accept(self.capture())
        data=json.loads((self.root/'learning.json').read_text())
        data['accepted']['reference']['end']['Z']=90
        (self.root/'learning.json').write_text(json.dumps(data))
        with self.assertRaises(TeachingError):self.learning.reference()
        with patch.object(self.refs,'load',return_value={**self.ref,'id':'new-context'}):
            self.assertEqual(self.learning.reference()['id'],'new-context')
            self.assertEqual(self.learning.context()['preferences'],[])


if __name__=='__main__':unittest.main()
