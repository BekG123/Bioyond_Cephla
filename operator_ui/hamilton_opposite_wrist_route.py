"""Pinned dense-demonstration forward route, preserving positive wrist winding."""
import hashlib
import json
from pathlib import Path
from autonomy import TransferError
from plan_hamilton_smooth_transit import PLAN as PARENT

SESSION=Path(__file__).resolve().parent/'reports/plate_session/hamilton_reteach_dense_1794445845223043300'
ORIGINAL_PLAN=SESSION/'opposite_wrist_runtime_plan.json'
UNBLENDED_PLAN=SESSION/'opposite_wrist_z77_runtime_plan.json'
LEGACY_BLEND_PLAN=SESSION/'opposite_wrist_z77_blended_runtime_plan.json'
PLAN=SESSION/'opposite_wrist_z82_rounded_runtime_plan.json'
REVISION=SESSION/'final_turn_z77_ik.json'
SOURCES={
    'opposite_wrist_ik.json':'bc5aee21728fa5c1485d19ebb10113b7427af4722c472bf02430f14d8d850cb7',
    'selected_three_travel_plan.json':'c3826b8763aefeac9af5e626d3befe35824d0b86b8246ae98d9211a046becf91',
    'samples.jsonl':'1739ccefa37777d0e4d107905ffc21fe8c0de87ef1fa39faf12c14426cdfa65d',
}


def build_original():
    for name,digest in SOURCES.items():
        if hashlib.sha256((SESSION/name).read_bytes()).hexdigest()!=digest:
            raise TransferError('Opposite-wrist teaching evidence changed: '+name)
    if hashlib.sha256(PARENT.read_bytes()).hexdigest()!='f47fd3e7fd2a47fb89cb4375521b3c3c206e6f833846bd86749362c18d0af949':
        raise TransferError('Opposite-wrist parent route changed.')
    source=json.loads((SESSION/'opposite_wrist_ik.json').read_bytes())
    selected=json.loads((SESSION/'selected_three_travel_plan.json').read_bytes())
    parent=json.loads(PARENT.read_bytes());candidate=source['candidates'][selected['selected']]
    points=candidate['points'];start=source['home_start'];joints=parent['routes']['forward']['start_joints']
    if len(points)!=6 or points[1:4]!=selected['travel_waypoints'] or not candidate['valid']:
        raise TransferError('Expected selected three-travel-target candidate.')
    return dict(status='prepared_for_first_supervised_trial',hardware_tested=False,
        source_hashes=SOURCES,config=source['config'],global_envelope=parent['global_envelope'],
        station_envelope=source['station_envelope'],transit_targets=points[1:4],
        comparison=dict(length_mm=candidate['forward']['length_mm'],
                        max_recorded_xyz_deviation_mm=candidate['max_recorded_xyz_deviation_mm'],
                        max_recorded_yaw_deviation_deg=candidate['max_recorded_yaw_deviation_deg']),
        routes=dict(forward=dict(start=start,start_joints=joints,points=points,
            segment_speeds=candidate['segment_speeds'],validation=candidate['forward']),
            reverse=dict(start=points[-1],start_joints=candidate['forward']['endpoint_joints'],
                points=list(reversed([start]+points))[1:],segment_speeds=[5]+[137]*5,
                validation=candidate['reverse'],execution_enabled=False)),
        note='Forward delivery only. Three travel targets, separate lift and descent phases. Positive yaw/J4 winding. Reverse is offline evidence only.')


def build_legacy():
    """Same Z77 route, with bounded blending only at its level turn junction."""
    original=build_original()
    if hashlib.sha256(ORIGINAL_PLAN.read_bytes()).hexdigest()!='f06fe6c51c2ac087e676dfa7c7eba43bbdb6b58e10296ee128a3efa8cb8b28d9':
        raise TransferError('Original opposite-wrist route changed.')
    if json.loads(ORIGINAL_PLAN.read_bytes())!=original:
        raise TransferError('Original opposite-wrist evidence changed.')
    if hashlib.sha256(REVISION.read_bytes()).hexdigest()!='abda35c7f6abfa0225f408a655a85523e8c1a1d53e2b551f0597637ab459d160':
        raise TransferError('Z77 revision evidence changed.')
    evidence=json.loads(REVISION.read_bytes())
    candidate=evidence['candidates']['final_turn_z77']
    old=original['routes']['forward'];points=candidate['points']
    expected=old['points'][:3]+[dict(old['points'][2],Z=77.),dict(old['points'][3],Z=77.),old['points'][-1]]
    if points!=expected or not candidate['valid']:
        raise TransferError('Expected final-turn-only Z77 correction.')
    if hashlib.sha256(UNBLENDED_PLAN.read_bytes()).hexdigest()!='25ffafe91d88d89be1b7ef4f7907ca3b95ea9aeba75f7ce688e4c470e864f675':
        raise TransferError('Unblended Z77 parent changed.')
    if json.loads(UNBLENDED_PLAN.read_bytes())['routes']['forward']['points']!=points:
        raise TransferError('Blend revision must preserve the Z77 waypoints.')
    original.update(parent_sha256=evidence['parent_sha256'],revision_sha256=hashlib.sha256(REVISION.read_bytes()).hexdigest(),
        unblended_parent_sha256=hashlib.sha256(UNBLENDED_PLAN.read_bytes()).hexdigest(),
        transit_targets=[points[i] for i in (1,2,4)],
        comparison=dict(length_mm=candidate['forward']['length_mm'],parent_length_mm=old['validation']['length_mm']),
        executor=dict(protocol=220109,optional_capability=220113,segment_zones=[-1,1,-1,-1,-1,-1],completion_barriers=1,new_lua_required=True),
        note='Z77 waypoints unchanged. One queue with 1mm blend at the first level turn junction. Complete the second turn before lowering; reach Z77 before final turn/crossing; seating stays exact. Requires updated existing trajectory module220113. Physical blending/clearance untested. Reverse remains offline only.')
    original['routes']['forward']=dict(old,points=points,segment_speeds=candidate['segment_speeds'],validation=candidate['forward'])
    original['routes']['reverse']=dict(start=points[-1],start_joints=candidate['forward']['endpoint_joints'],
        points=list(reversed([old['start']]+points))[1:],segment_speeds=[5]+[137]*5,
        validation=candidate['reverse'],execution_enabled=False)
    return original


def build():
    legacy=build_legacy()
    if hashlib.sha256(LEGACY_BLEND_PLAN.read_bytes()).hexdigest()!='f8eb1ed605785b7108119b2caddc61ad45a9cdda6ac902aee583ad29ed7a1808' or json.loads(LEGACY_BLEND_PLAN.read_bytes())!=legacy:
        raise TransferError('Accepted Z77 parent changed.')
    legacy.update(status='integrated_native_blend_pending_physical_trial',hardware_tested=False,
        rounded_parent_sha256=hashlib.sha256(LEGACY_BLEND_PLAN.read_bytes()).hexdigest(),
        executor=dict(protocol=220109,optional_capability=220114,
            segment_zones={'forward':[-1,1,1,5,-1,-1],'reverse':[-1,5,1,1,-1,-1]},
            completion_barriers=1,new_lua_required=True,requested_final_turn_ceiling_mm=82,
            interpolation='vendor_native_MoveL_blending_not_exact_Bezier'),
        note='Same pinned endpoints and opposite wrist winding, native 1mm upper-corner and 5mm final-corner zones in both directions. Main crossing Z77. Slow seating/departure unchanged. Z82 is monitored; vendor zone length alone does not certify onset. Physical curve/clearance validation pending.')
    legacy['routes']['reverse']['execution_enabled']=True
    return legacy


if __name__=='__main__':
    with PLAN.open('x') as stream:json.dump(build(),stream,indent=2,allow_nan=False)
    print(PLAN)
