import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import run_record_io
from squid_bridge import state_io


class RunRecordTests(TestCase):
    def test_invalid_feedback_remains_evidence_without_mutating_live_state(self):
        record={'samples':[{'E1':float('nan'),'E2':float('inf')}],'status':'stopped'}
        with TemporaryDirectory() as folder:
            path=Path(folder)/'run.json';run_record_io.write_run_record(path,record)
            saved=json.loads(path.read_bytes())
        self.assertEqual(saved['samples'][0]['E1'],{'invalid_numeric_feedback':'nan'})
        self.assertEqual(saved['samples'][0]['E2'],{'invalid_numeric_feedback':'inf'})
        self.assertTrue(math.isnan(record['samples'][0]['E1']))

    def test_transient_windows_error_retries_only_same_record(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'run.json';error=PermissionError('locked');error.winerror=5
            replace=state_io.replace_file;attempts=[]
            def locked_once(source,target):
                attempts.append(Path(source).read_bytes())
                if len(attempts)==1:raise error
                replace(source,target)
            with patch.object(state_io,'replace_file',side_effect=locked_once),patch.object(state_io.time,'sleep'):
                run_record_io.write_run_record(path,{'completed_cycles':1})
            self.assertEqual(attempts[0],attempts[1]);self.assertEqual(len(attempts),2)
            self.assertEqual(json.loads(path.read_bytes()),{'completed_cycles':1})
