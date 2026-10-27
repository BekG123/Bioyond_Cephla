"""Explicit Home review matching and repeatable successful runs: fake services only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reviewed_home import ReviewedHomeConnection
from researcher_teaching import TeachingError


class ReviewedHomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        p=patch('reviewed_home.ROOT',root);p.start();self.addCleanup(p.stop)
        self.path=root/'reports/alignment_home/fixture.json';self.path.parent.mkdir(parents=True)
        self.home=Mock();self.home.path=root/'points.json';self.home.path.write_text('{}')
        self.pose=dict(X=315.936,Y=-66.974,Z=253.72,Rz=7.899)
        self.q=dict(J1=215.12,J2=40.345,J3=60.463,J4=-92.909)
        self.stages=[dict(kind='queue',points=[{**self.pose,'Z':300}]),dict(kind='rotate',rz=-3.88)]
        self.env=dict(X=[200,450],Y=[-250,380],Z=[70,400])
        self.state=dict(ok=True,connected=True,errors=[],pose_mm=deepcopy(self.pose),joints=deepcopy(self.q),external_axes=dict(E1=.019))
        self.svc=Mock(envelope=self.env,envelope_enabled=True)
        self.svc.status.return_value=self.state
        self.home.get_service.return_value=self.svc
        self.home.get_runner.return_value=Mock(active=False,reserved=False)
        self.home.get_draggo.return_value.public.return_value=dict(state='off')
        self.home.params.return_value=dict(limit=220)
        self.home.target.return_value=(dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88),'homehash')
        self.home.route_plan.return_value=dict(prefix=None,stages=deepcopy(self.stages))
        self.review=dict(schema='cephla.alignment-home-review.v1',ik_and_limits_passed=True,
            start=self.pose,start_joints=self.q,observed_e1=.019,config=dict(limit=220),envelope=self.env,
            home=self.home.target()[0],target_id='homehash',stages=self.stages,
            points_sha256=hashlib.sha256(self.home.path.read_bytes()).hexdigest())
        self.path.write_text(json.dumps(self.review))
        self.registry=root/'registry.json'
        self.registry.write_text(json.dumps(dict(review='reports/alignment_home/fixture.json',sha256=hashlib.sha256(self.path.read_bytes()).hexdigest())))
        self.connection=ReviewedHomeConnection(self.home,self.registry)

    def test_exact_review_proposes_without_starting(self):
        plan=self.connection.propose()
        self.assertEqual(plan['dispatch'],'reviewed_home_return')
        self.assertTrue(plan['requirements']);self.home.start.assert_not_called()

    def test_drift_claw_settings_and_route_changes_refused(self):
        mutations=[lambda:self.state['pose_mm'].update(X=316),
                   lambda:self.state['external_axes'].update(E1=3.8),
                   lambda:setattr(self.svc,'envelope_enabled',False),
                   lambda:self.home.route_plan.return_value.update(stages=[])]
        for mutate in mutations:
            mutate()
            with self.assertRaises(TeachingError):self.connection.propose()
            self.state['pose_mm']=deepcopy(self.pose);self.state['external_axes']=dict(E1=.019)
            self.svc.envelope_enabled=True;self.home.route_plan.return_value=dict(prefix=None,stages=deepcopy(self.stages))
        self.home.start.assert_not_called()

    def test_confirmation_revalidates_and_attempt_is_consumed(self):
        plan={**self.connection.propose(),'id':'confirmed'}
        self.state['pose_mm']['Y']+=1
        with self.assertRaises(TeachingError):self.connection.start(plan)
        self.home.start.assert_not_called()
        self.state['pose_mm']=deepcopy(self.pose)
        self.home.start.return_value=dict(ok=True)
        result,attempt=self.connection.start(plan)
        self.assertTrue(result['ok']);self.assertTrue(attempt.exists())
        with self.assertRaisesRegex(TeachingError,'no verified completion'):self.connection.propose()
        self.home.start.assert_called_once()
        self.connection.finish(attempt,dict(state='done',result=dict(ok=True)))
        self.assertEqual(json.loads(attempt.read_text())['status'],'completed')
        original=attempt.read_bytes()
        second={**self.connection.propose(),'id':'second-confirmation'}
        _,second_attempt=self.connection.start(second)
        self.assertNotEqual(attempt,second_attempt)
        self.connection.finish(second_attempt,dict(state='done',result=dict(ok=True)))
        self.assertEqual(attempt.read_bytes(),original)
        self.assertEqual(self.home.start.call_count,2)
        self.assertEqual(self.connection.propose()['dispatch'],'reviewed_home_return')

    def test_successful_legacy_record_is_preserved_and_allows_repeat(self):
        plan=self.connection.propose()
        legacy=self.path.with_name(self.path.stem+'_gui_attempt.json')
        legacy.write_text(json.dumps(dict(status='completed',review_sha256=plan['review_sha256'],
            plan_id='old',sequence=dict(state='done',result=dict(ok=True)))))
        original=legacy.read_bytes()
        self.home.start.return_value=dict(ok=True)
        _,attempt=self.connection.start({**self.connection.propose(),'id':'new'})
        self.connection.finish(attempt,dict(state='done',result=dict(ok=True)))
        self.assertEqual(legacy.read_bytes(),original)
        self.assertNotEqual(legacy,attempt)

    def test_failure_and_corrupt_history_are_not_silent_retries(self):
        plan=self.connection.propose()
        legacy=self.path.with_name(self.path.stem+'_gui_attempt.json')
        for content in ('{invalid',json.dumps(dict(status='failed_or_stopped',review_sha256=plan['review_sha256']))):
            legacy.write_text(content)
        with self.assertRaisesRegex(TeachingError,'no verified completion'):
                self.connection.propose()
        self.home.start.assert_not_called()

    def test_used_confirmation_cannot_start_twice(self):
        plan={**self.connection.propose(),'id':'single-confirmation'}
        self.home.start.return_value=dict(ok=True)
        _,attempt=self.connection.start(plan)
        self.connection.finish(attempt,dict(state='done',result=dict(ok=True)))
        with self.assertRaisesRegex(TeachingError,'confirmation was already used'):
            self.connection.start(plan)
        self.home.start.assert_called_once()

    def test_missing_or_changed_review_cannot_authorize(self):
        self.registry.unlink();self.assertIsNone(self.connection.propose())
        self.registry.write_text(json.dumps(dict(review='reports/alignment_home/fixture.json',sha256='bad')))
        with self.assertRaisesRegex(TeachingError,'changed'):self.connection.propose()
        self.home.start.assert_not_called()


if __name__=='__main__':unittest.main()
