"""Production Flask ownership integration, with all devices mocked; no hardware."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app as console


class Tests(unittest.TestCase):
    def test_depth_control_independent_of_robot_sequence(self):
        with patch.object(console,'runner',SimpleNamespace(active=True)), \
             patch.object(console.realsense,'request',return_value=(b'{"ok":true}', 'application/json',200)) as proxy, \
             patch.object(console.pickup,'invalidate') as invalidate:
            response = console.app.test_client().post('/realsense/stop',json={})
            self.assertEqual(response.status_code,200)
            proxy.assert_called_once()
            invalidate.assert_not_called()

    def test_robot_motion_still_blocked_during_sequence(self):
        with patch.object(console,'runner',SimpleNamespace(active=True)), \
             patch.object(console.svc,'move_cartesian') as move:
            response = console.app.test_client().post('/move',json={})
            self.assertEqual(response.status_code,409)
            move.assert_not_called()


if __name__ == '__main__': unittest.main()
