import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import station_handling_five_20261110 as batch

class BatchTests(unittest.TestCase):
    def run_fake(self,fail=False):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'batch';hp=batch.h.hamilton.reference()
            initial={'robot':{'connected':True,'pose_mm':hp['routes']['reverse'][0]}}
            final={'robot':{'connected':True,'pose_mm':hp['routes']['forward'][0]}}
            with patch.object(batch,'ROOT',root),patch.object(sys,'argv',['test','--count','5','--execute']),\
                 patch.object(batch,'api',return_value=initial) as api,\
                 patch.object(batch.checks,'ready',side_effect=[initial]+[final]*5),\
                 patch.object(batch.h,'hamilton_idle'),patch.object(batch.h,'travel_hamilton') as travel,\
                 patch.object(batch,'invoke') as invoke,patch.object(batch,'handling') as handling:
                if fail:handling.side_effect=RuntimeError('test fault')
                if fail:
                    with self.assertRaisesRegex(RuntimeError,'test fault'):batch.main()
                else:batch.main()
                record=json.loads((root/'cycles_1_5/run.json').read_bytes())
                return record,travel.call_count,invoke.call_count,[c.args[0] for c in handling.call_args_list],api.call_args_list

    def test_five_exact_handling_cycles(self):
        record,travel,invoke,actions,_=self.run_fake()
        self.assertEqual(record['completed_cycles'],[1,2,3,4,5])
        self.assertEqual(travel,9);self.assertEqual(invoke,15)
        self.assertEqual(actions,['release','pickup']*5)

    def test_first_failure_stops_without_next_phase_or_retry(self):
        record,travel,invoke,actions,calls=self.run_fake(True)
        self.assertEqual(record['completed_cycles'],[])
        self.assertEqual(record['status'],'stopped_or_failed')
        self.assertEqual((travel,invoke),(0,0));self.assertEqual(actions,['release'])
        self.assertEqual(calls[-1].args,('program',{'action':'stop'}))

if __name__=='__main__':unittest.main()
