import tempfile,json
from pathlib import Path
from unittest.mock import Mock,patch
import unittest
import retry_dna_registration as m

class RetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'session_summary.json'
        self.path.write_text(json.dumps(dict(status='both_sides_no_read_plate_released_HOME_holder_restored',
            registration_complete=False,scan_triggers_per_side=5,sources={})))
        self.path.with_name('registration.json').write_text(json.dumps(dict(status='no_read',max_triggers=5)))
        self.live=Mock()
        self.live.original_scanner.return_value=('original',{})
        self.live.original_home.return_value=('original_release',{})
        self.live.opposite_scanner.return_value=('opposite',{})
        self.live.opposite_home.return_value=('opposite_release',{})
        self.live.stations.return_value={}

    def test_two_sides_no_read_stops_at_pass_limit(self):
        scan=Mock(return_value=dict(status='no_read',triggers=5))
        r=m.run_second_pass(self.path,self.live,scan)
        self.assertEqual(scan.call_count,2);self.live.stations.assert_not_called()
        self.assertEqual(r['status'],'two_pass_limit_reached_no_barcode_plate_released_HOME')
        with self.assertRaises(FileExistsError):m.run_second_pass(self.path,self.live,scan)
        self.assertEqual(scan.call_count,2)

    def test_first_decode_skips_opposite_and_gates_stations(self):
        r=m.run_second_pass(self.path,self.live,Mock(return_value=dict(status='registered',plate_id='unit-test')))
        self.live.opposite_scanner.assert_not_called()
        self.live.stations.assert_called_once_with('original_release','unit-test')
        self.assertTrue(r['registration_complete'])

    def test_scan_transport_fault_no_retry_or_next_motion(self):
        scan=Mock(side_effect=RuntimeError('scanner timeout'))
        with self.assertRaisesRegex(RuntimeError,'timeout'):m.run_second_pass(self.path,self.live,scan)
        scan.assert_called_once();self.live.original_home.assert_not_called()
        self.live.opposite_scanner.assert_not_called();self.live.stations.assert_not_called()

    def test_live_retry_uses_accepted_pickup_without_calibration(self):
        source=Path('accepted_release.json')
        live=m.Live()
        with patch('run_cellvis24_scanner.main',side_effect=AssertionError('Must not recalibrate')),\
             patch('run_cellvis24_workflow.main',side_effect=AssertionError('Must not recalibrate')),\
             patch('run_cellvis24_scanner_hamilton.reconnect'),\
             patch('run_cellvis24_scanner_hamilton.api',return_value={'plan':{'accepted':True}}) as api,\
             patch('run_cellvis24_scanner_hamilton.dispatch',return_value={'record':'open_trial.json'}),\
             patch('barcode_opposite_pickup.run',return_value=Path('pickup.json')) as pickup,\
             patch.object(live,'transport',return_value={}) as transport:
            live.original_scanner(source)
        api.assert_called_once_with('developer/api/barcode-opposite-trial/preview',
            {'source':str(source),'target':1.77})
        pickup.assert_called_once_with('open_trial.json',alignment_confirmed=True)
        transport.assert_called_once_with(Path('pickup.json'),'scanner')

    def test_station_continuation_explicitly_disables_calibration(self):
        with patch('run_cellvis24_scanner_hamilton.reconnect'),\
             patch('run_cellvis24_scanner_hamilton.api',return_value={'plan':{}}) as api,\
             patch('run_cellvis24_scanner_hamilton.dispatch',return_value={'record':'station.json'}),\
             patch('plate_registry.PlateRegistry'):
            m.Live().stations('release.json','unit-test')
        self.assertIs(api.call_args.args[1]['full_calibration'],False)

    def test_resume_refuses_any_scan_or_pickup_progress(self):
        self.path.with_name('registration_pass_2.json').write_text(json.dumps(dict(
            status='stopped_or_uncertain',steps=[{'phase':'original_scanner'}],at=0,finished_at=2)))
        failure=Path(self.tmp.name)/'failure.json'
        failure.write_text(json.dumps(dict(status='stopped_or_uncertain',error='Stationary plate observations disagree; no alignment.',
            at=1,finished_at=2,steps=[{'kind':'queue','status':'completed'},{'kind':'vision','status':'checking'}])))
        with self.assertRaisesRegex(RuntimeError,'reviewed calibration-only'):
            m.run_second_pass(self.path,self.live,resume_before_scan=failure)
        self.live.original_scanner.assert_not_called()

if __name__=='__main__':unittest.main()
