import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import run_registered_cellvis_cycle as m


class CycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=patch.object(m,'REPORTS',Path(self.tmp.name));p.start();self.addCleanup(p.stop)
        self.live=Mock()
        self.live.original_scanner.return_value=('pickup',{})
        self.live.original_home.return_value=('released',{})
        self.live.opposite_scanner.return_value=('other',{})
        self.live.opposite_home.return_value=('restored',{})
        self.live.stations.return_value={'record':'cycle.json'}
    def test_decoded_identity_allows_one_cycle_without_opposite_side(self):
        r=m.run_cycle('source',purpose='DNA reagents',expected_plate_id='plate1',live=self.live,
            scan=lambda:dict(status='registered',plate_id='plate1'))
        self.assertEqual(r['completed_cycles'],1);self.assertEqual(r['calibration_runs'],0)
        self.live.opposite_scanner.assert_not_called()
        self.live.stations.assert_called_once_with('released','plate1')
    def test_two_no_reads_return_home_without_station_cycle(self):
        scan=Mock(return_value={'status':'no_read'})
        r=m.run_cycle('source',purpose='DNA reagents',live=self.live,scan=scan)
        self.assertEqual(scan.call_count,2);self.live.opposite_home.assert_called_once_with('other')
        self.live.stations.assert_not_called();self.assertEqual(r['completed_cycles'],0)
    def test_identity_mismatch_stops_after_home_and_fault_never_retries(self):
        with self.assertRaisesRegex(RuntimeError,'Unexpected barcode'):
            m.run_cycle('source',purpose='DNA reagents',expected_plate_id='plate1',live=self.live,
                scan=lambda:dict(status='registered',plate_id='plate2'))
        self.live.stations.assert_not_called()
        self.live.reset_mock();scan=Mock(side_effect=TimeoutError('uncertain scanner'))
        with self.assertRaises(TimeoutError):m.run_cycle('source',purpose='DNA reagents',live=self.live,scan=scan)
        scan.assert_called_once();self.live.original_home.assert_not_called();self.live.stations.assert_not_called()


if __name__=='__main__':unittest.main()
