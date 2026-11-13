"""Fresh slot-1 retrieval receipts bound to the accepted Cellvis scanner geometry.

Historical evidence selects geometry, never supplies permission or fresh custody.
"""
import json
import time
from pathlib import Path
from autonomy import TransferError
from scope_step_trial import near
from calibration_e2 import accepted
from cellvis24_scanner_return import geometry, sha, ROOT

ACCEPTANCE=ROOT/'operator_ui/reports/plate_session/cellvis24_validation/accepted_lower_scanner_20261111.json'
FOLDER=ROOT/'runs/composed_transfers/handoffs'


def scanner_reference():
    d=json.loads(ACCEPTANCE.read_bytes())
    if d.get('status')!='operator_accepted_scanner_height' or d['target']['Z']!=163.76:
        raise TransferError('Accepted scanner reference changed.')
    receipt=ROOT/d['evidence'][0]['path']
    if sha(receipt)!=d['evidence'][0]['sha256']:raise TransferError('Scanner acceptance hash mismatch.')
    p=json.loads(receipt.read_bytes())['plan']['binding']['source']
    pickup=json.loads(Path(p).read_bytes())
    g=geometry(pickup['geometry']['id'])
    if g!=pickup['geometry']:raise TransferError('Accepted scanner pickup geometry changed.')
    return dict(geometry=g,acceptance_sha256=sha(ACCEPTANCE),scanner_z=163.76)


def retrieval(source,binding):
    from hotel_squid_composition import hotel,profile_binding
    module,workflow,g=hotel(1)
    source=Path(source).resolve()
    if source.parent!=module.OUTPUT.resolve():raise TransferError('Unknown hotel retrieval receipt.')
    d=json.loads(source.read_bytes())
    if (d.get('status')!='completed_retrieval_HOME_released_operator_observation_pending'
            or d['plan']['geometry']!=g
            or binding!=profile_binding('Cellvis P24-1.5H-N',1)
            or workflow['geometry_sha256']['retrieve']!=binding['geometry_sha256']):
        raise TransferError('Completed accepted slot-1 retrieval required.')
    if not 0<=time.time()-d['finished_at']<=1800:raise TransferError('Hotel retrieval receipt expired.')
    axes=d['final_native']['external_axes']
    if abs(axes['E1']-28)>.1 or not accepted(axes['E2']):raise TransferError('Hotel release/holder feedback mismatch.')
    near(d['final']['pose_mm'],g['home'],.05)
    return source,d


def create(source,binding,reference):
    source,d=retrieval(source,binding)
    if reference!=scanner_reference():raise TransferError('Scanner reference changed after approval.')
    near(d['final']['pose_mm'],reference['geometry']['station_clearance'],.05)
    # One handoff per actual retrieval, even after a process restart.
    folder=FOLDER/source.stem;folder.mkdir(parents=True,exist_ok=True)
    path=folder/'hotel_home.json'
    record=dict(status='hotel_retrieval_completed',payload='empty',source=str(source),
        source_sha256=sha(source),profile_binding=binding,reference=reference,
        final=d['final'],final_native=d['final_native'],finished_at=d['finished_at'],
        operator_observation='pending; not inferred from controller completion')
    with path.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    return path


def validate_source(path,d):
    path=Path(path).resolve()
    if path.parent.parent!=FOLDER.resolve() or path.name!='hotel_home.json':
        raise TransferError('Unknown hotel handoff.')
    source,original=retrieval(d['source'],d['profile_binding'])
    reference=scanner_reference()
    if (d.get('status')!='hotel_retrieval_completed' or d.get('payload')!='empty'
            or path.parent.name!=source.stem or d['source_sha256']!=sha(source)
            or d['reference']!=reference or d['final']!=original['final']
            or d['final_native']!=original['final_native'] or d['finished_at']!=original['finished_at']):
        raise TransferError('Hotel handoff evidence changed.')
    near(d['final']['pose_mm'],reference['geometry']['station_clearance'],.05)
    return reference['geometry']
