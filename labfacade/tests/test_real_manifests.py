"""Checks against the real machines/ folder and Squid's saving format."""
import pytest

from labfacade import Facade, Signer, load_manifests
from labfacade.fakes import FakeMachine
from labfacade.manifest import implemented_paths, missing_implementations
from labfacade.squid_format import configured_saving_format
from conftest import REPO, kinds

REAL = load_manifests(REPO / 'machines')


def test_real_manifests_are_found():
    assert {'hamilton_prep', 'bioyond_s4', 'squid'} <= set(REAL)


@pytest.mark.parametrize('machine', sorted(REAL))
def test_every_implemented_by_path_exists(machine):
    assert missing_implementations(REAL[machine]) == []


def test_implemented_by_parsing():
    assert implemented_paths('operator_ui/squid_stage.py (SquidStage.execute)') == ['operator_ui/squid_stage.py']
    assert implemented_paths('MCP get_status, get_robot_errors') == []
    assert implemented_paths('.claude/skills/aruco-grab') == ['.claude/skills/aruco-grab']
    assert implemented_paths('operator_ui/park_bare_channels.py --execute-confirmed') \
        == ['operator_ui/park_bare_channels.py']


@pytest.mark.parametrize('machine', sorted(REAL))
def test_an_invalid_manifest_refuses_everything(machine, tmp_path):
    manifest = REAL[machine]
    fake = FakeMachine()
    facade = Facade.from_manifests(REAL, {machine: fake}, Signer(b'k' * 32), tmp_path)
    read = next(op['name'] for op in manifest.operations() if op.get('risk') == 'read_only')
    result = facade.run_operation(machine, read)
    if manifest.valid:
        assert result['outcome'] == 'completed'
    else:
        assert (result['outcome'], result['code']) == ('refused', 'manifest_invalid')
        assert fake.commands == [] and facade.describe(machine)['manifest_errors']


def test_broken_yaml_or_schema_fails_closed(tmp_path):
    (tmp_path / 'broken.yaml').write_text('id: [unclosed')
    (tmp_path / 'thin.yaml').write_text('id: thin\noperations:\n  - {name: go, risk: motion, description: x}\n')
    manifests = load_manifests(tmp_path, REPO / 'machines' / 'manifest.schema.json')
    assert not manifests['broken'].valid and not manifests['thin'].valid
    assert not load_manifests(tmp_path)['thin'].valid          # no schema file next to them either


def _software(tmp_path, ini=None, default='INDIVIDUAL_IMAGES'):
    (tmp_path / 'control').mkdir(parents=True)
    (tmp_path / 'control' / '_def.py').write_text(f'FILE_SAVING_OPTION = FileSavingOption.{default}\n')
    if ini is not None:
        (tmp_path / 'configuration_test.ini').write_text('[GENERAL]\n' + ini)
    return tmp_path


def test_squid_saving_format_warns_unless_zarr(tmp_path, lab):
    report = configured_saving_format(_software(tmp_path / 'a', 'FILE_SAVING_OPTION = "MULTI_PAGE_TIFF"\n'))
    assert (report['format'], report['zarr']) == ('MULTI_PAGE_TIFF', False) and 'not OME-Zarr' in report['warning']
    report = configured_saving_format(_software(tmp_path / 'b'))
    assert (report['format'], report['source'], report['zarr']) == ('INDIVIDUAL_IMAGES', 'control/_def.py default', False)
    report = configured_saving_format(_software(tmp_path / 'c', 'FILE_SAVING_OPTION = "ZARR_V3"\n'))
    assert report['zarr'] is True and report['warning'] is None
    six_d = 'FILE_SAVING_OPTION = "ZARR_V3"\nZARR_USE_6D_FOV_DIMENSION = True\n'
    report = configured_saving_format(_software(tmp_path / 'd', six_d))
    assert report['zarr'] is False and '6D' in report['warning']

    run, _ = lab.run()
    lab.facade.squid_saving_format(tmp_path / 'a', run)
    assert kinds(run, 'anomaly')[-1]['status'] == 'saving_format'
