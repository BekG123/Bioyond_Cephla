"""Offline tool boundary and Codex billing/authentication regression checks."""
import io
import json
import os
from pathlib import Path
import queue
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import lacry_mcp_api as api
from lacry_codex import CodexChat, CodexSession, input_items
from lacry_agent import LacryAgent
from researcher_teaching import TeachingError
from sequences import Runner


@pytest.fixture
def gateway(monkeypatch,tmp_path):
    agent=Mock();agent.lab_api.tools.return_value=[]
    agent.public.return_value={'ok':True,'pending':None}
    agent._run_tool.return_value=(json.dumps({'ok':True}),False)
    app=Flask(__name__);api.register(app,agent,threading.RLock(),token='test-secret',
        journal=api.RequestJournal(tmp_path/'requests.sqlite3'))
    return app.test_client(),agent


def post(client,name,args=None,**kwargs):
    return client.post(api.PREFIX+'/call',json=dict(name=name,arguments=args or {}),
                       headers={'X-Lacry-MCP':'test-secret',**kwargs.pop('headers',{})},**kwargs)


def test_catalog_preserves_tools_and_has_no_approval_or_raw_motion(gateway):
    client,agent=gateway
    response=client.get(api.PREFIX+'/tools',headers={'X-Lacry-MCP':'test-secret'})
    names={t['name'] for t in response.json['tools']}
    assert {'get_workflow_catalog','plan_plate_transfer','look_at_camera','lacry_state','lacry_stop'}<=names
    assert not {'confirm','start','move_cartesian','clear_errors','enable','send','chat'} & names
    agent.client.complete.assert_not_called();agent._run_tool.assert_not_called()


@pytest.mark.parametrize('headers,remote',[({},'127.0.0.1'),({'X-Lacry-MCP':'wrong'},'127.0.0.1'),
    ({'X-Lacry-MCP':'test-secret','Origin':'https://example.com'},'127.0.0.1'),
    ({'X-Lacry-MCP':'test-secret'},'192.168.1.15')])
def test_endpoint_requires_local_nonbrowser_credential(gateway,headers,remote):
    client,agent=gateway
    r=client.post(api.PREFIX+'/call',json={'name':'lacry_stop','arguments':{}},headers=headers,
                  environ_overrides={'REMOTE_ADDR':remote})
    assert r.status_code==403;agent.stop.assert_not_called()


@pytest.mark.parametrize('name,args',[('confirm',{}),('plan_plate_transfer',{'ready':True}),
    ('get_workflow_catalog',{'execute':True}),('lacry_state',{'unexpected':1})])
def test_unrecognized_commands_and_arguments_fail_before_dispatch(gateway,name,args):
    client,agent=gateway
    assert post(client,name,args).status_code==400
    agent._run_tool.assert_not_called();agent.confirm.assert_not_called()


def test_dispatch_uses_existing_workflow_tool_without_model_call(gateway):
    client,agent=gateway
    args=dict(plate_profile='Cellvis P24-1.5H-N',source_slot=1,destination='Squid',roundtrip=True)
    r=post(client,'plan_plate_transfer',args)
    assert r.status_code==200 and not r.json['is_error']
    agent._run_tool.assert_called_once_with('plan_plate_transfer',args)
    agent.client.complete.assert_not_called();agent.confirm.assert_not_called()


def test_errors_are_json_and_never_retried(gateway):
    client,agent=gateway;agent._run_tool.side_effect=TimeoutError('uncertain')
    r=post(client,'get_workflow_catalog')
    assert r.status_code==500 and 'No automatic retry' in r.json['message']
    agent._run_tool.assert_called_once()


@pytest.mark.parametrize('account',[None,{'type':'apiKey'},{'type':'amazonBedrock'}])
def test_non_chatgpt_authentication_cannot_start_thread(tmp_path,account):
    session=CodexSession(tmp_path);session.proc=Mock();session.proc.poll.return_value=None
    session.rpc=Mock(return_value={'account':account})
    with pytest.raises(TeachingError,match='fallback is disabled'):session.ensure('instructions')
    session.rpc.assert_called_once_with('account/read',{'refreshToken':False})
    session.proc=None


def test_thread_is_limited_to_lacry_mcp_and_read_only_without_shell(tmp_path):
    session=CodexSession(tmp_path);session.proc=Mock();session.proc.poll.return_value=None
    session.rpc=Mock(side_effect=[{'account':{'type':'chatgpt'}},
        {'config':{'mcp_servers':{'unrelated':{'enabled':True}}}}, {'thread':{'id':'test-thread'}}])
    session.ensure('instructions')
    method,params=session.rpc.call_args.args
    assert method=='thread/start' and params['sandbox']=='read-only'
    assert params['config']['mcp_servers']['unrelated']['enabled'] is False
    assert params['config']['mcp_servers']['lacry']['enabled'] is True
    assert not params['config']['features']['shell_tool']
    session.proc=None


def test_codex_completion_uses_final_message_and_does_not_retry(tmp_path):
    session=CodexSession(tmp_path);session.ensure=Mock();session.thread_id='thread'
    session.check_tools=Mock()
    session.rpc=Mock(return_value={'turn':{'id':'turn'}})
    session.read=Mock(side_effect=[{'method':'item/completed','params':{'threadId':'thread','item':
        {'type':'agentMessage','phase':'final_answer','text':'Ready to review.'}}},
        {'method':'turn/completed','params':{'threadId':'thread','turn':{'id':'turn','status':'completed'}}}])
    assert session.turn('instructions',[{'type':'text','text':'plan'}])=='Ready to review.'
    session.rpc.assert_called_once()


def test_canceled_turn_interrupts_without_resending(tmp_path):
    session=CodexSession(tmp_path);session.ensure=Mock();session.thread_id='thread'
    session.check_tools=Mock()
    session.rpc=Mock(return_value={'turn':{'id':'turn'}});session.write=Mock();session.close=Mock()
    session.read=Mock(side_effect=TeachingError('timeout'))
    with pytest.raises(TeachingError):session.turn('instructions',[])
    session.rpc.assert_called_once();session.close.assert_called_once()
    assert session.write.call_args.args[0]['method']=='turn/interrupt'


def test_existing_chat_uses_codex_without_anthropic_credentials():
    runner=Runner();credentials=Mock();credentials.ready.return_value=False
    agent=LacryAgent(Mock(),credentials,lambda:runner,client=Mock())
    bridge=Mock();bridge.send.return_value={'ok':True};agent.codex_chat=bridge
    assert agent.send('Which workflows are available?')=={'ok':True}
    bridge.send.assert_called_once();credentials.ready.assert_not_called();agent.client.complete.assert_not_called()


def test_human_yes_keeps_existing_confirmation_path():
    agent=LacryAgent(Mock(),Mock(),lambda:Runner(),client=Mock());agent.codex_chat=Mock()
    agent.confirm_from_chat=Mock(return_value={'ok':True})
    agent.send('Yes')
    agent.confirm_from_chat.assert_called_once_with('Yes');agent.codex_chat.send.assert_not_called()


def test_legacy_model_calls_blocked_in_mcp_mode(monkeypatch):
    monkeypatch.setenv('LACRY_LLM_PROVIDER','codex_mcp')
    from imitation_agent import HaikuTools
    from plate_agent import VisionClient
    with pytest.raises(TeachingError,match='disabled'):HaikuTools(Mock()).complete({})
    with pytest.raises(Exception,match='disabled'):VisionClient().describe(None,None,None)


def test_text_and_camera_inputs_are_supported():
    items=input_items('hello',[{'type':'text','text':'document text'},
        {'type':'image','source':{'media_type':'image/png','data':'AA=='}}])
    assert items[-1]=={'type':'image','url':'data:image/png;base64,AA=='}


def test_missing_mcp_tools_blocks_generation(tmp_path):
    session=CodexSession(tmp_path);session.ensure=Mock();session.thread_id='thread'
    session.rpc=Mock(return_value={'data':[{'name':'lacry','tools':{},'toolsError':'unreachable'}]})
    with pytest.raises(TeachingError,match='MCP tools are unavailable'):session.turn('instructions',[])
    assert session.rpc.call_args.args[0]=='mcpServerStatus/list'
