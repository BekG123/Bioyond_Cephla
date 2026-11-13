import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import run_hotel_slot1_workflow as w

class WorkflowTests(unittest.TestCase):
    def test_preview_has_no_hardware_calls(self):
        with patch.object(w,'api') as api,patch.object(w,'reconnect') as reconnect,patch.object(w,'dispatch') as dispatch,patch('builtins.print'):
            w.main(['--action','roundtrip'])
        api.assert_not_called();reconnect.assert_not_called();dispatch.assert_not_called()

    def test_current_accepted_evidence_and_endpoints_match(self):
        manifest,plans=w.load_workflow()
        self.assertEqual(manifest['slot'],1)
        self.assertEqual(plans['deliver']['routes']['deliver']['points'][-1],plans['retrieve']['routes']['approach']['points'][-1])
        self.assertEqual(plans['retrieve']['routes']['lift']['speeds'],[5])

    def test_modified_acceptance_binding_refused(self):
        data=json.loads(w.WORKFLOW.read_bytes());data['acceptance_sha256']='wrong'
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'workflow.json';p.write_text(json.dumps(data))
            with patch.object(w,'WORKFLOW',p):
                with self.assertRaisesRegex(RuntimeError,'Acceptance evidence changed'):w.load_workflow()

    def test_higher_slot_not_routed_to_slot1(self):
        data=json.loads(w.WORKFLOW.read_bytes());data['slot']=2
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'workflow.json';p.write_text(json.dumps(data))
            with patch.object(w,'WORKFLOW',p):
                with self.assertRaisesRegex(RuntimeError,'Accepted slot1'):w.load_workflow()

if __name__=='__main__':unittest.main()
