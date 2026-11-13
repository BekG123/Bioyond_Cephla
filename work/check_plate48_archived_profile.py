"""Run offline production tests against the committed accepted fixture.

The live working profile has a pre-existing unaccepted correction. This does
not edit it or treat it as approved. All hardware is mocked by the tests.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'operator_ui'), str(ROOT/'operator_ui/tests')]
import projected_pickup

raw = subprocess.check_output(['git','show','HEAD:Pick and Hold/Calibration/plate_48_pickup_profile.json'], cwd=ROOT)
with tempfile.TemporaryDirectory(prefix='cephla-profile-test-') as directory:
    fixture = Path(directory)/'accepted_profile.json'
    fixture.write_bytes(raw)
    # The older fake service predates the native E2 reader. Supply the
    # already-verified angle boundary here; its checks have separate tests.
    with patch.object(projected_pickup, 'PROFILE', fixture), \
            patch('calibration_e2.verify', return_value=None):
        suite = unittest.defaultTestLoader.loadTestsFromName('test_plate48_workflow')
        result = unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(not result.wasSuccessful())
