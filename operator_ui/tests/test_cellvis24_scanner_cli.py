import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import run_cellvis24_scanner as cli
import cellvis24_scanner_pickup as pickup


class ScannerCliTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.ident='a'*32
        self.source=self.root/self.ident/'run.json';self.source.parent.mkdir()
        self.source.write_text('{}')
        for mod,name,value in ((cli,'REPORTS',self.root/'summaries'),(cli,'trial_source',lambda ident:self.source)):
            p=patch.object(mod,name,value);p.start();self.addCleanup(p.stop)
        p=patch('sys.stdout',new_callable=io.StringIO);p.start();self.addCleanup(p.stop)

    def test_preview_never_connects_or_moves(self):
        with patch.object(cli,'api',side_effect=AssertionError('No network')),patch.object(cli,'calibrate') as cal:
            cli.main(['--full-calibration']);cal.assert_not_called()

    def test_full_run_orders_stages_without_reseating_or_idle_after_pickup(self):
        events=[]
        def receipt(label):
            events.append(label);p=self.root/(label+'.json');p.write_text('{}');return p
        def calibration(args):
            self.assertEqual(args,['--projected-calibration-trial','--execute']);events.append('calibration')
            return dict(status='awaiting_open_claw_inspection',record=str(self.source))
        with (patch.object(cli,'calibrate',side_effect=calibration),patch.object(cli,'confirm',side_effect=lambda msg:events.append('inspection')),
             patch.object(cli,'grip_trial',side_effect=lambda ident,execute:receipt('grip')),
             patch.object(cli,'proof_lift',side_effect=lambda ident:receipt('lift')),
             patch.object(cli,'scanner_transfer',side_effect=lambda ident:dict(record=str(receipt('scanner'))))):
            result=cli.main(['--full-calibration','--execute'])
        self.assertEqual(events,['calibration','inspection','grip','lift','inspection','scanner'])
        self.assertEqual(result['status'],'completed_operator_retention_pending')
        self.assertEqual(len(result['steps']),4)

    def test_declined_alignment_never_grips(self):
        with patch.object(cli,'confirm',side_effect=RuntimeError('Operator stopped')),patch.object(cli,'grip_trial') as grip:
            with self.assertRaisesRegex(RuntimeError,'Operator stopped'):cli.main(['--trial-id',self.ident,'--execute'])
            grip.assert_not_called()
        self.assertEqual(json.loads(next((self.root/'summaries').glob('*.json')).read_text())['status'],'stopped_or_uncertain')

    def test_failed_grip_never_lifts_or_transfers(self):
        with (patch.object(cli,'confirm'),patch.object(cli,'grip_trial',side_effect=RuntimeError('Fault')),
             patch.object(cli,'proof_lift') as lift,patch.object(cli,'scanner_transfer') as transfer):
            with self.assertRaisesRegex(RuntimeError,'Fault'):cli.main(['--trial-id',self.ident,'--execute'])
            lift.assert_not_called();transfer.assert_not_called()

    def test_lost_scanner_ack_stops_once_never_resends(self):
        calls=[]
        def api(path,body=None):
            calls.append(path)
            if path=='state':return dict(robot=dict(connected=True))
            if path.endswith('/preview'):return dict(plan={})
            if path.endswith('/start'):raise TimeoutError('Lost ACK')
            return dict(ok=True)
        with patch.object(cli,'api',side_effect=api):
            with self.assertRaises(TimeoutError):cli.scanner_transfer(self.ident)
        self.assertEqual(calls,['state','developer/api/cellvis-scanner/preview','developer/api/cellvis-scanner/start','seq/stop'])

    def test_explicit_rejection_does_not_stop_another_owner(self):
        calls=[]
        def api(path,body=None):
            calls.append(path)
            if path=='state':return dict(robot=dict(connected=True))
            if path.endswith('/preview'):return dict(plan={})
            raise cli.ApiRejected('Busy')
        with patch.object(cli,'api',side_effect=api):
            with self.assertRaises(cli.ApiRejected):cli.scanner_transfer(self.ident)
        self.assertNotIn('seq/stop',calls)

    def test_invalid_trial_id_and_conflicting_modes(self):
        with contextlib.redirect_stderr(io.StringIO()),patch.object(cli,'trial_source',pickup.trial_source):
            for argv in (['--trial-id','../x'],['--full-calibration','--trial-id',self.ident],[]):
                with self.assertRaises(SystemExit):cli.parse_args(argv)


class ReceiptPickupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.ident='a'*32
        self.folder=self.root/self.ident;self.folder.mkdir()
        self.pose=dict(X=312.8,Y=-65.98,Z=75.72,Rz=90.12)
        self.trial=dict(status='awaiting_open_claw_inspection',payload='empty',steps=[dict(status='completed')],
            final=dict(pose_mm=self.pose),finished_at=time.time(),resolved_calibration=dict(solution=dict(
                plate_id='cellvis_p24_1_5h_n',grip_e1_mm=3.9,endpoint=self.pose)))
        p=patch.object(pickup,'RUNS',self.root);p.start();self.addCleanup(p.stop)
        p=patch('sys.stdout',new_callable=io.StringIO);p.start();self.addCleanup(p.stop)

    def save(self): (self.folder/'run.json').write_text(json.dumps(self.trial))

    def test_stale_or_wrong_plate_blocks_before_network(self):
        with patch.object(pickup,'api',side_effect=AssertionError('No hardware')):
            self.trial['finished_at']=time.time()-1900;self.save()
            with self.assertRaisesRegex(RuntimeError,'stale'):pickup.grip_trial(self.ident,True)
            self.trial['finished_at']=time.time();self.trial['resolved_calibration']['solution']['plate_id']='falcon48';self.save()
            with self.assertRaisesRegex(RuntimeError,'changed'):pickup.grip_trial(self.ident,True)

    def test_grip_and_proof_receipts_chain_and_preserve_speeds(self):
        self.save();pose=dict(self.pose);axes=dict(E1=28.,E2=1.77);moves=[]
        def state():
            return dict(robot=dict(connected=True,enabled=True,errors=[],control_mode=dict(mode='auto'),
                program_state=dict(state='running'),lua_app_initialized=True,pose_mm=dict(pose),joints={},external_axes=dict(axes)),
                sequence=dict(active=False),envelope=dict(enabled=True,**{k:dict(min=0,max=450) for k in ('X','Y','Z')}))
        def native():return dict(moving=False,error=False,emergency=False,drag=False,manual=False,external_axes=dict(axes))
        def api(path,body=None):
            if path=='state':return state()
            if path=='researcher/api/lacry/state':return dict(running=dict(active=False),pending=None)
            if path=='robot_params':return {}
            if path=='gripper':
                if body['action']=='move':axes['E1']=body['e1'];moves.append(('grip',body['e1'],body['speed']))
                return dict(ok=True,telemetry_live=True,e1_position=axes['E1'],e1_torque=-100)
            if path=='move':
                pose.update(X=body['x'],Y=body['y'],Z=body['z'],Rz=body['rz']);moves.append(('lift',body['z'],body['speed']))
                return dict(ok=True)
            raise AssertionError(path)
        with (patch.object(pickup,'api',side_effect=api),patch.object(pickup,'DragGoRPC') as rpc,
             patch.object(pickup.time,'sleep'),patch.object(pickup,'check_path',return_value={})):
            rpc.return_value.info.side_effect=native
            grip=pickup.grip_trial(self.ident,True);lift=pickup.proof_lift(self.ident)
        self.assertEqual(moves,[('grip',4.9,10),('grip',3.9,5),('lift',80.72,5)])
        self.assertEqual(json.loads(lift.read_text())['source_sha256'],pickup.hashlib.sha256(grip.read_bytes()).hexdigest())
        self.assertEqual(axes['E1'],3.9)
        with patch.object(pickup,'api',side_effect=AssertionError('No resend')):
            with self.assertRaises(FileExistsError):pickup.grip_trial(self.ident,True)


if __name__=='__main__':unittest.main()
