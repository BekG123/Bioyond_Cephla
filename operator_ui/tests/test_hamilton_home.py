"""Hamilton to actual saved Home: real queue Lua + guarded connector on fake hardware."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from test_latest_hamilton import LatestTests
from researcher_home import HomeReturn
from researcher_teaching import TeachingError
from autonomy import check_path


class HamiltonHomeTests(unittest.TestCase):
    def setUp(self):
        LatestTests.setUp(self)
        from hamilton_true_home import station_reference
        self.s.pose,self.s.q=station_reference(self.data)
        self.points=self.root/'points.json'
        self.points.write_text(json.dumps(dict(points={'Home':dict(x=289.97,y=62.63,z_grip=248.02,rz=-3.88)},roles={'home':'Home'})))
        self.s.envelope=dict(X=(200,450),Y=(-250,380),Z=(70,400))
        self.s.external_axes=lambda:dict(E1=3.7)
        self.s.status=lambda:dict(ok=True,connected=True,errors=[],pose_mm=self.s.pose,joints=self.s.q,
            control_mode={'mode':'auto'},program_state={'state':'running'},enabled=True)
        def rotate(rz,speed,force_delta):
            end={**self.s.pose,'Rz':rz}
            self.s.q=check_path(self.s.pose,end,self.s.q,self.s.cfg,self.s.envelope)
            self.s.pose=end
            return dict(ok=True)
        self.s.rotate_to_rz=rotate
        self.home=HomeReturn(self.points,lambda:self.s,lambda:self.run,
            lambda:SimpleNamespace(public=lambda _:dict(state='off')),lambda:self.s.cfg,Mock(),prepare=self.prepare)
        self.home.hamilton_route=self.latest
        self.body=dict(ready=True,target_id=self.home.target()[1])

    def test_full_return_uses_exact_queue_then_actual_home_without_changing_workspace(self):
        envelope=dict(self.s.envelope)
        self.assertTrue(self.home.public(self.s.status(),dict(state='off'))['can_start'])
        self.home.start(self.body)
        result=self.run.finish()
        self.assertTrue(result['ok'])
        for k,v in self.home.target()[0].items():self.assertAlmostEqual(self.s.pose[k],v,places=3)
        self.assertEqual(len(self.s.robot.calls),3)
        self.assertEqual([c[1] for c in self.s.robot.calls],[137]*3)
        self.assertEqual(len(self.s.moves),0)
        self.assertEqual(self.s.envelope,envelope)
        self.assertEqual(self.s.grips,[])
        saved=json.loads(next(self.latest.attempts.glob('*saved_home.json')).read_text())
        self.assertEqual(saved['status'],'completed')
        self.assertEqual(saved['target'],self.home.target()[0])

    def test_home_area_is_no_longer_an_automatic_destination(self):
        self.home.start(self.body);self.run.finish()
        ready=self.home.public(self.s.status(),dict(state='off'))
        self.assertFalse(ready['can_go_to_area'])
        before=len(self.s.robot.calls)
        with self.assertRaisesRegex(TeachingError,'retired'):
            self.home.start(dict(ready=True,target_id=ready['area_target_id'],destination='home_area'))
        self.assertEqual(len(self.s.robot.calls),before)

    def test_invalid_connector_rejected_before_any_departure(self):
        self.s.envelope['Z']=(70,220)
        with self.assertRaises(TeachingError):
            self.home.start(self.body)
        self.assertEqual(self.s.robot.calls,[]);self.assertEqual(self.s.moves,[])
        self.prepare.assert_not_called()

    def test_unknown_outside_start_does_not_get_route_exception(self):
        self.s.pose['Y']-=5
        with self.assertRaises(TeachingError):self.home.start(self.body)
        self.assertEqual(self.s.robot.calls,[])

    def test_stop_in_queue_never_starts_connector(self):
        self.home.start(self.body)
        self.run.cancelled=True
        with self.assertRaises(Exception):self.run.finish()
        self.assertEqual(self.s.moves,[])
        saved=json.loads(next(self.latest.attempts.glob('*saved_home.json')).read_text())
        self.assertEqual(saved['status'],'stopped_or_failed')

    def test_failed_connector_cannot_be_retried_from_home_area(self):
        self.latest.attempts.mkdir(parents=True)
        (self.latest.attempts/'1.json').write_text(json.dumps(dict(status='stopped_or_failed')))
        endpoint=self.data['trajectory'][-1]
        self.s.pose=dict(endpoint['pose_mm']);self.s.q=dict(endpoint['joints'])
        ready=self.home.public(self.s.status(),dict(state='off'))
        self.assertFalse(ready['can_start'])
        self.assertIn('previous route has no verified completion',ready['blocker'])
        self.assertIn('Resetting the controller does not resolve',ready['blocker'])
        with self.assertRaises(TeachingError):self.home.start(self.body)
        self.assertEqual(self.s.robot.calls,[])


if __name__=='__main__':unittest.main()
