"""Trial dispatch refusal tests; no network or physical movement."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from execute_adapted_descent import validate_start, execute


class TrialTests(unittest.TestCase):
    def setUp(self):
        self.state=dict(sequence=dict(active=False),target=dict(x=318.5),
            envelope=dict(enabled=True),robot=dict(ok=True,connected=True,errors=[],enabled=True,
            control_mode=dict(mode='auto'),program_state=dict(state='running'),
            pose_mm=dict(X=318.5,Y=-69.6,Z=300.,Rz=92.4),
            joints=dict(J1=261.,J2=39.,J3=61.,J4=-8.),external_axes=dict(E1=.028)))
        self.review=dict(state=deepcopy(self.state),config=dict(limit=220),band=66)

    def check(self):validate_start(self.review,self.state,dict(limit=220),66)

    def test_unchanged_start_passes(self):self.check()

    def test_drift_in_any_pose_or_joint_rejected(self):
        for group in ('pose_mm','joints'):
            for key in self.state['robot'][group]:
                with self.subTest(group=group,key=key):
                    self.state['robot'][group][key]+=1
                    with self.assertRaises(RuntimeError):self.check()
                    self.state['robot'][group][key]-=1

    def test_fault_busy_or_disabled_rejected(self):
        for change in ({'errors':[10]},{'enabled':False},{'ok':False}):
            with self.subTest(change=change):
                self.state['robot'].update(change)
                with self.assertRaises(RuntimeError):self.check()
                self.state=deepcopy(self.review['state'])
        self.state['sequence']['active']=True
        with self.assertRaises(RuntimeError):self.check()

    def test_target_or_claw_change_rejected(self):
        self.state['target']['x']+=1
        with self.assertRaises(RuntimeError):self.check()
        self.state=deepcopy(self.review['state'])
        self.state['robot']['external_axes']['E1']=3.8
        with self.assertRaises(RuntimeError):self.check()

    def test_unconfirmed_trial_never_reads_or_dispatches(self):
        with patch('execute_adapted_descent.api') as api:
            with self.assertRaisesRegex(RuntimeError,'confirmation'):
                execute('missing.json',False)
            api.assert_not_called()


if __name__=='__main__':unittest.main()
