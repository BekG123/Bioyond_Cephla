import copy
import json
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import holder_rotation_trial as h


def evidence():
    return dict(robot=dict(ok=True, connected=True, errors=[], enabled=True,
        control_mode={'mode':'auto'}, program_state={'state':'running'},
        pose_mm=dict(h.HOME)), native=dict(moving=False,error=False,emergency=False,
        drag=False,manual=False,external_units={'E2':'degrees'},external_axes={'E1':0.,'E2':1.}))


class Guards(unittest.TestCase):
    def test_readback_verification_is_bound_to_the_failed_attempt(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(h,'ROOT',Path(folder)):
            raw=json.dumps(dict(status='failed_or_uncertain',target_degrees=1.675)).encode()
            (Path(folder)/'return_original.json').write_bytes(raw)
            v=dict(status='original_restored_by_readback',result={'ok':True},
                original_attempt_sha256=hashlib.sha256(raw).hexdigest(),target_degrees=1.675,motion_resent=False)
            p=Path(folder)/'return_original_verified.json'
            p.write_text(json.dumps(v))
            self.assertEqual(h.verified_return()[1],v)
            (Path(folder)/'return_original.json').write_bytes(raw+b' ')
            with self.assertRaises(ValueError):h.verified_return()

    def test_quarter_turn_is_total_ninety_not_ninety_more(self):
        probe=dict(status='completed_awaiting_direction',result={'ok':True},
            origin_degrees=1.675,target_degrees=6.675,
            after={'native':{'external_axes':{'E2':6.682}}})
        expected,target=h.quarter_turn_target(probe,True)
        self.assertAlmostEqual(target,91.675)
        self.assertAlmostEqual(target-expected,84.993)
        with self.assertRaises(ValueError):h.quarter_turn_target(probe,False)
        probe['after']['native']['external_axes']['E2']=8
        with self.assertRaises(ValueError):h.quarter_turn_target(probe,True)

    def test_non_home_disabled_and_hand_guiding_refused(self):
        for mutation in ('home','disabled','drag','nan'):
            s=evidence()
            if mutation=='home':s['robot']['pose_mm']['Z']-=10
            if mutation=='disabled':s['robot']['enabled']=False
            if mutation=='drag':s['native']['drag']=True
            if mutation=='nan':s['native']['external_axes']['E2']=float('nan')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                h.check_snapshot(s['robot'],s['native'])

    def test_stale_published_program_cannot_move_and_receipt_blocks_retry(self):
        class Run:
            def stopped(self):return False
        class Service:
            calls=[]
            def __init__(self):self.robot=self
            def _locked(self,fn):return fn()
            def _hostpoint(self,params,mode,timeout):
                self.calls.append(mode)
                return {'ok':True}
            def get_sys_var_i(self,indices):return {7:0,8:250101}
        service=Service()
        with tempfile.TemporaryDirectory() as folder, patch.object(h,'ROOT',Path(folder)), patch.object(h,'snapshot',return_value=evidence()):
            with self.assertRaisesRegex(ValueError,'not verified'):
                h.direction_probe(Run(),service)
            self.assertEqual(service.calls,[9])
            with self.assertRaisesRegex(ValueError,'already attempted'):
                h.direction_probe(Run(),service)
            self.assertEqual(service.calls,[9])


if __name__=='__main__':unittest.main()
