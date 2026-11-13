"""Live Sonnet chat, vision and planning check with no hardware access.

Run with --live to use the saved API key. Tools and telemetry are test doubles;
all outbound connections except Anthropic HTTPS are blocked.
"""
import argparse
import base64
from copy import deepcopy
import json
from pathlib import Path
import socket
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from credential_store import CredentialStore
from imitation_agent import HaikuTools
from lacry_agent import LacryAgent
from lacry_decision_log import evidence
from plate_agent import VisionClient
from sequences import Runner


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='Send test messages/images to Anthropic; never hardware.')
    args=parser.parse_args()
    if not args.live:
        parser.print_help();return
    report=dict(physical_hardware=False,synthetic_image=True,status='started',responses=[],tools=[])
    credentials=VisionClient(CredentialStore())
    client=HaikuTools(credentials)
    def complete(payload):
        result=client.complete(payload)
        report['responses'].append(dict(model=result.get('model'),stop_reason=result.get('stop_reason'),
                                        usage=result.get('usage'),content=evidence(result.get('content'))))
        return result
    runner=Runner()
    agent=LacryAgent(Mock(),credentials,lambda:runner,client=SimpleNamespace(complete=complete))
    agent.public=Mock(return_value={'ok':True})
    agent._conversation_state=lambda:dict(offline_test=True,hardware_connected=False,pending=agent.pending)
    frame=np.full((200,300,3),255,np.uint8)
    cv2.circle(frame,(75,100),45,(0,0,0),-1)
    cv2.circle(frame,(225,100),20,(0,0,0),-1)
    ok,encoded=cv2.imencode('.png',frame)
    assert ok
    image=dict(type='image',source=dict(type='base64',media_type='image/png',
                                      data=base64.b64encode(encoded).decode()))
    def tool(name,arguments):
        report['tools'].append(dict(name=name,arguments=deepcopy(arguments)))
        if name=='look_at_camera':return [image,dict(type='text',text='Synthetic offline fixture, not lab telemetry.')],False
        if name=='get_lab_status':return json.dumps({'offline_test':True,'hardware_connected':False}),False
        if name=='plan_hamilton':
            agent.pending=dict(id='offline-preview',at=time.time(),dispatch='hamilton',
                steps=[dict(label='Hamilton calibration (test double)')],
                requirements=['Offline fixture; no executable hardware connection.'])
            return json.dumps({'ok':True,'plan':agent.pending,'preview_only':True}),False
        raise AssertionError('Unexpected tool in isolated model check: '+name)
    agent._run_tool=tool
    original=socket.create_connection
    def network(address,*a,**kw):
        if address != ('api.anthropic.com',443):
            raise RuntimeError('Hardware/network access blocked in model check.')
        return original(address,*a,**kw)
    output=Path(__file__).parent/'reports'/'model_checks'/('sonnet_'+str(time.time_ns())+'.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    try:
        with patch('socket.create_connection',network):
            agent.send('Use look_at_camera to inspect the synthetic test image. Describe the shapes and which is larger. Do not propose or execute movement.')
            assert any(t['name']=='look_at_camera' for t in report['tools'])
            assert agent.pending is None
            agent.send('Without taking another image, which side had the larger shape? Reply briefly; no movement.')
            agent.send('Preview Hamilton full calibration using plan_hamilton. This is an offline tool-planning check only. Do not start anything.')
            assert agent.pending and agent.pending['id']=='offline-preview'
            assert any(t['name']=='plan_hamilton' for t in report['tools'])
            agent.backend.execute_step.assert_not_called()
            assert not runner.active
        report.update(status='passed',model=agent.model,transcript=agent.transcript,
                      hardware_commands_sent=0,preview_only=True)
    except Exception as error:
        report.update(status='failed',error=str(error));raise
    finally:
        output.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(dict(status=report['status'],record=str(output),physical_hardware=False)))


if __name__=='__main__':main()
