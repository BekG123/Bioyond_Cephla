"""Qualification, limits, attestation, sensors, conditions and the ledger."""
from conftest import kinds


def test_blocked_operation_is_refused_until_a_person_overrides(lab):
    run, console = lab.run(lab.one_step('hamilton_prep', 'plate_transfer'))
    result = lab.facade.run_step(run, 's01')
    assert (result['outcome'], result['code']) == ('refused', 'not_qualified')
    assert result['detail']['qualification'] == 'blocked' and 'release' in result['detail']['blocker']
    assert lab.sent('hamilton_prep') == []
    console.override('s01', 'bek', 'supervised retest after tool replacement')
    assert lab.facade.run_step(run, 's01')['outcome'] == 'completed'
    assert 'override_used' in [e['status'] for e in kinds(run, 'approval')]


def test_operation_with_no_qualification_entry_is_untested(lab):
    run, _ = lab.run(lab.one_step('hamilton_prep', 'untested_move'))
    result = lab.facade.run_step(run, 's01')
    assert (result['code'], result['detail']['qualification']) == ('not_qualified', 'untested')
    assert lab.sent('hamilton_prep') == []


def test_unknown_operation_and_machine_are_refused(lab):
    run, _ = lab.run(lab.one_step('hamilton_prep', 'self_destruct'))
    assert lab.facade.run_step(run, 's01')['code'] == 'unknown_operation'
    assert lab.facade.run_operation('centrifuge', 'spin')['code'] == 'unknown_machine'
    assert lab.facade.run_step(run, 's99')['code'] == 'unknown_step'


def test_unwired_operation_is_refused(lab):
    lab.fakes['hamilton_prep'].unbound.add('park')
    run, _ = lab.run(lab.one_step('hamilton_prep', 'park'))
    assert lab.facade.run_step(run, 's01')['code'] == 'not_bound'


def test_parameters_outside_limits_are_refused(lab):
    for params, code in (({'y_step': 0.8}, 'outside_limit'), ({'y_step': -0.8}, 'outside_limit'),
                         ({'y_step': True}, 'outside_limit'), ({'y_step': '0.2'}, 'outside_limit'),
                         ({'speed': 5}, 'undeclared_parameter')):
        run, _ = lab.run(lab.one_step('hamilton_prep', 'open_jaws', params))
        result = lab.facade.run_step(run, 's01')
        assert (result['outcome'], result['code']) == ('refused', code), params
        lab.clock.advance(1)
    for dz, ok in ((6, False), (-5.01, False), (5, True)):
        run, _ = lab.run(lab.one_step('bioyond_s4', 'move_z', {'dz': dz}))
        assert (lab.facade.run_step(run, 's01')['outcome'] == 'completed') is ok, dz
        lab.clock.advance(1)
    assert lab.sent('hamilton_prep') == [] and lab.sent('bioyond_s4') == ['move_z']


def test_parameter_at_the_limit_runs(lab):
    run, _ = lab.run(lab.one_step('hamilton_prep', 'open_jaws', {'y_step': 0.5}))
    assert lab.facade.run_step(run, 's01')['outcome'] == 'completed'


def test_supervised_operation_without_attestation_pauses_the_run(lab):
    run, console = lab.run(attest=False)
    result = lab.facade.run_step(run, 's01')
    assert (result['outcome'], result['code']) == ('paused', 'attestation')
    assert lab.facade.run_step(run, 's01')['code'] == 'run_paused'
    assert lab.sent('squid') == []
    console.attest_presence('bek')
    console.resume('bek', 'now at the E-stop')
    assert lab.facade.run_step(run, 's01')['outcome'] == 'completed'


def test_qualified_operation_needs_no_attestation(lab):
    run, _ = lab.run(attest=False)
    assert lab.facade.run_step(run, 's02')['outcome'] == 'completed'


def test_heartbeat_lapse_pauses_at_the_next_step(lab):
    run, console = lab.run()
    assert lab.facade.run_step(run, 's01')['outcome'] == 'completed'
    lab.clock.advance(301)
    result = lab.facade.run_step(run, 's04')
    assert (result['outcome'], result['code']) == ('paused', 'attestation') and 'heartbeat' in result['reason']
    assert lab.sent('hamilton_prep') == []
    assert [e['status'] for e in kinds(run, 'pause')] == ['attestation']
    console.heartbeat('bek')
    assert lab.facade.run_step(run, 's04')['code'] == 'run_paused'      # a heartbeat alone does not resume
    console.resume('bek', 'back at the E-stop')
    assert lab.facade.run_step(run, 's04')['outcome'] == 'completed'
    assert [e['status'] for e in kinds(run, 'resume')] == ['resumed']


def test_sensor_answers_a_gate_or_a_person_does(lab):
    fake = lab.fakes['hamilton_prep']
    fake.sensor_values['door_closed'] = False
    run, console = lab.run(lab.one_step('hamilton_prep', 'park'))
    result = lab.facade.run_step(run, 's01')
    assert (result['outcome'], result['code']) == ('waiting', 'sensor_check_failed')
    fake.sensor_values['door_closed'] = None                 # no sensor can answer
    assert lab.facade.run_step(run, 's01')['detail']['confirm'] == ['door closed']
    assert fake.commands == []
    fake.sensor_values['door_closed'] = True
    assert lab.facade.run_step(run, 's01')['outcome'] == 'completed'
    assert 'sensor_ok' in [e['status'] for e in kinds(run, 'gate')]


def test_precondition_not_met_waits_without_sending(lab):
    fake = lab.fakes['hamilton_prep']
    fake.conditions['initialized'] = False
    run, _ = lab.run(lab.one_step('hamilton_prep', 'park'))
    assert lab.facade.run_step(run, 's01')['code'] == 'precondition_not_met'
    fake.state = 'busy'
    fake.conditions['initialized'] = True
    assert lab.facade.run_step(run, 's01')['code'] == 'machine_busy'
    assert fake.commands == []
    fake.state = 'idle'
    assert lab.facade.run_step(run, 's01')['outcome'] == 'completed'


def test_failed_postcondition_stops_the_run(lab):
    lab.fakes['squid'].conditions['acquisition complete'] = False
    run, _ = lab.run()
    result = lab.facade.run_step(run, 's03')
    assert (result['outcome'], result['code']) == ('failed', 'postcondition_failed')
    assert lab.facade.run_step(run, 's04')['code'] == 'run_paused'
    assert lab.sent('hamilton_prep') == []


def test_uncheckable_postcondition_is_not_called_success(lab):
    del lab.fakes['squid'].conditions['acquisition complete']
    run, _ = lab.run()
    result = lab.facade.run_step(run, 's03')
    assert (result['outcome'], result['detail']['unverified']) == ('completed_unverified', ['acquisition complete'])
    assert kinds(run, 'pause')


def test_ledger_mismatch_stops_before_anything_moves(lab):
    plan = lab.one_step('bioyond_s4', 'place_plate', {'station': 'squid'},
                        transfer={'plate': 'P1', 'from': 'hamilton', 'to': 'squid stage'})
    run, _ = lab.run(plan)
    result = lab.facade.run_step(run, 's01')
    assert (result['outcome'], result['code']) == ('paused', 'ledger_mismatch')
    assert "recorded at 'gripper'" in result['reason']
    assert lab.sent('bioyond_s4') == []
    assert run.read_json('ledger.json')['plates']['P1']['location'] == 'gripper'


def test_validate_plan_shows_problems_before_approval(lab):
    plan = dict(title='bad', plates={'P1': 'shelf'}, steps=[
        dict(id='a', machine='hamilton_prep', operation='plate_transfer'),
        dict(id='b', machine='hamilton_prep', operation='open_jaws', params={'y_step': 2}),
        dict(id='c', machine='nowhere', operation='x')])
    codes = [p['code'] for p in lab.facade.validate_plan(plan)]
    assert codes == ['bad_location', 'not_qualified', 'outside_limit', 'unknown_machine']
    from conftest import PLAN
    assert lab.facade.validate_plan(PLAN) == []


def test_describe_reports_qualification_and_faults(lab):
    listing = lab.facade.describe('hamilton_prep')
    assert {o['name']: o['qualification'] for o in listing['operations']}['plate_transfer'] == 'blocked'
    detail = lab.facade.describe('hamilton_prep', 'plate_transfer')
    assert detail['known_faults'][0]['id'] == 'release_slip'
    assert lab.facade.describe('hamilton_prep', 'open_jaws')['limits']['y_step']['value'] == 0.5
