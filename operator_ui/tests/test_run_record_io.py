import json
import math
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import run_record_io
from squid_bridge import state_io
import pytest


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


@pytest.mark.parametrize('persistent',[False,True])
def test_1175_preserves_old_record_and_retries_identical_candidate(tmp_path,persistent):
    path=tmp_path/'run.json';path.write_text('{"status":"approved"}')
    replace=state_io.replace_file;attempts=[]
    error=OSError('Unable to remove the file to be replaced');error.winerror=1175
    def locked(source,target):
        attempts.append((str(source),Path(source).read_bytes()))
        assert json.loads(path.read_bytes())=={'status':'approved'}
        if persistent or len(attempts)<3:raise error
        replace(source,target)
    with patch.object(state_io,'replace_file',side_effect=locked),patch.object(state_io.time,'sleep') as sleep:
        if persistent:
            with pytest.raises(OSError) as failure:run_record_io.write_run_record(path,{'status':'dispatching'})
            assert failure.value.winerror==1175
        else:run_record_io.write_run_record(path,{'status':'dispatching'})
    assert len(attempts)==(7 if persistent else 3)
    assert len(set(attempts))==1
    assert sum(c.args[0] for c in sleep.call_args_list)<=.701
    assert json.loads(path.read_bytes())['status']==('approved' if persistent else 'dispatching')
    assert not list(tmp_path.glob('.run-*.tmp'))


@pytest.mark.parametrize('code',[1176,1177,112])
def test_partial_rename_or_disk_failure_never_retries(tmp_path,code):
    path=tmp_path/'run.json';path.write_text('{}')
    error=OSError('non-retryable file failure');error.winerror=code
    with patch.object(state_io,'replace_file',side_effect=error) as replace,patch.object(state_io.time,'sleep') as sleep:
        with pytest.raises(OSError):run_record_io.write_run_record(path,{'status':'dispatching'})
    assert replace.call_count==1
    sleep.assert_not_called()
