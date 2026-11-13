"""Fault-injection tests; no robot, instrument or model connections."""
import json
from pathlib import Path
import sys
import threading
from unittest.mock import Mock
from uuid import uuid4

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lacry_mcp_api as api
from lacry_recovery import RequestJournal


def host(path, agent=None, lock=None):
    agent = agent or Mock()
    agent.lab_api.tools.return_value = []
    agent._run_tool.return_value = (json.dumps({'ok': True, 'plan': 'original-plan'}), False)
    agent.stop.return_value = {'ok': True}
    agent.public.return_value = {'pending': None}
    app = Flask(__name__)
    journal = RequestJournal(path)
    api.register(app, agent, lock or threading.RLock(), token='fixture', journal=journal)
    return app, agent, journal


def call(app, ident, name='get_workflow_catalog', arguments=None):
    with app.test_client() as client:
        return client.post(api.PREFIX+'/call', headers={'X-Lacry-MCP': 'fixture'},
            json=dict(name=name, arguments=arguments or {}, request_id=ident))


def test_lost_reply_uses_durable_result_even_after_backend_restart(tmp_path):
    app, agent, journal = host(tmp_path/'requests.db')
    ident = uuid4().hex
    first = call(app, ident)
    assert first.status_code == 200
    restarted, other, _ = host(journal.path)
    recovered = call(restarted, ident)
    assert recovered.status_code == 200
    assert recovered.json['content'] == first.json['content']
    assert recovered.json['recovery']['receipt_replayed']
    agent._run_tool.assert_called_once()
    other._run_tool.assert_not_called()


def test_same_id_cannot_be_reused_for_another_operation(tmp_path):
    app, agent, _ = host(tmp_path/'requests.db')
    ident = uuid4().hex
    call(app, ident)
    response = call(app, ident, 'lacry_stop')
    assert response.status_code == 409
    assert response.json['recovery']['code'] == 'request_conflict'
    agent.stop.assert_not_called()


def test_restart_with_inflight_intent_never_replays_it(tmp_path):
    app, agent, journal = host(tmp_path/'requests.db')
    ident = uuid4().hex
    assert journal.begin(ident, 'get_workflow_catalog', {}) is None
    restarted, other, _ = host(journal.path)
    response = call(restarted, ident)
    assert response.json['recovery']['code'] == 'outcome_unknown'
    assert not response.json['recovery']['retryable']
    other._run_tool.assert_not_called()
    status = call(restarted, uuid4().hex, 'lacry_recovery_status', {'request_id': ident})
    assert json.loads(status.json['content'])['state'] == 'outcome_unknown'


def test_same_process_inflight_is_reported_without_duplicate_dispatch(tmp_path):
    app, agent, journal = host(tmp_path/'requests.db')
    ident = uuid4().hex
    journal.begin(ident, 'get_workflow_catalog', {})
    result = call(app, ident)
    assert result.json['recovery']['code'] == 'request_in_progress'
    agent._run_tool.assert_not_called()


def test_control_contention_can_recover_without_confirmation(tmp_path):
    lock = Mock()
    lock.acquire.side_effect = [False, True]
    app, agent, _ = host(tmp_path/'requests.db', lock=lock)
    ident = uuid4().hex
    refused = call(app, ident)
    assert refused.status_code == 409 and refused.json['recovery']['retryable']
    agent._run_tool.assert_not_called()
    assert call(app, ident).status_code == 200
    agent._run_tool.assert_called_once()
    agent.confirm.assert_not_called()


def test_stop_is_available_during_tool_and_cancels_queued_mutation(tmp_path):
    app, agent, _ = host(tmp_path/'requests.db')
    entered, release = threading.Event(), threading.Event()
    def work(*args):
        entered.set()
        assert release.wait(5)
        return json.dumps({'ok': True}), False
    agent._run_tool.side_effect = work
    replies = []
    running_id, queued_id = uuid4().hex, uuid4().hex
    worker = threading.Thread(target=lambda: replies.append(call(app, running_id)))
    worker.start()
    try:
        assert entered.wait(5)
        queued = call(app, queued_id, 'cancel_pending_plan')
        assert queued.json['recovery']['code'] == 'tool_busy'
        assert call(app, uuid4().hex, 'lacry_stop').status_code == 200
        agent.stop.assert_called_once()
        assert call(app, uuid4().hex, 'lacry_recovery_status').status_code == 200
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive() and replies[0].status_code == 200
    cancelled = call(app, queued_id, 'cancel_pending_plan')
    assert cancelled.json['recovery']['code'] == 'cancelled_by_stop'
    agent._run_tool.assert_called_once()


def test_queued_read_can_finish_after_stop(tmp_path):
    lock = Mock()
    lock.acquire.side_effect = [False, True]
    app, agent, _ = host(tmp_path/'requests.db', lock=lock)
    ident = uuid4().hex
    assert call(app, ident).status_code == 409
    assert call(app, uuid4().hex, 'lacry_stop').status_code == 200
    assert call(app, ident).status_code == 200


def test_ui_stop_cancels_the_same_mcp_queue(tmp_path):
    from lacry_agent import LacryAgent
    from sequences import Runner
    runner=Runner()
    agent=LacryAgent(Mock(),Mock(),lambda:runner,client=Mock())
    journal=RequestJournal(tmp_path/'requests.db')
    agent.cancel_mcp_waiters=journal.cancel_waiters
    ident=uuid4().hex
    journal.begin(ident,'cancel_pending_plan',{})
    journal.finish(ident,dict(ok=False),409,queued=True)
    assert agent.stop()['ok']
    assert journal.begin(ident,'cancel_pending_plan',{})[0]['recovery']['code']=='cancelled_by_stop'


def test_unexpected_tool_failure_is_saved_not_retried(tmp_path):
    app, agent, _ = host(tmp_path/'requests.db')
    agent._run_tool.side_effect = TimeoutError('ambiguous outcome')
    ident = uuid4().hex
    assert call(app, ident).status_code == 500
    assert call(app, ident).status_code == 500
    agent._run_tool.assert_called_once()


def test_failed_receipt_commit_does_not_repeat_tool(tmp_path, monkeypatch):
    app, agent, journal = host(tmp_path/'requests.db')
    monkeypatch.setattr(journal, 'finish', Mock(side_effect=OSError('disk unavailable')))
    ident = uuid4().hex
    assert call(app, ident).status_code == 500
    recovered = call(app, ident)
    assert recovered.status_code == 409
    assert recovered.json['recovery']['code'] == 'outcome_unknown'
    assert not recovered.json['recovery']['retryable']
    agent._run_tool.assert_called_once()


def test_failed_intent_commit_dispatches_nothing(tmp_path, monkeypatch):
    app, agent, journal = host(tmp_path/'requests.db')
    monkeypatch.setattr(journal, 'begin', Mock(side_effect=OSError('disk unavailable')))
    assert call(app, uuid4().hex).status_code == 500
    agent._run_tool.assert_not_called()


def test_stop_still_works_if_journal_is_unavailable(tmp_path, monkeypatch):
    app, agent, journal = host(tmp_path/'requests.db')
    monkeypatch.setattr(journal, 'connect', Mock(side_effect=OSError('disk unavailable')))
    result = call(app, uuid4().hex, 'lacry_stop')
    assert result.status_code == 200 and not result.json['is_error']
    agent.stop.assert_called_once()
    assert journal.stop_pending


def test_queued_mutations_are_cancelled_across_restart(tmp_path):
    lock=Mock();lock.acquire.return_value=False
    app, agent, journal = host(tmp_path/'requests.db', lock=lock)
    ident=uuid4().hex
    assert call(app, ident, 'cancel_pending_plan').status_code == 409
    restarted, other, _ = host(journal.path)
    assert call(restarted, ident, 'cancel_pending_plan').json['recovery']['code']=='cancelled_by_restart'
    other._run_tool.assert_not_called()


def test_delayed_stop_barrier_is_persisted_before_next_dispatch(tmp_path, monkeypatch):
    lock=Mock();lock.acquire.side_effect=[False, True]
    app, agent, journal = host(tmp_path/'requests.db', lock=lock)
    ident=uuid4().hex
    assert call(app, ident, 'cancel_pending_plan').status_code == 409
    with monkeypatch.context() as broken:
        broken.setattr(journal, 'connect', Mock(side_effect=OSError('disk unavailable')))
        assert call(app, uuid4().hex, 'lacry_stop').status_code == 200
    result=call(app, ident, 'cancel_pending_plan')
    assert result.json['recovery']['code']=='cancelled_by_stop'
    agent._run_tool.assert_not_called()


def test_audit_failure_preserves_completed_result(tmp_path):
    app, agent, _ = host(tmp_path/'requests.db')
    agent.get_runner.return_value.audit.side_effect = OSError('audit unavailable')
    ident = uuid4().hex
    assert call(app, ident).status_code == 200
    assert call(app, ident).status_code == 200
    agent._run_tool.assert_called_once()


@pytest.mark.parametrize('ident', ['../token', '', 'A'*32, 42])
def test_invalid_request_id_never_dispatches(tmp_path, ident):
    app, agent, _ = host(tmp_path/'requests.db')
    assert call(app, ident).status_code == 400
    agent._run_tool.assert_not_called()


def test_exact_receipt_can_be_inspected_without_repeating_tool(tmp_path):
    app, agent, _ = host(tmp_path/'requests.db')
    ident = uuid4().hex
    original = call(app, ident)
    inspected = call(app, uuid4().hex, 'lacry_recovery_status', {'request_id': ident})
    receipt = json.loads(inspected.json['content'])
    assert receipt['state'] == 'completed'
    assert receipt['response']['content'] == original.json['content']
    agent._run_tool.assert_called_once()


def test_unknown_receipt_is_not_permission_to_repeat(tmp_path):
    app, agent, _ = host(tmp_path/'requests.db')
    result = call(app, uuid4().hex, 'lacry_recovery_status', {'request_id': uuid4().hex})
    assert json.loads(result.json['content'])['found'] is False
    agent._run_tool.assert_not_called()
