import unittest
from pathlib import Path
from unittest.mock import patch
from run_dna_plate_registration import scan_until_decoded


class BoundedRegistrationScanTests(unittest.TestCase):
    def test_five_no_reads_end_without_sixth_trigger(self):
        with patch('barcode_scanner_cli.scan_once',return_value=({'result':'no_read'},Path('scan.json'))) as scan,patch('run_dna_plate_registration.time.sleep'):
            with self.assertRaisesRegex(RuntimeError,'No read after 5'):
                scan_until_decoded(5,1)
            self.assertEqual(scan.call_count,5)

    def test_decode_ends_scanning_immediately(self):
        replies=[({'result':'no_read'},Path('one.json')),({'result':'decoded','barcode':'DNA-001'},Path('two.json'))]
        with patch('barcode_scanner_cli.scan_once',side_effect=replies) as scan,patch('run_dna_plate_registration.time.sleep'):
            record,receipt,count=scan_until_decoded(5,1)
            self.assertEqual(count,2);self.assertEqual(scan.call_count,2)
            self.assertEqual(record['barcode'],'DNA-001')

    def test_transport_failure_or_unconfirmed_stop_never_retries(self):
        for reply in ({'result':'timeout'},{'result':'decoded','barcode':'DNA-001','stop_error':'lost'}):
            with self.subTest(reply=reply),patch('barcode_scanner_cli.scan_once',return_value=(reply,Path('scan.json'))) as scan:
                with self.assertRaises(RuntimeError):scan_until_decoded(5,1)
                self.assertEqual(scan.call_count,1)

    def test_invalid_limit_never_triggers(self):
        for count in (0,6,True):
            with patch('barcode_scanner_cli.scan_once') as scan:
                with self.assertRaises(ValueError):scan_until_decoded(count,1)
                scan.assert_not_called()


if __name__=='__main__':unittest.main()
