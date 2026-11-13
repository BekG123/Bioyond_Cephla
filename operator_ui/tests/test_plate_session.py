"""Offline location migration and release-before-rotation checks. No robot I/O."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plate_session import (CalibrationSession, configuration, preview, public_labels,
                           verify_holder, verify_rotation_clearance)
from researcher_teaching import TeachingError


class PlateSessionTests(unittest.TestCase):
    def readings(self, angle):
        return [dict(at=98.5+i*.5, degrees=angle) for i in range(3)]

    def test_absolute_taught_target_not_original_plus_quarter_turn(self):
        plan = preview('Hamilton', dict(calibrated=False))
        self.assertEqual(plan['rotation']['target_mode'], 'absolute')
        self.assertAlmostEqual(plan['rotation']['target_degrees'], 90.71661229181757)
        verify_holder('Hamilton', self.readings(90.717), now=100)
        with self.assertRaises(ValueError):
            verify_holder('Hamilton', self.readings(91.77), now=100)

    def test_original_squid_band_does_not_rotate(self):
        plan = preview('Squid', dict(calibrated=True))
        self.assertFalse(next(s for s in plan['steps'] if s['state']=='HOME_ORIENTED')['rotate'])
        self.assertNotIn('CALIBRATING', [s['state'] for s in plan['steps']])
        for value in (1.740, 1.749324037839865, 1.750, 1.7575638072998392, 1.760, 1.763057, 1.769, 1.77, 1.82):
            verify_holder('Squid', self.readings(value), now=100)
        for value in (1.739999, 1.821, 90.717, float('nan')):
            with self.assertRaises(ValueError):
                verify_holder('Squid', self.readings(value), now=100)

    def test_no_rotation_before_release_lift_and_open(self):
        order = [s['state'] for s in preview('Hamilton', dict(calibrated=False))['steps']]
        self.assertLess(order.index('HOME_RELEASED'), order.index('HOME_CLEAR'))
        self.assertLess(order.index('HOME_CLEAR'), order.index('HOME_ORIENTED'))
        self.assertLess(order.index('HOME_VERIFIED'), order.index('HOME_GRIPPED'))

    def clear_observation(self):
        return dict(at=99.5, z_mm=103.718, e1_mm=28, e2_degrees=1.77,
            lift_from_seated_mm=30, stationary=True, plate_supported=True,
            plate_released=True, sweep_reviewed=True, hands_clear=True,
            estop_supervised=True, path_checked=True, payload='empty', fault=False, timeout=False)

    def test_clearance_needs_actual_release_not_just_open_position(self):
        observation = self.clear_observation()
        self.assertTrue(verify_rotation_clearance(observation, seated_z=73.718, now=100))
        for field, value in [('plate_released', False), ('payload', 'held'), ('fault', True),
                             ('timeout', True), ('sweep_reviewed', False), ('stationary', False),
                             ('e1_mm', 25), ('z_mm', 73.718), ('at', 96), ('e2_degrees', float('nan'))]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_rotation_clearance(dict(observation, **{field:value}), seated_z=73.718, now=100)

    def test_stale_duplicate_and_missing_holder_feedback_rejected(self):
        for samples in ([1.77]*3, self.readings(1.77)[:2],
                        [dict(at=99, degrees=1.77)]*3, [dict(at=96+i*.1,degrees=1.77) for i in range(3)]):
            with self.assertRaises(ValueError):
                verify_holder('Squid', samples, now=100)

    def test_calibration_reuse_bound_to_session_and_setup(self):
        session = CalibrationSession()
        with self.assertRaises(ValueError):
            session.complete(run_id='bad', result={'ok':False}, setup='a')
        session.complete(run_id='verified', result={'ok':True}, setup='a')
        self.assertTrue(session.public('a')['calibrated'])
        self.assertFalse(session.public('b')['calibrated'])
        session.complete(run_id='again', result={'ok':True}, setup='b')
        session.invalidate('timeout')
        self.assertFalse(session.public('b')['calibrated'])
        self.assertFalse(CalibrationSession().public()['calibrated'])

    def test_names_do_not_modify_legacy_action_ids_or_new_plans(self):
        old = dict(summary='Return Home', actions=['move_home'], station='Home', source='Home/trial.json')
        result = public_labels(old)
        self.assertEqual(result['summary'], 'Return IDLE')
        self.assertEqual(result['station'], 'IDLE')
        self.assertEqual(result['actions'], old['actions'])
        self.assertEqual(result['source'], old['source'])
        plan = preview('Hamilton', dict(calibrated=False))
        self.assertEqual(public_labels(plan), plan)
        self.assertEqual(old['station'], 'Home')

    def test_missing_destination_never_defaults_to_hamilton(self):
        for value in (None, '', 'hamilton', 'Unknown'):
            with self.assertRaises(ValueError):preview(value, dict(calibrated=False))

    def agent(self):
        from lacry_agent import LacryAgent
        backend = SimpleNamespace(state=Mock(return_value=dict(
            robot=dict(connected=True,ok=True,errors=[]), hand=dict(state='off'))))
        runner = SimpleNamespace(active=False, reserved=False)
        return LacryAgent(backend, Mock(), lambda:runner, client=Mock())

    def test_new_home_never_dispatches_legacy_parking_move(self):
        agent = self.agent()
        agent._run_legacy_tool = Mock(side_effect=AssertionError('must not dispatch parking'))
        agent.plan_home_clearance_recovery = Mock(return_value=dict(
            id='recovery', executable=True, dispatch='home_clearance_recovery'))
        response, failed = agent._run_tool('propose_actions', dict(actions=['move_home']))
        self.assertFalse(failed)
        plan = json.loads(response)['plan']
        self.assertTrue(plan['executable'])
        self.assertEqual(plan['dispatch'], 'home_clearance_recovery')
        self.assertTrue(json.loads(response)['awaiting_confirmation'])
        agent.plan_home_clearance_recovery.assert_called_once_with()
        agent._run_legacy_tool.assert_not_called()

    def test_home_button_selects_clearance_recovery(self):
        agent = self.agent()
        agent.plan_home_clearance_recovery = Mock(return_value={'recovery': True})
        agent.plan_plate_session = Mock(side_effect=AssertionError('must not select calibration'))
        self.assertEqual(agent.button('move_home'), {'recovery': True})
        agent.plan_home_clearance_recovery.assert_called_once_with(source='button')

    def test_recover_button_preserves_bound_recovery_id(self):
        agent = self.agent()
        agent._recovery_plan = Mock(return_value=dict(id='a'*32, steps=[], requirements=[],
            dispatch='home_clearance_recovery', labels=['Recover HOME clearance']))
        plan = agent.button('recover')
        self.assertEqual(plan['id'], 'a'*32)
        self.assertEqual(agent.pending['id'], plan['id'])

    def test_home_refusal_does_not_substitute_calibration_or_parking(self):
        from autonomy import TransferError
        agent = self.agent()
        agent.plan_home_clearance_recovery = Mock(side_effect=TransferError('Unknown recovery position'))
        agent._run_legacy_tool = Mock(side_effect=AssertionError('must not dispatch parking'))
        agent.plan_plate_session = Mock(side_effect=AssertionError('must not select calibration'))
        response, failed = agent._run_tool('propose_actions', dict(actions=['move_home']))
        self.assertTrue(failed)
        self.assertIn('Unknown recovery position', response)

    def test_idle_alias_uses_unchanged_legacy_route(self):
        agent = self.agent()
        agent._run_legacy_tool = Mock(return_value=('{}', False))
        agent._run_tool('propose_actions', dict(actions=['move_idle']))
        self.assertEqual(agent._run_legacy_tool.call_args.args[1]['actions'], ['move_home'])

    def test_new_experiment_cannot_skip_holder_preparation(self):
        agent = self.agent()
        agent._run_legacy_tool = Mock(side_effect=AssertionError('must not skip new preparation'))
        response, failed = agent._run_tool('plan_lab_roundtrip', dict(repetitions=5))
        self.assertFalse(failed)
        plan = json.loads(response)['plan']
        self.assertEqual(plan['first_destination'], 'Hamilton')
        self.assertEqual(plan['requested_workflow']['arguments']['repetitions'], 5)
        self.assertFalse(plan['executable'])

    def test_fault_hand_guiding_and_new_session_invalidate_cached_calibration(self):
        from plate_session import setup_digest
        agent = self.agent()
        session = CalibrationSession()
        agent.classic = SimpleNamespace(calibration_session=session)
        for robot, hand in [(dict(connected=False), dict(state='off')),
                            (dict(connected=True,ok=True,errors=['fault']), dict(state='off')),
                            (dict(connected=True,ok=True,errors=[]), dict(state='active'))]:
            session.complete(run_id='prior', result={'ok':True}, setup=setup_digest())
            self.assertFalse(agent.plate_session_status(robot, hand)['calibrated'])
        session.complete(run_id='prior', result={'ok':True}, setup=setup_digest())
        with self.assertRaisesRegex(TeachingError, 'already completed'):
            agent._classic_plan()
        agent.pending = {'id':'old-plan'}
        response, failed = agent._run_tool('begin_plate_session', dict(reason='Operator reseated the fixture'))
        self.assertFalse(failed)
        self.assertFalse(json.loads(response)['motion_started'])
        self.assertFalse(json.loads(response)['session']['calibrated'])
        self.assertIsNone(agent.pending)

    def test_model_contract_has_no_legacy_home_parking_instruction(self):
        from lacry_agent import SYSTEM, TOOLS
        self.assertIn('absolute E2=90.71661229181757', SYSTEM)
        self.assertIn('move_idle', SYSTEM)
        self.assertNotIn('Home means the saved true Home', SYSTEM)
        actions = next(t for t in TOOLS if t['name']=='propose_actions')['input_schema']['properties']['actions']['items']['enum']
        self.assertIn('move_idle', actions)
        self.assertIn('move_home', actions)

    def test_session_renewal_rejects_active_or_reserved_work(self):
        agent=self.agent()
        agent.classic=SimpleNamespace(calibration_session=CalibrationSession())
        original=agent.classic.calibration_session
        for flag in ('active','reserved'):
            setattr(agent.get_runner(),flag,True)
            with self.assertRaises(TeachingError):agent.begin_plate_session('Requested repeat')
            self.assertIs(agent.classic.calibration_session,original)
            setattr(agent.get_runner(),flag,False)
        for reason in ('',None,'x'*301):
            with self.assertRaises(TeachingError):agent.begin_plate_session(reason)

    def test_session_begin_api_resets_receipt_without_motion(self):
        from flask import Flask
        from researcher import register_researcher
        agent=self.agent()
        agent.classic=SimpleNamespace(calibration_session=CalibrationSession())
        agent.confirm=Mock(side_effect=AssertionError('no motion'))
        app=Flask(__name__)
        register_researcher(app,lambda:{},lacry=agent)
        response=app.test_client().post('/researcher/api/lacry/plate-session/begin',json={'reason':'Operator requested repeat'})
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json['motion_started'])
        self.assertFalse(response.json['session']['calibrated'])
        agent.confirm.assert_not_called()

    def test_preview_api_never_calls_confirmation_or_motion(self):
        from flask import Flask
        from researcher import register_researcher
        app = Flask(__name__)
        agent = self.agent()
        agent.confirm = Mock(side_effect=AssertionError('no motion'))
        register_researcher(app, lambda:{}, lacry=agent)
        response = app.test_client().post('/researcher/api/lacry/plate-session/plan',
                                         json={'first_destination':'Hamilton'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['plan']['executable'])
        self.assertEqual(response.json['plan']['rotation']['target_mode'], 'absolute')
        agent.confirm.assert_not_called()


if __name__ == '__main__':
    unittest.main()
