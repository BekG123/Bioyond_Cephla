import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import short_side_holder_restore as m

class RestoreTests(unittest.TestCase):
    def run_trial(self,bad_version=False,bad_arrival=False):
        s=Mock();s._locked=lambda f:f()
        s.program.return_value={'ok':True}
        s._hostpoint.return_value={'ok':True}
        def regs(keys):
            token=s._hostpoint.call_args.args[0][7]
            return {7:int(token),8:0 if bad_version else 250102}
        s.robot.get_sys_var_i.side_effect=regs
        snap={'robot':{'joints':dict(J1=1,J2=2,J3=3,J4=4)},'native':{'external_axes':{'E1':0,'E2':90.31}}}
        approved=dict(start=89.97,target=90.31,before=snap)
        with tempfile.TemporaryDirectory() as folder,patch.object(m,'PATH',Path(folder)/'trial.json'),patch.object(m,'review',return_value=approved),patch.object(m,'snapshot') as snapshot:
            approved.update(profile='original',path=str(m.PATH))
            snapshot.side_effect=[snap,ValueError('arrival mismatch') if bad_arrival else snap]
            if bad_version or bad_arrival:
                with self.assertRaises(ValueError):m.execute(SimpleNamespace(stopped=lambda:False),s,approved)
            else:
                self.assertTrue(m.execute(SimpleNamespace(stopped=lambda:False),s,approved)['ok'])
            record=json.loads(m.PATH.read_text())
            if bad_version:
                self.assertEqual(s._hostpoint.call_count,1);s.program.assert_not_called()
            elif bad_arrival:s.program.assert_called_once_with('stop')
            else:
                self.assertEqual(s._hostpoint.call_count,2)
                command,mode,timeout=s._hostpoint.call_args.args
                self.assertEqual((mode,command[8],command[9]),(10,89.97,90.31))
                self.assertEqual(record['status'],'completed')
    def test_one_small_slow_move(self):self.run_trial()
    def test_wrong_interface_sends_no_motion(self):self.run_trial(bad_version=True)
    def test_failed_arrival_stops_without_retry(self):self.run_trial(bad_arrival=True)
    def test_revision02_restores_accepted_angle_and_keeps_half_degree_bound(self):
        service=Mock();service._endpoint_addr.return_value=('fake',0)
        with tempfile.TemporaryDirectory() as folder,patch.object(m,'FOLDER',Path(folder)),patch.object(m,'snapshot',return_value={}),patch('draggo.DragGoRPC') as rpc:
            rpc.return_value.info.return_value={'external_axes':{'E2':90.829}}
            result=m.review(service,'full_sequence02')
            self.assertAlmostEqual(result['target'],90.71661229181757)
            self.assertEqual(Path(result['path']).name,'full_sequence02_holder_restore.json')
            rpc.return_value.info.return_value={'external_axes':{'E2':91.3}}
            with self.assertRaises(ValueError):m.review(service,'full_sequence02')

if __name__=='__main__':unittest.main()
