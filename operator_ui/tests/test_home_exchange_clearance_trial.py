"""Offline command-inhibition and failure tests. Never connects to hardware."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import home_exchange_clearance_trial as subject


class ClearanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'seating.json'
        self.pose = dict(X=312.011,Y=-65.478,Z=73.714,Rz=89.765)
        self.state = dict(robot=dict(connected=True,ok=True,errors=[],enabled=True,
                control_mode=dict(mode='auto'),program_state=dict(state='running'),
                pose_mm=deepcopy(self.pose),external_axes=dict(E1=3.9),joints={}),
                sequence=dict(active=False),envelope=dict(enabled=True,
                    X=dict(min=200,max=450),Y=dict(min=-250,max=380),Z=dict(min=70,max=400)))
        self.path.write_text(json.dumps(dict(status='placement_completed_awaiting_inspection_before_release',
                plan=dict(binding={'id':'test'}),final_state=deepcopy(self.state))))
        self.commands = []
        self.failure = None
        for target, replacement in [
            ('seating.bind', lambda p: ({}, {'id':'test'})),
            ('seating.holder.RECEIPT', self.path),
            ('seating.verify_holder_stationary', lambda: []),
            ('check_path', lambda *a: {}),
            ('api', self.api),
        ]:
            p = patch('home_exchange_clearance_trial.'+target, replacement)
            p.start(); self.addCleanup(p.stop)

    def api(self, endpoint, body=None):
        if endpoint == 'state': return deepcopy(self.state)
        if endpoint == 'researcher/api/status': return dict(hand_guiding=dict(state='off'))
        if endpoint == 'robot_params': return {}
        self.commands.append((endpoint, body))
        if endpoint == 'gripper':
            if self.failure == 'release': return dict(ok=False,error='controller fault')
            if self.failure == 'timeout': raise TimeoutError('uncertain release')
            self.state['robot']['external_axes']['E1'] = body['e1']
            return dict(ok=True, recovered=self.failure == 'recovered')
        if endpoint == 'move':
            self.state['robot']['pose_mm'] = {k:body[v] for k,v in [('X','x'),('Y','y'),('Z','z'),('Rz','rz')]}
            return dict(ok=True)
        if endpoint == 'program': return dict(ok=True)
        raise AssertionError(endpoint)

    def test_missing_support_never_commands(self):
        with self.assertRaisesRegex(RuntimeError, 'inspect full plate support'):
            subject.run('unused')
        self.assertEqual(self.commands, [])

    def test_failed_seating_never_releases(self):
        data = json.loads(self.path.read_text()); data['status']='stopped_or_failed'
        self.path.write_text(json.dumps(data))
        with self.assertRaisesRegex(RuntimeError, 'Successful checked seating'):
            subject.run('unused',support_confirmed=True)
        self.assertEqual(self.commands, [])

    def test_changed_grip_never_releases(self):
        self.state['robot']['external_axes']['E1'] = 7
        with self.assertRaisesRegex(RuntimeError, 'Gripper feedback'):
            subject.run('unused',support_confirmed=True)
        self.assertEqual(self.commands, [])

    def test_release_fault_inhibits_lift_and_full_opening(self):
        self.failure = 'release'
        with self.assertRaises(RuntimeError): subject.run('unused',support_confirmed=True)
        self.assertEqual([p for p,b in self.commands], ['gripper','program'])

    def test_release_timeout_never_retries_or_lifts(self):
        self.failure = 'timeout'
        with self.assertRaises(TimeoutError): subject.run('unused',support_confirmed=True)
        self.assertEqual([p for p,b in self.commands], ['gripper','program'])

    def test_recovered_response_inhibits_lift(self):
        self.failure = 'recovered'
        with self.assertRaises(RuntimeError): subject.run('unused',support_confirmed=True)
        self.assertEqual([p for p,b in self.commands], ['gripper','program'])

    def test_nan_grip_inhibits_commands(self):
        self.state['robot']['external_axes']['E1'] = float('nan')
        with self.assertRaisesRegex(RuntimeError, 'finite gripper'):
            subject.run('unused',support_confirmed=True)
        self.assertEqual(self.commands, [])

    def test_existing_attempt_cannot_replay(self):
        self.path.with_name('home_holder_release_clearance.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'already attempted'):
            subject.run('unused',support_confirmed=True)
        self.assertEqual(self.commands, [])


if __name__ == '__main__': unittest.main()
