"""Approve once, then run. Nothing the agent holds can grant an approval."""
import inspect
import json
import shutil

from labfacade import Facade, HumanConsole, Signer
from conftest import PLAN, kinds


def test_approved_plan_runs_end_to_end(lab):
    run, _ = lab.run()
    assert [lab.facade.run_step(run, s)['outcome'] for s in ('s01', 's02', 's03', 's04')] == ['completed'] * 4
    assert lab.sent('squid') == ['return_to_loading', 'run_imaging']
    assert lab.sent('bioyond_s4') == ['place_plate'] and lab.sent('hamilton_prep') == ['park']
    assert run.read_json('ledger.json')['plates']['P1']['location'] == 'squid stage'
    assert list((run.path / 'frames/s02').glob('before_*.png')) and list((run.path / 'frames/s02').glob('after_*.png'))


def test_no_approval_is_refused(lab):
    run, _ = lab.run(approve=False)
    result = lab.facade.run_step(run, 's01')
    assert (result['outcome'], result['code']) == ('refused', 'no_approval')
    assert lab.sent('squid') == []
    assert kinds(run, 'result')[-1]['status'] == 'refused'


def test_expired_approval_is_refused(lab):
    run, _ = lab.run()
    lab.clock.advance(8 * 3600 + 1)
    assert lab.facade.run_step(run, 's02')['code'] == 'approval_expired'
    assert lab.sent('bioyond_s4') == []


def test_approval_from_another_run_is_refused(lab):
    first, _ = lab.run()
    lab.clock.advance(1)
    second, _ = lab.run(approve=False)
    shutil.copy(first.path / 'approval.json', second.path / 'approval.json')
    assert lab.facade.run_step(second, 's02')['code'] == 'approval_invalid'


def test_tampered_or_unsigned_approval_is_refused(lab):
    run, _ = lab.run()
    record = run.read_json('approval.json')
    run.write_json('approval.json', dict(record, expires_at=record['expires_at'] + 10 ** 6))
    assert lab.facade.run_step(run, 's02')['code'] == 'approval_invalid'
    run.write_json('approval.json', {k: v for k, v in record.items() if k != 'sig'})
    assert lab.facade.run_step(run, 's02')['code'] == 'approval_invalid'
    assert lab.sent('bioyond_s4') == []


def test_approval_signed_with_another_key_is_refused(lab):
    run, _ = lab.run(approve=False)
    HumanConsole(run, Signer(b'some-other-key-0123456789'), lab.clock).approve_plan('mallory')
    assert lab.facade.run_step(run, 's02')['code'] == 'approval_invalid'


def test_plan_edited_after_approval_is_refused(lab):
    run, _ = lab.run()
    record = json.loads((run.path / 'run.json').read_text())
    record['plan']['steps'][1]['params']['station'] = 'hamilton'
    (run.path / 'run.json').write_text(json.dumps(record))
    result = lab.facade.run_step(run, 's02')
    assert (result['outcome'], result['code']) == ('refused', 'plan_changed')
    assert lab.sent('bioyond_s4') == []


def test_parameters_other_than_the_approved_ones_are_refused(lab):
    run, _ = lab.run()
    result = lab.facade.run_operation('bioyond_s4', 'place_plate', {'station': 'hamilton'}, run, 's02')
    assert result['code'] == 'not_in_approved_plan'
    assert lab.facade.run_operation('bioyond_s4', 'pick_plate', {'station': 'squid'}, run, 's02')['code'] \
        == 'not_in_approved_plan'
    assert lab.sent('bioyond_s4') == []


def test_motion_outside_a_run_is_refused_and_reads_are_not(lab):
    assert lab.facade.run_operation('bioyond_s4', 'place_plate', {'station': 'squid'})['code'] == 'no_plan_step'
    assert lab.facade.run_operation('squid', 'get_status')['outcome'] == 'completed'
    assert lab.sent('bioyond_s4') == [] and lab.sent('squid') == ['get_status']


def test_the_facade_has_no_way_to_grant_anything():
    names = [n for n in dir(Facade) if not n.startswith('__')]
    for word in ('approve', 'attest', 'confirm', 'override', 'resume', 'heartbeat', 'sign'):
        assert not any(word in n for n in names), word
    for name in ('run_step', 'run_operation'):
        parameters = inspect.signature(getattr(Facade, name)).parameters
        assert not any(p in parameters for p in ('approved', 'operator_confirmed', 'confirmed'))


def test_state_change_needs_a_fresh_confirmation_each_time(lab):
    run, console = lab.run(lab.one_step('bioyond_s4', 'enable_robot'))
    result = lab.facade.run_step(run, 's01')
    assert (result['outcome'], result['detail']['confirm']) == ('waiting', ['confirm enable_robot'])
    console.confirm('s01', 'confirm enable_robot', 'bek')
    lab.clock.advance(121)                                   # the confirmation has gone stale
    assert lab.facade.run_step(run, 's01')['code'] == 'needs_confirmation'
    assert lab.sent('bioyond_s4') == []
    console.confirm('s01', 'confirm enable_robot', 'bek')
    assert lab.facade.run_step(run, 's01')['outcome'] == 'completed'


def test_unrecognized_gate_needs_a_person(lab):
    run, console = lab.run(lab.one_step('bioyond_s4', 'pick_plate', {'station': 'squid'}))
    assert lab.facade.run_step(run, 's01')['detail']['confirm'] == ['path clear']
    console.confirm('s01', 'path clear', 'bek')
    assert lab.facade.run_step(run, 's01')['outcome'] == 'completed'


def test_every_grant_is_logged(lab):
    run, console = lab.run()
    console.heartbeat('bek')
    statuses = [e['status'] for e in kinds(run, 'approval')]
    assert statuses == ['plan_approved', 'presence_attested', 'heartbeat']
    assert PLAN['steps'][0]['id'] == 's01'
