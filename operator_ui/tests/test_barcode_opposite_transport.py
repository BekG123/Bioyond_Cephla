import tempfile,time,json
from pathlib import Path
from unittest.mock import patch,Mock
import unittest
import barcode_opposite_transport as m
from autonomy import TransferError

class TransportTests(unittest.TestCase):
    def test_recent_phase_can_reference_old_lift_but_stale_current_phase_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);folder=root/('a'*32);folder.mkdir()
            trial=folder/'run.json';trial.write_text('{}')
            seat=dict(X=313,Y=-66,Z=75.72,Rz=90);proof=dict(seat,Z=80.72)
            g=dict(seat=seat,clearance=dict(seat,Z=105.72),station_clearance=dict(seat,Z=105.72),cfg={})
            pickup=folder/'pickup.json'
            pickup.write_text(json.dumps(dict(status='proof_lift_completed_retention_pending',source=str(trial),
                source_sha256=m.sha(trial),geometry=g,finished_at=time.time()-3600,holder_target=181.77,
                grip_target=3.9,lift_speed=5,final={'robot':{'pose_mm':proof}})))
            with patch.object(m,'OUTPUT',root),patch.object(m,'source_data',return_value=(trial,{},g)):
                with self.assertRaisesRegex(TransferError,'expired'):m.binding(pickup,'scanner')
                historical=m.binding(pickup,'scanner',require_fresh=False)
                scanner=folder/'scanner.json'
                receipt=dict(status='at_scanner_held',plan={'binding':historical},envelope_restoration={'ok':True},finished_at=time.time())
                scanner.write_text(json.dumps(receipt))
                self.assertEqual(m.binding(pickup,'return_home')['phase'],'return_home')
                receipt['finished_at']=time.time()-3600;scanner.write_text(json.dumps(receipt))
                with self.assertRaisesRegex(TransferError,'expired'):m.binding(pickup,'return_home')

    def test_lower_target_roundtrip_preserves_legacy_binding_and_return_origin(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);folder=root/('a'*32);folder.mkdir()
            trial=folder/'run.json';trial.write_text('{}')
            seat=dict(X=313,Y=-66,Z=75.72,Rz=90);proof=dict(seat,Z=80.72)
            g=dict(seat=seat,clearance=dict(seat,Z=105.72),station_clearance=dict(seat,Z=105.72),cfg={})
            pickup=folder/'pickup.json'
            pickup.write_text(json.dumps(dict(status='proof_lift_completed_retention_pending',source=str(trial),
                source_sha256=m.sha(trial),geometry=g,finished_at=time.time(),holder_target=1.77,
                grip_target=3.9,lift_speed=5,final={'robot':{'pose_mm':proof}})))
            with patch.object(m,'OUTPUT',root),patch.object(m,'source_data',return_value=(trial,{},g)):
                legacy=m.binding(pickup,'scanner');self.assertNotIn('scanner_target',legacy)
                low=m.binding(pickup,'scanner',scanner_z=163.76)
                self.assertEqual(low['points'][-1],dict(m.TARGET,Z=163.76))
                self.assertEqual(low['points'][:-1],legacy['points'][:-1])
                receipt=dict(status='at_scanner_held',plan={'binding':low},envelope_restoration={'ok':True},finished_at=time.time())
                (folder/'scanner.json').write_text(json.dumps(receipt))
                back=m.binding(pickup,'return_home')
                self.assertEqual(back['start'],dict(m.TARGET,Z=163.76))
                self.assertEqual(back['points'][0],dict(m.TARGET,Z=300))
                for invalid in (0,160,200,float('nan')):
                    with self.assertRaises(Exception):m.binding(pickup,'scanner',scanner_z=invalid)
                with self.assertRaises(Exception):m.binding(pickup,'return_home',scanner_z=163.76)
                self.assertEqual(m.binding(pickup,'scanner'),legacy)

    def test_failed_scanner_queue_stops_and_restores_workspace_without_retry(self):
        with tempfile.TemporaryDirectory() as td:
            pose=dict(X=313,Y=-66,Z=80.72,Rz=90)
            g=dict(source=str(Path(td)/'pickup.json'),phase='scanner',start=pose,points=[pose],cfg={})
            p=dict(at=time.time(),binding=g,start=pose,joints=dict(J1=0,J2=0,J3=0,J4=0),implementation={})
            s=Mock();s.set_envelope.return_value={'ok':True};s.program.return_value={'ok':True}
            run=Mock();run.stopped.return_value=False
            with patch.object(m,'plan',return_value=p),patch.object(m,'preflight',return_value=dict(pose_mm=pose)),\
                 patch.object(m,'native',return_value=dict(external_axes={'E1':3.9,'E2':181.77})),\
                 patch.object(m,'LuaTrajectory') as lua:
                lua.return_value.execute.return_value=dict(ok=False,error='timeout')
                with self.assertRaisesRegex(TransferError,'no retry'):m.execute(run,s,{},p)
            lua.return_value.execute.assert_called_once();s.program.assert_called_once_with('stop')
            self.assertEqual(s.set_envelope.call_count,2)
            self.assertEqual(s.set_envelope.call_args.args,(200.,450.,-250.,380.,70.,400.))
            self.assertEqual(json.loads((Path(td)/'scanner.json').read_text())['status'],'stopped_or_uncertain')

    def test_changed_binding_refused_before_motion(self):
        p=dict(at=time.time(),binding=dict(source='source',phase='scanner'),implementation={})
        s=Mock()
        with patch.object(m,'plan',return_value=dict(binding={},implementation={})):
            with self.assertRaisesRegex(TransferError,'Transport changed'):m.execute(Mock(),s,{},p)
        s.set_envelope.assert_not_called()

    def test_generic_service_cannot_use_scanner_corridor(self):
        with self.assertRaisesRegex(TransferError,'Bound opposite-side'):
            m.prepare_for_service(Mock(),{},{},[],{},m.TRIAL)

if __name__=='__main__':unittest.main()
