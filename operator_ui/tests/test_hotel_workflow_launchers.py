import unittest
from unittest.mock import patch
import run_hotel_slot2_workflow as two
import run_hotel_slot3_workflow as three

class WorkflowLauncherTests(unittest.TestCase):
    def test_preview_never_connects_or_moves(self):
        for cli in (two,three):
            with self.subTest(cli=cli.__name__), patch.object(cli,'load_workflow',return_value=({'id':'test'},{})), patch.object(cli,'api') as api, patch.object(cli,'reconnect') as reconnect, patch('builtins.print'):
                cli.main(['--action','roundtrip'])
            api.assert_not_called();reconnect.assert_not_called()

    def test_slot2_accepted_evidence_still_matches(self):
        w,g=two.load_workflow()
        self.assertEqual(w['slot'],2)
        self.assertEqual(g['approach_geometry']['endpoint']['Z'],295.995)

    def test_slot3_accepted_evidence_binds_corrected_height(self):
        w,g=three.load_workflow()
        self.assertEqual(w['slot'],3)
        self.assertEqual(w['status'],'operator_accepted')
        self.assertEqual(g['approach_geometry']['endpoint']['Z'],352.387)
        self.assertEqual(g['routes']['lift']['points'][0]['Z'],357.387)

if __name__=='__main__':unittest.main()
