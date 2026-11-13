"""Sonnet migration: signed history, multimodal tools and fail-closed responses."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lacry_agent import LacryAgent
from lacry_model import DEFAULT_MODEL
from imitation_agent import HaikuTools
from plate_agent import VisionClient
from researcher_teaching import TeachingError
from sequences import Runner


class SonnetTests(unittest.TestCase):
    def make_agent(self, responses):
        runner=Runner()
        self.requests=[]
        def complete(payload):
            self.requests.append(deepcopy(payload))
            return deepcopy(responses.pop(0))
        client=Mock();client.complete.side_effect=complete
        credentials=SimpleNamespace(key='test-key',model=DEFAULT_MODEL,ready=lambda:True)
        with patch.dict(os.environ,{'LACRY_MODEL':DEFAULT_MODEL}):
            agent=LacryAgent(Mock(),credentials,lambda:runner,client=client)
        agent.public=Mock(return_value={'ok':True})
        agent._conversation_state=Mock(side_effect=lambda:{'changed':len(self.requests)})
        return agent,client

    def test_signed_history_is_append_only_across_tools_and_turns(self):
        thinking={'type':'thinking','thinking':'','signature':'signed-prefix'}
        tool={'type':'tool_use','id':'camera','name':'look_at_camera','input':{}}
        final={'type':'text','text':'Plate visible.'}
        agent,client=self.make_agent([
            {'stop_reason':'tool_use','content':[thinking,tool]},
            {'stop_reason':'end_turn','content':[thinking,final]},
            {'stop_reason':'end_turn','content':[{'type':'text','text':'Recorded.'}]}])
        image={'type':'image','source':{'type':'base64','media_type':'image/jpeg','data':'fixture'}}
        agent._run_tool=Mock(return_value=([image],False))
        agent.send('Look at the plate')
        saved=deepcopy(agent.history)
        agent.send('Describe its appearance')
        first,second,third=self.requests
        self.assertEqual(first['model'],DEFAULT_MODEL)
        self.assertNotIn('temperature',first)
        self.assertEqual(first['thinking'],{'type':'adaptive'})
        self.assertEqual(first['output_config'],{'effort':'medium'})
        self.assertEqual(first['max_tokens'],8192)
        self.assertEqual(first['system'],second['system'])
        self.assertEqual(second['system'],third['system'])
        self.assertEqual(second['messages'][:len(first['messages'])],first['messages'])
        self.assertEqual(third['messages'][:len(saved)],saved)
        self.assertEqual(second['messages'][1]['content'],[thinking,tool])
        self.assertEqual(second['messages'][2]['content'][0]['content'],[image])
        self.assertEqual(saved[-1]['content'],[thinking,final])
        agent.backend.execute_step.assert_not_called()

    def test_incomplete_or_refused_response_never_dispatches_partial_tool(self):
        for reason in ('max_tokens','refusal','model_context_window_exceeded','pause_turn'):
            with self.subTest(reason=reason):
                agent,client=self.make_agent([{'stop_reason':reason,'content':[
                    {'type':'tool_use','name':'propose_actions','id':'partial','input':{}}]}])
                agent._run_tool=Mock()
                with self.assertRaisesRegex(TeachingError,reason):agent.send('Plan a transfer')
                agent._run_tool.assert_not_called()
                self.assertIsNone(agent.pending)
                client.complete.assert_called_once()

    def test_shared_analysis_transport_converts_legacy_options_without_mutating_history(self):
        payload={'model':DEFAULT_MODEL,'temperature':0,'max_tokens':700,
                 'messages':[{'role':'user','content':'Describe this'}]}
        original=deepcopy(payload)
        reply=io.BytesIO(json.dumps({'content':[{'type':'text','text':'OK'}]}).encode())
        with patch('imitation_agent.urllib.request.urlopen',return_value=reply) as send:
            HaikuTools(SimpleNamespace(key='fake-key')).complete(payload)
        sent=json.loads(send.call_args.args[0].data)
        self.assertNotIn('temperature',sent)
        self.assertEqual(sent['max_tokens'],8192)
        self.assertEqual(send.call_args.kwargs['timeout'],60)
        self.assertEqual(payload,original)

    def test_shared_model_includes_existing_image_analysis(self):
        with patch.dict(os.environ,{'LACRY_MODEL':DEFAULT_MODEL,'BIOYOND_AGENT_MODEL':'old-haiku'}):
            self.assertEqual(VisionClient().model,DEFAULT_MODEL)

    def test_image_description_accepts_thinking_but_only_returns_text(self):
        import numpy as np
        client=VisionClient();client.key='fixture-key'
        reply={'stop_reason':'end_turn','content':[
            {'type':'thinking','thinking':'','signature':'keep-private'},
            {'type':'text','text':'Two circles.'}]}
        with patch('plate_agent.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(reply).encode())) as send:
            frame=np.zeros((64,64,3),dtype=np.uint8)
            result=client.describe(frame,frame,{'instruction':'Describe the image'})
        payload=json.loads(send.call_args.args[0].data)
        self.assertEqual(payload['model'],DEFAULT_MODEL)
        self.assertNotIn('temperature',payload)
        self.assertEqual(result['summary'],'Two circles.')
        self.assertNotIn('keep-private',json.dumps(result))


if __name__=='__main__':unittest.main()
