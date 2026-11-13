"""Only the exact reviewed pre-dispatch record can clear its history block."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from home_attempts import known_reviewed_no_travel

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.record=json.loads((Path(__file__).resolve().parents[1]/'reports/ik_home/1793520304775515000_e3f80f2bfd534420a1ca3e75a82fa4ec.json').read_bytes())
    def test_exact_review_only(self):
        self.assertTrue(known_reviewed_no_travel(self.record))
        for key,value in [('status','completed'),('at',0),('sequence',{}),('plan',{})]:
            changed=deepcopy(self.record);changed[key]=value
            self.assertFalse(known_reviewed_no_travel(changed))
    def test_arbitrary_failure_is_not_proof(self):
        for record in (None,{},dict(status='failed_or_stopped'),dict(value=float('nan'))):
            self.assertFalse(known_reviewed_no_travel(record))

if __name__=='__main__':unittest.main()
