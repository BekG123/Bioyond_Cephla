import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from analyze_hamilton_inward_motion import drive_status, opening_contract, tlv

class FeedbackAnalysisTests(unittest.TestCase):
    def test_counter_and_encoder_are_not_conflated(self):
        report=drive_status('1e001c00170102000100280004009c44b542280004008856b342170102000000')
        self.assertAlmostEqual(report['position_mm'],90.6340026855)
        self.assertAlmostEqual(report['encoder_position_mm'],89.6690063477)
        self.assertAlmostEqual(report['position_minus_encoder_mm'],.9649963379)

    def test_packet_signs_and_velocity_independently_decoded(self):
        packet=opening_contract()
        self.assertEqual([(r['channel'],r['distance_mm']) for r in packet['channels']],[(1,.5),(2,-.5)])
        self.assertEqual(packet['velocity_mm_s'],1)

    def test_truncated_and_wrong_status_rejected(self):
        for payload in ('1e001c00','280004000000803f'):
            with self.assertRaises(ValueError): drive_status(payload)
        with self.assertRaises(ValueError): tlv(b'\x1e')

if __name__=='__main__': unittest.main()
