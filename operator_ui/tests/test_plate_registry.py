"""Persistent identity, rack conflicts and Lacry integration. No lab hardware."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plate_registry import PlateRegistry, PlateError
from plate_memory import register_plate_api


def receipt(plate_id, at='2026-11-11T20:00:00+00:00'):
    return dict(at=at, result='decoded', barcode=plate_id, framed=True,
                response_hex=(plate_id+'\x04').encode().hex())


class PlateRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'plates.sqlite3'
        self.store = PlateRegistry(self.path)

    def scan(self, ident='001'):
        return self.store.record_scan(receipt(ident), 'test receipt')

    def test_restart_exact_ids_history_and_idempotent_import(self):
        for ident in ('001','1','plate-A','plate-a',' 001 '):
            self.scan(ident)
        row = self.store.get('001')
        self.store.update('001', row['revision'], {'contents':'DNA reagents','aliases':['DNA stock']}, 'researcher')
        self.scan()
        reopened = PlateRegistry(self.path)
        self.assertEqual(reopened.get('001')['scan_count'], 1)
        self.assertEqual(reopened.search('DNA')['plates'][0]['plate_id'], '001')
        self.assertEqual(reopened.search('001')['total'], 1)
        self.assertEqual(reopened.search()['total'], 5)
        self.assertEqual(len(reopened.get('001', history=True)['history']), 2)
        self.assertEqual(reopened.get('001')['location'], 'unknown')

    def test_rescan_preserves_metadata_and_old_import_does_not_regress_time(self):
        row = self.scan()
        self.store.update('001', row['revision'], {'contents':'DNA'}, 'researcher')
        self.store.record_scan(receipt('001','2026-11-11T21:00:00+00:00'), 'later')
        self.store.record_scan(receipt('001','2026-11-11T19:00:00+00:00'), 'older import')
        row = self.store.get('001')
        self.assertEqual(row['metadata']['contents'], 'DNA')
        self.assertEqual(row['last_seen'], '2026-11-11T21:00:00+00:00')
        self.assertEqual(row['scan_count'], 3)
        self.assertEqual(row['location'], 'unknown')

    def test_ng_timeout_corrupt_and_mismatched_frames_never_create_identity(self):
        for status in ('no_read','timeout','incomplete','error'):
            self.assertIsNone(self.store.record_scan(dict(receipt('001'), result=status), 'test'))
        for changes in ({'framed':False},{'barcode':'002'},{'response_hex':'ff04'},
                        {'response_hex':'303031'}, {'barcode':1}, {'at':'yesterday'}):
            with self.subTest(changes=changes), self.assertRaises(PlateError):
                self.store.record_scan(dict(receipt('001'), **changes), 'test')
        with self.assertRaises(PlateError):
            self.store.record_scan(receipt('NG'), 'test')
        self.assertEqual(self.store.search()['total'], 0)

    def test_reservation_separate_from_occupancy_and_conflicts_atomic(self):
        first, second = self.scan('001'), self.scan('002')
        first = self.store.assign_slot('001', first['revision'], 'rack:1/slot:2', 'researcher')
        self.assertEqual(first['location'], 'unknown')
        with self.assertRaises(PlateError):
            self.store.assign_slot('002', second['revision'], 'rack:1/slot:2', 'researcher')
        with self.assertRaises(PlateError):
            self.store.report_location('002', second['revision'], 'rack:1/slot:2', 'researcher')
        first = self.store.report_location('001', first['revision'], 'rack:1/slot:2', 'researcher')
        first = self.store.assign_slot('001', first['revision'], None, 'release reservation')
        with self.assertRaises(PlateError):
            self.store.assign_slot('002', second['revision'], 'rack:1/slot:2', 'researcher')
        self.store.report_location('001', first['revision'], 'unknown', 'removed; location unknown')
        self.store.assign_slot('002', second['revision'], 'rack:1/slot:2', 'researcher')
        self.assertEqual(self.store.slots()[1]['assigned_plate_id'], '002')
        self.assertIsNone(self.store.slots()[1]['reported_plate_id'])
        self.assertFalse(self.store.slots()[1]['motion_commissioned'])

    def test_concurrent_slot_claim_has_one_winner(self):
        rows = [self.scan(i) for i in ('001','002')]
        def assign(row):
            try:
                self.store.assign_slot(row['plate_id'], row['revision'], 'rack:1/slot:1', 'operator')
                return True
            except PlateError:
                return False
        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertEqual(sum(workers.map(assign, rows)), 1)

    def test_stale_revision_missing_plate_bad_slot_and_rollback(self):
        row = self.scan()
        self.store.update('001', row['revision'], {'notes':'first'}, 'researcher')
        with self.assertRaises(PlateError):
            self.store.update('001', row['revision'], {'notes':'lost update'}, 'researcher')
        with self.assertRaises(PlateError):
            self.store.update('999', 1, {'notes':'invented'}, 'researcher')
        current = self.store.get('001')
        with self.assertRaises(PlateError):
            self.store.assign_slot('001', current['revision'], 'rack:1/slot:6', 'researcher')
        with self.assertRaises(PlateError):
            self.store.update('001', current['revision'], {'notes':'rollback'}, '')
        self.assertEqual(self.store.get('001'), current)

    def test_ambiguous_contents_are_explicit_and_exact_id_is_preserved(self):
        for ident in ('001','002'):
            row = self.scan(ident)
            self.store.update(ident,row['revision'],{'contents':'DNA reagents'},'researcher')
        result = self.store.search('the plate with DNA')
        self.assertTrue(result['ambiguous'])
        self.assertEqual(result['total'], 2)
        self.assertFalse(self.store.search('001')['ambiguous'])

    def test_http_and_agent_tools_use_same_persistent_record_without_motion(self):
        from flask import Flask
        from lacry_agent import LacryAgent
        from lacry_memory import LacryMemory
        from sequences import Runner
        app = Flask(__name__)
        register_plate_api(app, self.store)
        client = app.test_client()
        row = self.scan()
        result = client.post('/researcher/api/plates/update',json=dict(plate_id='001',revision=row['revision'],
            researcher_quote='Plate 001 contains DNA reagents', changes={'contents':'DNA reagents'}))
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json['motion_started'])
        self.assertEqual(client.get('/researcher/api/plates?q=DNA').json['plates'][0]['plate_id'],'001')
        self.assertEqual(client.post('/researcher/api/plates/assign-slot',json=[]).status_code,400)
        model, backend = Mock(), Mock()
        model.complete.return_value = dict(content=[dict(type='text',text='Plate 001 contains DNA reagents.')])
        memory = LacryMemory(Path(self.temp.name)/'memory.sqlite3', plate_registry=self.store)
        agent = LacryAgent(backend, Mock(), lambda:Runner(), client=model, memory=memory)
        agent.public = Mock(return_value={'ok':True})
        output, error = agent._run_tool('get_plate',dict(plate_id='001'))
        self.assertFalse(error)
        self.assertIn('DNA reagents',output)
        agent.send('Which plate has DNA reagents?')
        request=model.complete.call_args.args[0]
        # Live inventory is appended to the newest turn, preserving the model's
        # system/history prefix (including signed thinking blocks).
        context=json.dumps([m for m in request['messages'] if m['role']=='user'][-1]['content'])
        self.assertIn('Plate inventory',context)
        self.assertIn('DNA reagents',context)
        self.assertIn('plate_id',context)
        self.assertNotIn('DNA reagents',request['system'])
        backend.execute_step.assert_not_called()

    def test_run_links_history_and_invalidates_old_reported_custody(self):
        row = self.scan()
        self.store.report_location('001',row['revision'],'HOME','researcher')
        self.store.record_run('001','run-1','started','run folder')
        self.store.record_run('001','run-1','completed','run folder')
        record = self.store.get('001',history=True)
        self.assertEqual(record['location'],'unknown')
        self.assertEqual(record['history'][0]['data']['run_id'],'run-1')

    def test_original_scanner_receipt_uses_recorded_raw_events(self):
        old = receipt('001')
        raw = old.pop('response_hex')
        old.pop('framed')
        old.update(response_complete=True, events=[{'rx_hex':raw}])
        self.assertEqual(self.store.record_scan(old, 'original receipt')['plate_id'], '001')
        self.store.record_scan(old, 'original receipt')
        self.assertEqual(self.store.get('001')['scan_count'], 1)


if __name__ == '__main__':
    unittest.main()
