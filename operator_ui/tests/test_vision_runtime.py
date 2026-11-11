import sys
from pathlib import Path
from unittest.mock import patch
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import vision_runtime as runtime


class RuntimeTests(unittest.TestCase):
    def test_actual_pinned_environment(self):
        self.assertTrue(runtime.verify()['validated'])

    def test_wrong_version_refused(self):
        with patch('cv2.__version__','5.0.0'), self.assertRaises(RuntimeError):
            runtime.verify()

    def test_legacy_launch_redirects_before_initialization(self):
        with patch.object(sys,'executable','C:/wrong/python.exe'), \
             patch.object(runtime.os,'execv',side_effect=SystemExit) as execute:
            with self.assertRaises(SystemExit):runtime.bootstrap()
        self.assertEqual(execute.call_args.args[0],str(runtime.PYTHON))
        self.assertIn(str(runtime.ROOT/'operator_ui/app.py'),execute.call_args.args[1])


if __name__=='__main__':unittest.main()
