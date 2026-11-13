"""Dataset integration tests: local files, fake machines, ephemeral HTTP only."""
from io import BytesIO
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import numpy as np
from PIL import Image
import pytest
import jsonschema

from labfacade.artifacts import digest, validate_ome, write_array
from labfacade.backends import BioyondConsoleBackend, HamiltonBackend, SquidBackend
from labfacade.dataset import ConsoleFrame, DatasetSources, RawJournal, collect_receipts, inspection_quality
from labfacade.squid_format import configured_saving_format
from labfacade.verify_dataset import verify_dataset
from labfacade.reconcile_dataset import reconcile_dataset
from conftest import REPO, kinds


def png(path):
    pixels = ((np.indices((64, 64)).sum(axis=0) // 8) % 2 * 255).astype('uint8')
    Image.fromarray(pixels).save(path, 'PNG')
    return True


def ome(root, ndim=2, complete=True):
    root.mkdir(parents=True)
    names = ['t', 'c', 'z', 'y', 'x'][-ndim:] if ndim <= 5 else ['f', 't', 'c', 'z', 'y', 'x']
    axes = [dict(name=n, type='time' if n == 't' else 'channel' if n == 'c' else 'space') for n in names]
    metadata = dict(zarr_format=3, node_type='group', attributes=dict(
        ome=dict(version='0.5', multiscales=[dict(axes=axes, datasets=[dict(path='0', coordinateTransformations=[dict(type='scale', scale=[1] * ndim)])])]),
        _squid=dict(acquisition_complete=complete)))
    (root / 'zarr.json').write_text(json.dumps(metadata))
    write_array(root / '0', np.ones([2] * ndim, dtype='uint16'))
    child = json.loads((root / '0/zarr.json').read_text())
    child['dimension_names'] = names
    (root / '0/zarr.json').write_text(json.dumps(child))
    return root


def test_collision_safe_copies_and_approval_snapshot(lab, tmp_path):
    run, _ = lab.run()
    raw = tmp_path / 'run.json'
    raw.write_text('{"old":true}')
    first = run.collect('bioyond_s4', raw, 's01')
    raw.write_text('{"new":true}')
    second = run.collect('bioyond_s4', raw, 's01')
    assert first['path'] != second['path']
    assert json.loads((run.path / first['path']).read_text()) == {'old': True}
    assert digest(run.path / first['path']) == first['sha256']
    assert run.read_json('run.json')['approvals']['approval.json']['record'] == run.read_json('approval.json')
    assert set(p.name for p in run.path.iterdir() if p.is_dir()) == {'frames', 'squid', 'bioyond', 'hamilton'}


def test_receipt_graph_cycles_missing_and_escape(lab, tmp_path):
    run, _ = lab.run()
    root = tmp_path / 'receipts'
    root.mkdir()
    a, b = root / 'a.json', root / 'b.json'
    a.write_text(json.dumps(dict(record=str(b), source='missing.json', receipt=str(tmp_path / 'secret.json'))))
    b.write_text(json.dumps(dict(source=str(a))))
    result = collect_receipts(run, 'bioyond_s4', 's01', [a], [root])
    assert len(result) == 2
    assert {e['status'] for e in kinds(run, 'anomaly')} >= {'evidence_not_collected', 'evidence_path_rejected'}
    assert len(run.read_json('artifacts.json')['artifacts']) == 2


def test_bioyond_receipt_bindings_and_provenance_tags(lab, tmp_path):
    run, _ = lab.run()
    reports = tmp_path / 'operator_ui/reports'
    holder = tmp_path / 'operator_ui/demonstrations/pickup_holder'
    grip = tmp_path / 'operator_ui/demonstrations/reference_grip'
    other = tmp_path / 'operator_ui/demonstrations/other'
    for folder in (reports, holder, grip, other):
        folder.mkdir(parents=True)
    (reports / 'run.json').write_text(json.dumps(dict(source='button', binding=dict(
        clearance_record=str(holder / 'clearance.json')))))
    (holder / 'clearance.json').write_text(json.dumps(dict(source='native_motion_status',
        grip_record=str(grip / 'grip.json'))))
    (grip / 'grip.json').write_text(json.dumps(dict(source=str(reports / 'run.json'))))
    backend = BioyondConsoleBackend(checkout=tmp_path)
    backend.last_record = reports / 'run.json'
    assert len(backend.collect_dataset(run, 's01', backend.WORKFLOW)) == 3
    assert not kinds(run, 'anomaly')
    assert verify_dataset(run.path)['ok']
    (grip / 'grip.json').write_text(json.dumps(dict(source='../missing.json',
        record=str(other / 'secret.json'))))
    backend.collect_dataset(run, 's01', backend.WORKFLOW)
    assert all(e['status'] == 'evidence_path_rejected' for e in kinds(run, 'anomaly'))


@pytest.mark.parametrize('style', ['flat', 'smooth_gradient', 'tiny'])
def test_suspect_frames_preserved_but_dataset_incomplete(lab, style):
    def capture(path):
        if style == 'smooth_gradient':
            pixels = np.tile(np.linspace(50, 82, 256, dtype='uint8'), (256, 1))
            Image.fromarray(pixels).save(path, 'PNG')
        else:
            Image.new('L', (1, 1) if style == 'tiny' else (256, 256), 64).save(path, 'PNG')
        return True
    lab.fakes['hamilton_prep'].dataset_sources = DatasetSources(frame=capture)
    run, _ = lab.run()
    assert lab.facade.run_step(run, 's04')['outcome'] == 'completed'
    assert len(list((run.path / 'frames').rglob('*.png'))) == 2
    gaps = run.read_json('dataset.json')['steps']['s04']['gaps']
    assert [g['status'] for g in gaps] == ['frame_quality_suspect'] * 2
    assert run.read_json('dataset.json')['steps']['s04']['complete'] is False
    assert verify_dataset(run.path)['ok']  # content warnings do not mean corrupt files


def test_structured_frame_quality(tmp_path):
    path = tmp_path / 'frame.png'
    png(path)
    assert inspection_quality(path)['status'] == 'no_issue_detected'


def test_reconcile_preserves_history_and_backfills_without_dispatch(lab, tmp_path):
    run, _ = lab.run(lab.one_step('bioyond_s4', 'run_plate_workflow'))
    checkout = tmp_path / 'execution'
    reports = checkout / 'operator_ui/reports'
    holder = checkout / 'operator_ui/demonstrations/pickup_holder'
    reports.mkdir(parents=True)
    holder.mkdir(parents=True)
    source = reports / 'run.json'
    child = holder / 'clearance.json'
    child.write_text('{}')
    source.write_text(json.dumps(dict(source='button', clearance_record=str(child))))
    run.collect('bioyond_s4', source, 's01')
    frame = run.path / 'frames/before.png'
    Image.new('L', (128, 128), 64).save(frame)
    artifact = run.artifact(frame)
    run.index_artifact(artifact, 'bioyond_s4', 's01', dict(type='inspection_frame', when='before'))
    run.events.emit('artifact', machine='bioyond_s4', step='s01', artifacts=[artifact])
    run.events.emit('command', step='s01', status='sent')
    run.events.emit('status', step='s01', status='progress', data=dict(line=dict(record=str(source))))
    run.write_json('dataset.json', dict(v=1, steps=dict(s01=dict(complete=False, gaps=[
        dict(status='evidence_not_collected', detail={'source':'button'}),
        dict(status='evidence_path_rejected', detail={'source':str(child)})]))))
    before = run.events.path.read_bytes()
    with pytest.raises(ValueError, match='terminal'):
        reconcile_dataset(run.path, checkout)
    assert run.events.path.read_bytes() == before
    run.events.emit('result', step='s01', status='completed')
    before = run.events.path.read_bytes()
    ledger, approval = [(run.path / f).read_bytes() for f in ('ledger.json', 'approval.json')]
    report = reconcile_dataset(run.path, checkout)
    assert report['verification']['ok']
    assert [g['status'] for g in report['dataset']['gaps']] == ['frame_quality_suspect']
    assert run.events.path.read_bytes().startswith(before)
    assert (run.path / 'ledger.json').read_bytes() == ledger
    assert (run.path / 'approval.json').read_bytes() == approval
    assert any(a.get('original') == str(child) for a in run.read_json('artifacts.json')['artifacts'])
    assert not any(lab.sent(m) for m in lab.fakes)
    child.write_text('{"changed":true}')
    report = reconcile_dataset(run.path, checkout)
    assert report['verification']['ok']
    assert any('changed' in g['detail'].get('error', '') for g in report['dataset']['gaps'])


def test_zarr_copy_manifest_hash_and_6d_rejection(lab, tmp_path):
    run, _ = lab.run()
    source = ome(tmp_path / 'plate.ome.zarr')
    assert validate_ome(source)['image_count'] == 1
    artifact = run.collect('squid', source, 's03', ome=True)
    manifest_path = run.path / artifact['path']
    assert digest(manifest_path) == artifact['sha256']
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest['files']:
        assert digest(manifest_path.parent / manifest['root'] / entry['path']) == entry['sha256']
    with pytest.raises(ValueError, match='6D'):
        run.collect('squid', ome(tmp_path / 'six.ome.zarr', 6), 's03', ome=True)
    with pytest.raises(ValueError, match='finalized'):
        validate_ome(ome(tmp_path / 'active.ome.zarr', complete=False))


def test_invalid_ome_transform_and_version(tmp_path):
    source = ome(tmp_path / 'image.ome.zarr')
    meta = json.loads((source / 'zarr.json').read_text())
    meta['attributes']['ome']['version'] = '0.4'
    (source / 'zarr.json').write_text(json.dumps(meta))
    with pytest.raises(ValueError, match='0.5'):
        validate_ome(source)


def test_invalid_array_shape_rejected(tmp_path):
    source = ome(tmp_path / 'image.ome.zarr')
    path = source / '0/zarr.json'
    metadata = json.loads(path.read_text())
    metadata['shape'] = [2.5, 2]
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match='positive integers'):
        validate_ome(source)


def test_arrays_externalized_not_stringified(lab):
    run, _ = lab.run()
    values = np.arange(6, dtype='uint16').reshape(2, 3)
    event = run.events.emit('result', machine='squid', step='s03', data=dict(pixels=values, facts=[1, 2]))
    assert event['data']['facts'] == [1, 2]
    assert 'array_artifact' in event['data']['pixels']
    artifact = event['artifacts'][0]
    manifest_path = run.path / artifact['path']
    manifest = json.loads(manifest_path.read_text())
    chunk = manifest_path.parent / manifest['root'] / 'c/0/0'
    assert np.array_equal(np.frombuffer(chunk.read_bytes(), dtype='<u2').reshape(2, 3), values)
    schema = json.loads((REPO / 'labfacade/schemas/event.schema.json').read_text())
    jsonschema.validate(event, schema)
    assert '[[0' not in run.events.path.read_text()


def test_three_machine_run_collects_frames_journals_and_zarr(lab, tmp_path):
    source = ome(tmp_path / 'plate.ome.zarr')
    software = tmp_path / 'software'
    software.mkdir()
    ini = software / 'active.ini'
    ini.write_text('FILE_SAVING_OPTION = ZARR_V3\nZARR_USE_6D_FOV_DIMENSION = False\n')
    for machine, backend in lab.fakes.items():
        journal = tmp_path / (machine + '.jsonl')
        journal.write_text('{"fact":"raw journal"}\n')
        backend.dataset_sources = DatasetSources(frame=png, journals=[journal],
            images=[source] if machine == 'squid' else [], software_dir=software if machine == 'squid' else None,
            active_config=ini if machine == 'squid' else None)
    run, _ = lab.run()
    for step in ('s01', 's02', 's03', 's04'):
        assert lab.facade.run_step(run, step)['outcome'] == 'completed'
    assert len(list((run.path / 'frames').rglob('*.png'))) == 8
    assert len([a for a in run.read_json('artifacts.json')['artifacts'] if a.get('format') == 'OME-Zarr']) == 2
    assert {e['machine'] for e in kinds(run, 'artifact')} == set(lab.fakes)
    assert any(e['status'] == 'saving_format' for e in kinds(run, 'status'))
    schema = json.loads((REPO / 'labfacade/schemas/event.schema.json').read_text())
    for event in run.events.read():
        jsonschema.validate(event, schema)
        for artifact in event['artifacts']:
            assert digest(run.path / artifact['path']) == artifact['sha256']
    assert verify_dataset(run.path)['ok']
    assert all(s['complete'] for s in run.read_json('dataset.json')['steps'].values())


@pytest.mark.parametrize('behavior,outcome', [({'raises':'fault'}, 'failed'), ({'hang':1}, 'unknown')])
def test_failed_steps_capture_after_and_do_not_retry(lab, behavior, outcome):
    backend = lab.fakes['hamilton_prep']
    backend.dataset_sources = DatasetSources(frame=png)
    backend.behaviors['park'] = behavior
    run, _ = lab.run()
    assert lab.facade.run_step(run, 's04')['outcome'] == outcome
    assert len(list((run.path / 'frames').rglob('*.png'))) == 2
    assert lab.facade.run_step(run, 's04')['code'] == 'run_paused'
    assert len(backend.commands) == 1
    backend.release.set()


def test_missing_frames_are_explicit(lab):
    lab.fakes['hamilton_prep'].capture_frame = None
    run, _ = lab.run()
    assert lab.facade.run_step(run, 's04')['outcome'] == 'completed'
    assert [e['data']['when'] for e in kinds(run, 'anomaly') if e['status'] == 'frame_unavailable'] == ['before', 'after']
    assert run.read_json('dataset.json')['steps']['s04']['complete'] is False


def test_hamilton_only_collects_owned_ticket_and_never_marker(lab, tmp_path):
    class Prep:
        folder = tmp_path
        active = dict(request_id='owned')
    (tmp_path / 'owned.jsonl').write_text('{"kind":"request"}\n')
    marker = tmp_path / 'active.json'
    marker.write_text('{"ownership":"unchanged"}')
    run, _ = lab.run()
    backend = HamiltonBackend(prep=Prep(), dataset_sources=DatasetSources())
    assert len(backend.collect_dataset(run, 's04', 'get_status')) == 1
    assert marker.read_text() == '{"ownership":"unchanged"}'


def test_selected_format_and_default_6d(tmp_path):
    (tmp_path / 'control').mkdir()
    (tmp_path / 'control/_def.py').write_text('FILE_SAVING_OPTION = FileSavingOption.ZARR_V3\nZARR_USE_6D_FOV_DIMENSION = True\n')
    assert not configured_saving_format(tmp_path)['zarr']
    ini = tmp_path / 'chosen.ini'
    ini.write_text('FILE_SAVING_OPTION = ZARR_V3\nZARR_USE_6D_FOV_DIMENSION = False\n')
    report = configured_saving_format(tmp_path, active_config=ini)
    assert report['zarr'] and not report['runtime_verified']


def test_console_frame_converts_jpeg_and_rejects_stale(tmp_path):
    buffer = BytesIO()
    Image.new('RGB', (3, 2), 'blue').save(buffer, 'JPEG')
    class Handler(BaseHTTPRequestHandler):
        stale = False
        def do_GET(self):
            assert self.path == '/frame'
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            if self.stale:
                self.send_header('X-Error', 'camera released')
            self.end_headers()
            self.wfile.write(buffer.getvalue())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        capture = ConsoleFrame(f'http://127.0.0.1:{server.server_address[1]}')
        path = tmp_path / 'frame.png'
        assert capture(path)
        with Image.open(path) as image:
            assert image.format == 'PNG' and image.size == (3, 2)
        Handler.stale = True
        with pytest.raises(RuntimeError, match='stale'):
            capture(tmp_path / 'bad.png')
    finally:
        server.shutdown()
        server.server_close()


def test_read_only_step_collects_before_after_and_journal(lab):
    lab.fakes['squid'].dataset_sources = DatasetSources(frame=png)
    run, _ = lab.run(lab.one_step('squid', 'get_status'))
    result = lab.facade.run_step(run, 's01')
    assert result['outcome'] == 'completed'
    assert len(list((run.path / 'frames/s01').glob('*.png'))) == 2
    assert any(p.endswith('transport.jsonl') for p in result['evidence_paths'])


def test_journal_hash_stable_after_timeout(lab):
    run, _ = lab.run()
    journal = RawJournal(run, 'bioyond_s4', 's01')
    journal('request', {'x': 1})
    artifact = journal.finish()
    journal('response', {'late': True})
    assert digest(run.path / artifact['path']) == artifact['sha256']
    assert len(journal.path.read_text().splitlines()) == 1


def test_completed_acquisition_handoff_is_bound_and_portable(lab, tmp_path):
    run, _ = lab.run()
    source = ome(tmp_path / 'output/plate.ome.zarr')
    receipt = tmp_path / 'native-run.json'
    receipt.write_text(json.dumps(dict(schema_version=1, run_id='native-42', status='completed',
                                     ended_at=42, experiment_id='exp-1', output_path=str(source.parent))))
    result = lab.facade.collect_acquisition(run, 's03', receipt, 'native-42', [source.parent])
    assert len(result) == 2
    assert kinds(run, 'result')[-1]['data']['acquisition_run_id'] == 'native-42'
    with pytest.raises(ValueError, match='identity'):
        lab.facade.collect_acquisition(run, 's03', receipt, 'different', [source.parent])
    with pytest.raises(ValueError, match='outside'):
        lab.facade.collect_acquisition(run, 's03', receipt, 'native-42', [tmp_path / 'other'])
    assert kinds(run, 'anomaly')[-1]['status'] == 'imaging_dataset_rejected'


def test_tiff_and_incomplete_acquisition_not_accepted(lab, tmp_path):
    run, _ = lab.run()
    output = tmp_path / 'output'
    output.mkdir()
    Image.new('L', (2, 2)).save(output / 'image.tiff')
    receipt = tmp_path / 'native.json'
    data = dict(schema_version=1, run_id='native', status='completed', ended_at=2, output_path=str(output))
    receipt.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='TIFF'):
        lab.facade.collect_acquisition(run, 's03', receipt, 'native', [output])
    data['status'] = 'running'
    receipt.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='completed'):
        lab.facade.collect_acquisition(run, 's03', receipt, 'native', [output])


def test_symlink_artifact_rejected(lab, tmp_path):
    run, _ = lab.run()
    source = tmp_path / 'source.json'
    source.write_text('{}')
    link = tmp_path / 'link.json'
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip('Windows symlink permission unavailable')
    with pytest.raises(ValueError, match='Linked'):
        run.collect('bioyond_s4', link, 's01')


def test_verifier_detects_modified_zarr_chunk(lab, tmp_path):
    run, _ = lab.run()
    artifact = run.collect('squid', ome(tmp_path / 'test.ome.zarr'), 's03')
    assert verify_dataset(run.path)['ok']
    manifest_path = run.path / artifact['path']
    manifest = json.loads(manifest_path.read_text())
    (manifest_path.parent / manifest['root'] / '0/c/0/0').write_bytes(b'corrupted')
    assert not verify_dataset(run.path)['ok']


def test_squid_generic_collector_cannot_bypass_6d_policy(lab, tmp_path):
    run, _ = lab.run()
    with pytest.raises(ValueError, match='6D'):
        run.collect('squid', ome(tmp_path / 'bad.ome.zarr', 6), 's03')


def test_hcs_plate_well_image_links(tmp_path):
    root = tmp_path / 'plate.ome.zarr'
    ome(root / 'A/1/0')
    for folder, attrs in ((root, dict(plate=dict(rows=[{'name':'A'}], columns=[{'name':'1'}],
                                              wells=[dict(path='A/1', rowIndex=0, columnIndex=0)]))),
                          (root / 'A', {}),
                          (root / 'A/1', dict(well=dict(images=[dict(path='0')])))):
        metadata = dict(zarr_format=3, node_type='group', attributes={'ome':dict(version='0.5', **attrs)} if attrs else {})
        (folder / 'zarr.json').write_text(json.dumps(metadata))
    assert validate_ome(root)['image_count'] == 1
    metadata['attributes']['ome']['well']['images'][0]['path'] = '../missing'
    (root / 'A/1/zarr.json').write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match='path'):
        validate_ome(root)
