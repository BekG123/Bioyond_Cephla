"""Real model + production orchestrator/planner/Lua, exclusively fake hardware.

Does not import app.py or open robot/Squid connections. Outbound TCP is restricted
to Anthropic for the explicitly requested --live-model option.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import socket
import sys
import threading
import time
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'tests'))
from test_autonomous_squid import WorkflowTests


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--live-model',action='store_true')
    options=parser.parse_args()
    target=ROOT/'squid_bridge'/('proof_live_model.json' if options.live_model else 'proof_scripted_model.json')
    proof=dict(at=time.time(),real_model=options.live_model,physical_hardware=False,
        real_imaging=False,calibration_and_instruments='test doubles',
        production_components=['LacryAgent','ClassicPickup','AutonomousSquid','SquidExecution',
                               'LacryBackend station planner','Lua trajectory executor'],
        status='started',model_responses=[],user_messages=[],trace=[])
    fixture=WorkflowTests();fixture.setUp()
    timer=None
    original_connection=socket.create_connection
    def network(address,*args,**kwargs):
        if not options.live_model or address[0]!='api.anthropic.com' or address[1]!=443:
            raise RuntimeError('Proof harness blocks all robot/instrument network access.')
        return original_connection(address,*args,**kwargs)
    try:
        agent=fixture.agent;fake=fixture.fake
        fake.status=fake.poll
        fake.job_status=lambda ident=None:fake.poll()
        fixture.backend.squid=fake
        fixture.backend.instrument=NS(status=lambda:dict(available=False,message='Hamilton is not part of this proof.'))
        fixture.backend.state=lambda:dict(robot=fixture.travel.s.status(),hand={'state':'off'},
            camera={'open':True,'enabled':True},squid=fake.poll(),station='Home',teaching=False)
        if options.live_model:
            from plate_agent import VisionClient
            from credential_store import CredentialStore
            from imitation_agent import HaikuTools
            credentials=VisionClient(CredentialStore())
            if not credentials.ready():raise RuntimeError('Saved Haiku credentials unavailable.')
            client=HaikuTools(credentials);agent.credentials=credentials
            def complete(payload):
                response=client.complete(payload)
                proof['model_responses'].append(deepcopy(response))
                return response
            agent.client=NS(complete=complete)
        else:
            agent.credentials.model='scripted-fixture'
            agent.client.complete.side_effect=[
                dict(content=[dict(type='tool_use',id='all',name='plan_squid_experiment',input={})]),
                dict(content=[dict(type='text',text='The complete experiment is ready.')])]
        actual_tool=agent._run_tool
        def tool(name,args):
            proof['trace'].append(dict(at=time.time(),event='model_tool',name=name,arguments=args))
            return actual_tool(name,args)
        agent._run_tool=tool
        fake.finish=False
        def imaging_started():
            nonlocal timer
            proof['trace'].append(dict(at=time.time(),event='imaging_started'))
            def finished():
                proof['trace'].append(dict(at=time.time(),event='imaging_completed_signal'))
                fake.state.update(status='completed',completion_confirmed=True)
            timer=threading.Timer(.8,finished);timer.start()
        fake.on_start=imaging_started
        original_step=fixture.backend.execute_step
        def execute(run,step,plan):
            proof['trace'].append(dict(at=time.time(),event='robot_step',label=step['label']))
            return original_step(run,step,plan)
        fixture.backend.execute_step=execute
        with patch('socket.create_connection',network):
            request='Fully calibrate, leave the plate at Squid, image using its currently selected settings, wait at Home until imaging finishes, then retrieve the plate to Home.'
            proof['user_messages'].append(request);agent.send(request)
            assert agent.pending and agent.pending['dispatch']=='autonomous_squid', 'Model did not propose the complete requested experiment.'
            assert not fixture.travel.s.robot.calls, 'Unexpected execution before confirmation.'
            proof['planned_steps']=[s['label'] for s in agent.pending['steps']]
            proof['user_messages'].append('Yes');agent.send('Yes')
            final=fixture.finish()
            assert final['ok'],final
            assert agent.review is None,'Unexpected extra confirmation.'
            proof['workflow']=json.loads(fixture.workflow.active_record.read_text())
            proof['transcript']=deepcopy(agent.transcript)
            proof['result']=final
            proof['robot_queue_calls']=deepcopy(fixture.travel.s.robot.calls)
            proof['jaw_targets']=fixture.travel.s.grips
            signal=next(e['at'] for e in proof['trace'] if e['event']=='imaging_completed_signal')
            grip=next(e['at'] for e in proof['trace'] if e.get('label')=='Grip the plate at Squid')
            assert grip>signal,'Retrieval happened before imaging completion.'
            proof.update(status='passed',confirmation_count=1,additional_confirmations=0,
                         retrieved_after_imaging=True)
    except Exception as error:
        proof.update(status='failed',error=str(error),transcript=deepcopy(fixture.agent.transcript))
    finally:
        if timer:timer.join(2)
        fixture.doCleanups()
        target.write_text(json.dumps(proof,indent=2,allow_nan=False,default=str),encoding='utf-8')
    print(json.dumps({k:proof.get(k) for k in ('status','real_model','physical_hardware',
        'confirmation_count','additional_confirmations','retrieved_after_imaging','error')}))
    print('Evidence: '+str(target))
    return 0 if proof['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
