import unittest
from types import SimpleNamespace
from unittest.mock import patch
import run_hotel_slot_trial as cli
import hotel_slot2_trial as trial

class LauncherTests(unittest.TestCase):
    def test_both_previews_make_no_hardware_calls(self):
        with patch.object(cli,'api') as api,patch.object(cli,'reconnect') as reconnect,patch.object(cli,'dispatch') as dispatch,patch('builtins.print'):
            cli.main(['--slot','2']);cli.main(['--slot','3'])
        api.assert_not_called();reconnect.assert_not_called();dispatch.assert_not_called()

    def test_slot3_phase_cannot_be_sent_through_slot2_binding(self):
        g=trial.geometry(3);r=g['route'];owner=trial.TrialService(SimpleNamespace(),{'geometry':g})
        points,q=trial.prepare_for_service(owner,'slot3_taught_approach',r['start'],g['start_joints'],r['points'],g['cfg'],g['envelope'],r['speeds'])
        self.assertAlmostEqual(points[-1]['Z'],352.39)
        with self.assertRaisesRegex(Exception,'Slot and phase mismatch'):
            trial.prepare_for_service(owner,'slot2_taught_approach',r['start'],g['start_joints'],r['points'],g['cfg'],g['envelope'],r['speeds'])

    def test_no_automatic_connector_from_inside_rack(self):
        robot={'pose_mm':dict(X=224.65,Y=-135.35,Z=296,Rz=-.65)}
        with self.assertRaisesRegex(RuntimeError,'no automatic recovery'):cli.connector(robot,{})

if __name__=='__main__':unittest.main()
