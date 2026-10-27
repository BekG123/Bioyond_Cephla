"""Offline model/tool boundaries and measured motion. No API or robot network."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from imitation_agent import ImitationAgent, References, execute_stage, HaikuTools
from researcher_teaching import StationTeaching, TeachingError
from sequences import get_robot_params
from autonomy import TransferError


class Run:
    active = False
    name = ''
    cancelled = False
    state = 'idle'
    def start(self, name, fn, *args):
        if self.active:
            return dict(ok=False)
        self.active, self.name, self.task = True, name, (fn, args)
        self.cancelled = False
        self.state = 'running'
        return dict(ok=True)
    def finish(self):
        fn, args = self.task
        try:
            return fn(self, *args)
        finally:
            self.active = False
    def stopped(self): return self.cancelled
    def request_stop(self):
        self.cancelled = True
        return dict(ok=True)
    def audit(self, *args, **kwargs): pass
    def say(self, *args): pass


class Service:
    envelope_enabled = True
    envelope = dict(X=(200,400), Y=(-100,100), Z=(70,400))
    def __init__(self):
        self.pose = dict(X=300., Y=0., Z=120., Rz=0.)
        self.e1 = 15.
        self.commands = []
        self.fault = None
        self.torque = 0.
        self.bad_torque = False
    def _preflight(self): return self.fault
    def pose_mm(self): return self.pose.copy()
    def joints(self): return dict(J1=120., J2=60., J3=40., J4=-100.)
    def status(self):
        return dict(ok=True, connected=True, errors=[], pose_mm=self.pose.copy(), endpoint='test:56788',
                    external_axes=dict(E1=self.e1), control_mode=dict(mode='auto'), enabled=True,
                    program_state=dict(state='running'))
    def torque_report(self):
        return dict(ok=True, telemetry_live=True, joints=dict(J1=100., J2=0., J3=0.,
            J4=1000. if self.bad_torque and self.commands else 0.), e1_position=self.e1, e1_torque=self.torque)
    def move_gripper(self, target, speed=0):
        self.commands.append(('grip',target,speed)); self.e1 = target
        return dict(ok=True, gripper=dict(e1_position=target,e1_torque=self.torque,position_error=0.))
    def move_cartesian(self, x,y,z,rz,speed,kind):
        self.commands.append(('move',z,speed)); self.pose.update(X=x,Y=y,Z=z,Rz=rz)
        return dict(ok=True)


class ImitationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.svc, self.run = Service(), Run()
        self.teaching = StationTeaching(self.root/'teaching.json',lambda:self.svc,0)
        self.teaching.start(dict(name='Test',workflow='plate_pick_hamilton'))
        data = self.teaching._load()
        data['draft']['waypoints'] = [dict(station=name, pose_mm=dict(self.svc.pose, Z=z),
            captured_at='2026-10-16T00:00:00Z', source='robot_controller',endpoint='test:56788',
            kind='executed_algorithm' if name == 'Align' else 'manual_action',
            gripper=None if name == 'Align' else dict(E1=e1))
            for name,z,e1 in [('Align',120,15),('Descend',100,15),('Grip',100,14.6)]]
        self.teaching._store(data)
        self.refs = References(self.teaching,self.root/'reference.json',get_robot_params())
        candidate = self.refs.candidate()
        self.ref = self.refs.approve(dict(reference_id=candidate['id'],reviewed_clear_path=True))
        self.credentials = SimpleNamespace(key='test-key-never-sent', model='claude-haiku-4-5-20251001', ready=lambda:True)
        self.client = Mock()
        self.client.complete.side_effect = self.reply
        self.executor = Mock(side_effect=self.move)
        self.agent = ImitationAgent(self.refs,self.credentials,lambda:self.svc,lambda:self.run,
            self.root,client=self.client,executor=self.executor)
    def reply(self, payload):
        if payload['tool_choice']['type'] == 'none':
            return dict(stop_reason='end_turn',content=[dict(type='text',text='Measured action complete.')])
        return dict(stop_reason='tool_use',content=[dict(type='tool_use', id='test_tool',
            name=payload['tools'][0]['name'], input=dict(reference_id=self.ref['id']))])
    def move(self, run, svc, action, reference):
        if action == 'Descend': svc.pose = deepcopy(reference['end'])
        else: svc.e1 = reference['e1_end']
        return dict(ok=True,pose_mm=svc.pose)
    def start(self, action='Descend'):
        return self.agent.start(action,dict(reference_id=self.ref['id']))

    def test_descend_then_grip_is_unavailable(self):
        self.assertTrue(self.start()['ok'])
        self.assertTrue(self.run.finish()['ok'])
        self.assertFalse(self.agent.public(self.svc.status())['can_grip'])
        with self.assertRaises(TeachingError): self.start('Grip')
        self.assertEqual(self.executor.call_count,1)
        first = self.agent.events[0]['payload']
        self.assertEqual(len(first['messages']),1)  # Later feedback cannot mutate the saved request.
        self.assertNotIn(self.credentials.key,json.dumps(self.agent.events))

    def test_missing_measurement_cannot_be_approved(self):
        data = self.teaching._load()
        data['draft']['waypoints'][-1]['gripper'] = None
        self.teaching._store(data)
        with self.assertRaises(TeachingError): self.refs.candidate()

    def test_review_is_required_and_stale_review_rejected(self):
        with self.assertRaises(TeachingError): self.refs.approve(dict(reference_id=self.ref['id']))
        data = self.teaching._load(); data['draft']['revision'] += 1; self.teaching._store(data)
        with self.assertRaises(TeachingError):
            self.refs.approve(dict(reference_id=self.ref['id'],reviewed_clear_path=True))

    def test_xy_path_change_and_nonfinite_data_rejected(self):
        data = self.teaching._load()
        data['draft']['waypoints'][1]['pose_mm']['X'] += 10
        self.teaching._store(data)
        with self.assertRaises(TeachingError): self.refs.candidate()
        data['draft']['waypoints'][1]['pose_mm']['X'] = True
        self.teaching._store(data)
        with self.assertRaises(TeachingError): self.refs.candidate()

    def test_invalid_model_requests_never_execute(self):
        examples = [dict(stop_reason='end_turn',content=[dict(type='text',text='Move now')]),
                    dict(stop_reason='max_tokens',content=[])]
        base = self.reply(dict(tool_choice=dict(type='auto'),tools=[dict(name='descend_to_reference')]))
        for change in ('name','input','duplicate'):
            item = deepcopy(base)
            if change == 'name': item['content'][0]['name'] = 'reset_errors'
            elif change == 'input': item['content'][0]['input']['z'] = 0
            else: item['content'] *= 2
            examples.append(item)
        for answer in examples:
            with self.subTest(answer=answer):
                self.client.complete.side_effect = lambda payload:answer
                self.start(); self.assertFalse(self.run.finish()['ok'])
        self.executor.assert_not_called()

    def test_stop_during_api_wait_prevents_motion(self):
        def respond(payload):
            self.agent.stop()
            return self.reply(payload)
        self.client.complete.side_effect = respond
        self.start(); self.assertFalse(self.run.finish()['ok'])
        self.executor.assert_not_called()

    def test_live_pose_change_while_waiting_prevents_motion(self):
        def respond(payload):
            self.svc.pose['Z'] -= 2
            return self.reply(payload)
        self.client.complete.side_effect = respond
        self.start(); self.assertFalse(self.run.finish()['ok'])
        self.executor.assert_not_called()

    def test_fault_no_retry_no_grip(self):
        self.executor.side_effect = lambda *args:dict(ok=True,breach=True)
        self.start(); self.assertFalse(self.run.finish()['ok'])
        self.executor.assert_called_once()
        with self.assertRaises(TeachingError): self.start('Grip')

    def test_motion_exception_is_returned_to_model_without_recovery(self):
        self.executor.side_effect = TransferError('collision: inspect the arm')
        self.start(); self.assertFalse(self.run.finish()['ok'])
        self.executor.assert_called_once()
        feedback = self.client.complete.call_args.args[0]
        self.assertEqual(feedback['tool_choice'],dict(type='none'))
        self.assertTrue(feedback['messages'][-1]['content'][0]['is_error'])
        self.assertIn('collision',feedback['messages'][-1]['content'][0]['content'])

    def test_key_missing_busy_envelope_and_draggo_block(self):
        self.credentials.ready = lambda:False
        with self.assertRaises(TeachingError): self.start()
        self.credentials.ready = lambda:True
        self.run.active = True
        with self.assertRaises(TeachingError): self.start()
        self.run.active = False
        self.svc.envelope_enabled = False
        with self.assertRaises(TeachingError): self.start()
        self.svc.envelope_enabled = True; self.svc.fault = 'End hand-guiding'
        with self.assertRaises(TeachingError): self.start()
        self.client.complete.assert_not_called()

    def test_summary_failure_does_not_repeat_successful_motion(self):
        count = 0
        def respond(payload):
            nonlocal count
            count += 1
            if count > 1: raise TeachingError('API unavailable')
            return self.reply(payload)
        self.client.complete.side_effect = respond
        self.start(); self.assertTrue(self.run.finish()['ok'])
        self.executor.assert_called_once()
        self.assertIsNotNone(self.agent.descended)

    def test_evidence_summary_excludes_raw_samples(self):
        folder = self.root/'manual_motion_test'; folder.mkdir()
        (folder/'manual_session.json').write_text(json.dumps(dict(summary=dict(sample_count=10),
            samples=[dict(api_key='do-not-send')], metadata=dict(incident=dict(exclude_from_replay=True)))))
        self.start(); self.run.finish()
        evidence = json.loads(self.agent.events[0]['payload']['messages'][0]['content'])['diagnostic_evidence'][0]
        self.assertFalse(evidence['executable'])
        self.assertNotIn('samples',evidence)
        self.assertNotIn('do-not-send',json.dumps(self.agent.events))

    def test_legacy_grip_executor_cannot_close(self):
        self.svc.pose = deepcopy(self.ref['end'])
        with self.assertRaises(TransferError):execute_stage(self.run,self.svc,'Grip',self.ref)
        self.assertEqual(self.svc.commands,[])

    def test_grip_torque_breach_stops_without_reopening(self):
        self.svc.pose = deepcopy(self.ref['end']); self.svc.bad_torque = True
        with self.assertRaises(TransferError): execute_stage(self.run,self.svc,'Grip',self.ref)
        self.assertEqual(len(self.svc.commands),0)

    def test_grip_stop_and_existing_contact_no_motion(self):
        self.svc.pose = deepcopy(self.ref['end']); self.run.cancelled = True
        with self.assertRaises(TransferError): execute_stage(self.run,self.svc,'Grip',self.ref)
        self.run.cancelled = False; self.svc.torque = -150.
        with self.assertRaises(TransferError): execute_stage(self.run,self.svc,'Grip',self.ref)
        self.assertEqual(self.svc.commands,[])

    def test_descend_uses_guarded_path_and_actual_arrival(self):
        with patch('autonomy.check_path'), patch('pick_and_hold.Calibration.fast_disk.check_path') as check:
            result = execute_stage(self.run,self.svc,'Descend',self.ref)
        self.assertTrue(result['ok'],result); self.assertGreater(check.call_count,1)
        self.assertEqual(self.svc.pose['Z'],100.)
        self.assertTrue(all(cmd[0] == 'move' for cmd in self.svc.commands))
        self.assertTrue(all(100 <= cmd[1] < 120 for cmd in self.svc.commands))

    def test_path_rejection_before_descent(self):
        with patch('autonomy.check_path',side_effect=TransferError('outside envelope')):
            self.assertFalse(execute_stage(self.run,self.svc,'Descend',self.ref)['ok'])
        self.assertEqual(self.svc.commands,[])


if __name__ == '__main__': unittest.main()
