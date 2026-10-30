"""A clone must resolve evidence and launch paths without access to the lab."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'operator_ui'))
import realsense_service as depth


class CheckoutTests(unittest.TestCase):
    def test_controller_packages_match_manifests(self):
        manifests = list((ROOT/'controller').glob('*.manifest.json'))
        self.assertGreaterEqual(len(manifests), 10)
        for manifest in manifests:
            data = json.loads(manifest.read_bytes())
            raw = (manifest.parent/data['output']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), data['output_sha256'], manifest.name)

    def test_recorded_routes_and_grip_evidence_survive_checkout(self):
        from hamilton_accepted_route import evidence
        from scope_compact137 import accepted
        from projected_pickup import load, accepted_grip
        from test_researcher import console
        evidence(); accepted(); accepted_grip(load()[0])
        console.latest_hamilton.reviewed()

    def test_mcp_entry_is_relative_to_repo_and_uses_portable_python(self):
        server = json.loads((ROOT/'.mcp.json').read_bytes())['mcpServers']['bioyond-s4']
        self.assertEqual(server['command'], 'python')
        self.assertFalse(Path(server['args'][0]).is_absolute())
        self.assertTrue((ROOT/server['args'][0]).is_file())

    def test_depth_launch_uses_selected_platform_interpreter_without_hardware(self):
        for platform, relative in [('nt', 'Scripts/python.exe'), ('posix', 'bin/python')]:
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                executable = root/'.venv-realsense'/relative
                executable.parent.mkdir(parents=True); executable.touch()
                (root/'operator_ui').mkdir()
                service = depth.RealSenseService()
                original = depth.worker_python
                resolve = lambda: original(root, platform)
                with patch.object(depth, 'ROOT', root), patch.object(depth, 'worker_python', resolve), \
                     patch.object(service, 'status', side_effect=[{'ok': False}, {'ok': True}]), \
                     patch.object(depth.subprocess, 'Popen') as start:
                    self.assertTrue(service.launch()['ok'])
                self.assertEqual(start.call_args.args[0][0], str(executable))
                self.assertIn(str(root/'operator_ui/realsense_worker.py'), start.call_args.args[0])

    def test_depth_missing_environment_gives_setup_instructions(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(depth, 'ROOT', Path(temp)):
            service = depth.RealSenseService()
            with patch.object(service, 'status', return_value={'ok': False}), patch.object(depth.subprocess, 'Popen') as start:
                with self.assertRaisesRegex(RuntimeError, 'Windows or Linux'):
                    service.launch()
                start.assert_not_called()
