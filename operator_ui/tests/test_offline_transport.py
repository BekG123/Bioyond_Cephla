"""Real TCP client against the in-process fake controller, never the lab arm."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'operator_ui'), str(ROOT/'bioyond-s4-mcp/tests')]
from fake_controller import FakeController
from robot_service import RobotService


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, BIOYOND_ENV_STORE=str(Path(self.temp.name)/'envelope.json'))
        env.start(); self.addCleanup(env.stop)
        self.fake = FakeController()
        self.addCleanup(self.fake._srv.close)
        self.service = RobotService()
        self.addCleanup(self.service.disconnect)
        self.assertTrue(self.service.connect('127.0.0.1', self.fake.port)['ok'])
        self.service.set_envelope(100, 500, -350, 100, 30, 420)

    def test_units_motion_and_envelope_refusal(self):
        pose = self.service.pose_mm()
        self.assertEqual((pose['X'], pose['Z'], pose['Rz']), (300., 370., 90.))
        result = self.service.move_cartesian(305, -55, 365, 90)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['pose_after']['X'], 305.)
        refused = self.service.move_cartesian(305, -55, 900, 90)
        self.assertFalse(refused['ok'])
        self.assertIn('outside', refused['error'])
        self.assertEqual(self.service.pose_mm()['Z'], 365.)

    def test_envelope_persists_and_opening_reports_no_grasp(self):
        self.assertEqual(RobotService().envelope, self.service.envelope)
        result = self.service.move_gripper(28)
        self.assertTrue(result['ok'])
        self.assertFalse(result['gripper']['grip_detected'])
        self.assertEqual(self.service.gripper_status()['e1_position'], 28.)
        self.assertFalse(self.service.torque_report()['telemetry_live'])
