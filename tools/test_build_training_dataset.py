import gzip
import json
from pathlib import Path
import tempfile
import unittest
from build_training_dataset import Exporter, clean, parse, domain, asset_metadata, identifier
from validate_training_dataset import validate, remove_flagged_transitions


class DatasetTests(unittest.TestCase):
    def test_rgb_baseline_is_not_mislabeled_as_predicted_depth(self):
        self.assertEqual(asset_metadata('operator_ui/depth_baselines/test/rgb.png')['supervision'], 'unlabeled')
        self.assertEqual(asset_metadata('operator_ui/depth_baselines/test/prediction.npy')['supervision'], 'model_prediction_not_ground_truth')
        self.assertEqual(asset_metadata('operator_ui/realsense_captures/test/depth_m.npy')['asset_kind'], 'depth_sensor_measurement')
        self.assertEqual(asset_metadata('operator_ui/reports/plate/overlay.jpg')['asset_kind'], 'derived_visualization')

    def test_simulation_flags_are_not_physical_success(self):
        self.assertEqual(domain('mujoco_sim/runs/test/report.json', {'success':True}), 'simulation_or_offline_fixture')
        self.assertEqual(domain('operator_ui/logs/squid/events.jsonl',
            {'stage_simulated':False,'camera_simulated':True,'completed':True}), 'real_stage_simulated_camera')
        self.assertEqual(domain('operator_ui/reports/trial/result.json', {'ok':True}), 'unspecified_check_source')

    def test_appending_log_is_bounded_by_inventoried_length(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'operator_ui/reports/trial/events.jsonl'
            source.parent.mkdir(parents=True)
            source.write_text('{"event":"first"}\n', encoding='utf-8')
            stat=source.stat()
            with source.open('a',encoding='utf-8') as f:f.write('{"event":"later"}\n')
            exporter=Exporter(root,root/'training_data/snapshot')
            exporter.source(source,stat)
            for handle in exporter.handles.values():handle.close()
            manifest=json.loads((exporter.output/'source_manifest.jsonl').read_text())
            self.assertEqual(manifest['bytes_hashed'],stat.st_size)
            self.assertTrue(manifest['changed_during_export'])
            with gzip.open(exporter.output/'agent_instruments/events.jsonl.gz','rt') as f:
                self.assertEqual(len(f.readlines()),1)

    def test_secret_redaction_and_nonfinite_rejection(self):
        row = clean({'api_key': 'private', 'nested': ['Bearer abc123', 'password=private'], 'tokens_used': 15})
        self.assertEqual(row['api_key'], '[REDACTED]')
        self.assertNotIn('private', json.dumps(row))
        self.assertEqual(row['tokens_used'], 15)
        for raw in ('{"x":NaN}', '{"x":1e999}'):
            with self.assertRaises(ValueError): parse(raw)

    def test_export_provenance_gaps_faults_labels_and_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            demo = root / 'operator_ui/demonstrations/trial'
            demo.mkdir(parents=True)
            def sample(t, errors=None):
                return dict(at=t, robot=dict(ok=True, connected=True, errors=errors or [],
                    pose_mm=dict(X=t,Y=0,Z=10,Rz=0), external_axes={'E1':3.7}))
            rows = [sample(1),dict(at=1.1,valid=False,error='Connection lost'),sample(1.2),sample(4),sample(4.2,['fault']),sample(4.4),sample(4.6)]
            source = demo / 'samples.jsonl'
            source.write_text(''.join(json.dumps(x)+'\n' for x in rows)+'{"truncated":', encoding='utf-8')
            before = source.read_bytes()
            (demo/'result.json').write_text('{"ok":true,"replay_approved":false}')
            audit = root/'operator_ui/logs/audit/session'
            audit.mkdir(parents=True)
            (audit/'events_0001.jsonl').write_text(json.dumps(dict(event='http_request',method='GET'))+'\n'+
                json.dumps(dict(event='http_request',method='POST',body={'api_key':'private'}))+'\n')
            assets=root/'operator_ui/depth_baselines/test'
            assets.mkdir(parents=True);(assets/'prediction.npy').write_bytes(b'test fixture')
            out=root/'training_data/snapshot'
            summary=Exporter(root,out).run()
            self.assertEqual(source.read_bytes(),before)
            self.assertEqual(summary['counts']['motion/transitions.jsonl.gz'],1)
            self.assertEqual(summary['counts']['quality/quarantine.jsonl'],1)
            self.assertEqual(summary['counts']['excluded_get_poll_records'],1)
            with gzip.open(out/'labels/evidence.jsonl.gz','rt',encoding='utf-8') as f:
                labels=[json.loads(x) for x in f]
            self.assertTrue(any(x['evidence'].get('replay_approved') is False for x in labels))
            self.assertTrue(all(x['eligibility']=='review_required' for x in labels))
            asset=json.loads((out/'vision/assets.jsonl').read_text())
            self.assertEqual(asset['supervision'],'model_prediction_not_ground_truth')
            self.assertTrue(asset['sha256'])
            validate(out)
            self.assertTrue(json.loads((out/'validation.json').read_text())['ok'])
            # Reproduce the old builder's edge case: a failed poll with no pose between valid samples.
            with gzip.open(out/'motion/observations.jsonl.gz','rt',encoding='utf-8') as f:
                obs=[json.loads(line) for line in f]
            with gzip.open(out/'motion/transitions.jsonl.gz','rt',encoding='utf-8') as f:
                bad=json.loads(f.readline())
            bad.update(id=identifier(obs[0]['id']+':'+obs[1]['id']),
                observation_id=obs[0]['id'],next_observation_id=obs[1]['id'],dt_s=.2)
            with gzip.open(out/'motion/transitions.jsonl.gz','at',encoding='utf-8') as f:
                f.write(json.dumps(bad)+'\n')
            info=json.loads((out/'dataset.json').read_text())
            info['counts']['motion/transitions.jsonl.gz']+=1
            (out/'dataset.json').write_text(json.dumps(info))
            with self.assertRaises(SystemExit):validate(out)
            remove_flagged_transitions(out)
            validate(out)
            self.assertTrue(json.loads((out/'validation.json').read_text())['ok'])
            with self.assertRaises(ValueError): Exporter(root,out)


if __name__ == '__main__': unittest.main()
