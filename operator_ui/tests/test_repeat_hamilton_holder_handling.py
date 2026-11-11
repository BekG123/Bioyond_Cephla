import contextlib
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
from unittest import TestCase, main
from unittest.mock import patch
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import repeat_hamilton_holder_handling as runner


class BatchTests(TestCase):
    def execute_fake(self,fail_at=None):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);calls=[];seq={'active':False}
            def api(path,body=None):
                nonlocal seq
                if path=='state':return {'robot':dict(connected=True,enabled=True,errors=[],program_state={'state':'running'},control_mode={'mode':'auto'})}
                if path=='seq':return seq
                if path.endswith('/preview'):return {'plan':dict(id=uuid4().hex,**body)}
                if path.endswith('/start'):
                    p=body['plan'];calls.append(p['phase'])
                    if len(calls)==fail_at:
                        seq=dict(active=False,name='hamilton_holder_dropoff',result={'ok':False,'error':'test fault'})
                    else:
                        receipt=root/(p['id']+'.json')
                        receipt.write_text(json.dumps(dict(status=runner.STATUSES[p['phase']],at=time.time())))
                        seq=dict(active=False,name='hamilton_holder_dropoff',result=dict(ok=True,record=str(receipt)))
                    return {'started':'hamilton_holder_dropoff'}
                raise AssertionError(path)
            with patch.object(runner,'FOLDER',root),patch.object(runner,'api',side_effect=api),contextlib.redirect_stdout(io.StringIO()):
                if fail_at:
                    with self.assertRaisesRegex(RuntimeError,'test fault'):runner.batch(root/'source.json',5)
                else:runner.batch(root/'source.json',5)
            record=json.loads(next(root.glob('batch_*/run.json')).read_bytes())
            return calls,record

    def test_five_cycles_chain_all_25_phases(self):
        calls,r=self.execute_fake()
        self.assertEqual(calls,list(runner.PHASES)*5)
        self.assertEqual(r['completed_cycles'],5)
        self.assertEqual(r['status'],'controller_completed_pending_operator_observation')

    def test_failed_phase_stops_without_retry_or_next_cycle(self):
        calls,r=self.execute_fake(12)
        self.assertEqual(len(calls),12);self.assertEqual(r['completed_cycles'],2)
        self.assertEqual(r['status'],'stopped_or_uncertain')


if __name__=='__main__':main()
