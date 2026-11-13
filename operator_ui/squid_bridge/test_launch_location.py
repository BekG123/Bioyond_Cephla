"""Installation resolution and preview only; no Squid imports or hardware."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import launch


class LocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.software = self.home/'Desktop/squid-latest/software'
        self.software.mkdir(parents=True)
        (self.software/'main_hcs.py').write_text('# fixture')

    def test_default_is_desktop(self):
        with patch.object(launch.Path, 'home', return_value=self.home), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(launch.software_directory(), self.software.resolve())

    def test_explicit_path_precedes_environment(self):
        with patch.dict(os.environ, {'SQUID_SOFTWARE_DIR':str(self.home/'missing')}):
            self.assertEqual(launch.software_directory(self.software), self.software.resolve())
            with self.assertRaises(SystemExit): launch.software_directory()

    def test_missing_selected_installation_has_no_fallback(self):
        with patch.object(launch.Path, 'home', return_value=self.home):
            with self.assertRaises(SystemExit): launch.software_directory(self.home/'missing')

    def test_preview_does_not_change_directory_or_boot(self):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['launch.py', '--software', str(self.software), '--check',
                                      '--stage-only', '--simulate-camera', '--controller-serial', '12769210', '--start-server']), \
             patch.object(launch.os, 'chdir') as change, patch.object(launch.runpy, 'run_path') as boot, \
             contextlib.redirect_stdout(output):
            launch.main()
        change.assert_not_called(); boot.assert_not_called()
        result=json.loads(output.getvalue())
        self.assertFalse(result['started']); self.assertFalse(result['stage_simulated'])
        self.assertTrue(result['camera_simulated'])
        self.assertEqual(result['software'], str(self.software.resolve()))


if __name__ == '__main__': unittest.main()
