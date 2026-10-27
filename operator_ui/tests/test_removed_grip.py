"""Deleted grip workflows cannot dispatch any hardware work."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_researcher import console


class RemovedGripTests(unittest.TestCase):
    def test_retired_routes_never_start_runner(self):
        with patch.object(console.runner,'start') as start:
            client=console.app.test_client()
            for path in ('/seq/workflow','/seq/transfer','/seq/verify_pickup'):
                response=client.post(path,json={'operator_confirmed':True,'cell_clear':True})
                self.assertEqual(response.status_code,410,path)
                self.assertFalse(response.get_json()['ok'])
            start.assert_not_called()

    def test_stepper_removed(self):
        rules={str(r) for r in console.app.url_map.iter_rules()}
        self.assertFalse(any('manual-grip' in r for r in rules))
        self.assertFalse((Path(__file__).resolve().parents[1]/'manual_grip.py').exists())


if __name__=='__main__':unittest.main()
