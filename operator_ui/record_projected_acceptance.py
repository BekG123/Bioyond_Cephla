"""Record the operator-accepted 48-well trial; offline, no hardware access."""
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
PROFILE=ROOT/'Pick and Hold/Calibration/plate_48_pickup_profile.json'
LOG=ROOT/'operator_ui/reports/projected_alignment/20261026_232305_920d2cde.jsonl'

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    rows=[json.loads(line) for line in LOG.read_text().splitlines()]
    result=rows[-1]['result']
    assert rows[-1]['event']=='completed' and result['ok'] and result['alignment_pose_reached']
    assert not result['descent_executed'] and not result['grip_executed']
    height=ROOT/'Pick and Hold/Calibration/plate_48_height_reference_20261026.json'
    old=ROOT/'Pick and Hold/Descend/corrected_endpoint.json'
    endpoint=json.loads(old.read_bytes())['endpoint']
    aligned=result['pose']
    acceptance=dict(schema='cephla.projected-plate-acceptance.v1',
        id='48_well_calibration_alignment_20261026',recorded_at=datetime.now(timezone.utc).isoformat(),
        status='operator_accepted_calibration_and_alignment_round',
        operator_feedback='Yes! Great job; save this as a successful calibration and alignment round.',
        plate=dict(wells=48,rows=6,columns=8,height_mm=20,original_height_mm=15,same_support=True),
        observation_height_mm=289.129,alignment_pose_mm=aligned,
        physical_alignment_executed=True,visual_alignment_accepted=True,
        independent_absolute_depth_verified=False,gripping_height_verified=False,
        descent_verified=False,grip_verified=False,full_pickup_verified=False,
        methods=['Track the real 6x8 well pattern using frozen image references and independent well-group registration.',
                 'Project the original two disk landmarks through the measured image transform; never use virtual radius as depth.',
                 'Transfer the original observation height by the measured +5 mm plate height on the same support.',
                 'Use a fixed image at the verified height, retaining all eight upstream/current transform combinations.',
                 'Use vendor Wide XY/yaw and camera-to-claw transforms, then the existing guarded IK alignment at Z300.'],
        lessons=['A large total well count alone is insufficient; check spatial coverage and independent transform agreement.',
                 'Height changes can alter blur/reflections enough to invalidate the earlier fixed-height photometric reference.',
                 'A validated height-matched reference recovered 48/48 wells without relaxing uncertainty limits.',
                 'The accepted round includes reviewed intermediate failures; it is not proof of an unattended repeat from Home.',
                 'Plate-top height, jaw-contact height and secure grip are separate quantities; the last two await a physical trial.'],
        evidence=[dict(path=p.relative_to(ROOT).as_posix(),sha256=digest(p)) for p in (LOG,height)])
    out=ROOT/'operator_ui/reports/projected_alignment/accepted_round_20261026.json'
    out.write_text(json.dumps(acceptance,indent=2),encoding='utf-8')
    profile=dict(schema='cephla.projected-pickup-profile.v1',id='48_well_projected_20261026',
        acceptance=out.relative_to(ROOT).as_posix(),acceptance_sha256=digest(out),
        alignment_log=LOG.relative_to(ROOT).as_posix(),alignment_log_sha256=digest(LOG),
        alignment_pose_mm=aligned,descent_status='pending_supervised_open_claw_trial',
        gripping_edge_height='unknown; operator requested supervised verification',
        candidate_endpoint=dict(X=aligned['X'],Y=aligned['Y'],Z=endpoint['Z']+5,Rz=aligned['Rz']),
        candidate_z_basis='Trial candidate only: old taught jaw height +5 mm top-height difference; not a measured gripping height.',
        parent_descent=old.relative_to(ROOT).as_posix(),parent_descent_sha256=digest(old),
        descent_algorithm='existing ResearcherDescent + LuaDescent; open to E1=28, approach137, final20mm at5',
        grip_algorithm='existing ReferenceGrip; staged 1.0/0.2/0.1 mm closure at speed5 to E1=3.7',
        automatic_lift_enabled=False,full_pickup_verified=False)
    if PROFILE.exists():raise RuntimeError('Profile already exists; do not overwrite subsequent trial acceptance.')
    PROFILE.write_text(json.dumps(profile,indent=2),encoding='utf-8')
    print(json.dumps(dict(acceptance=str(out),profile=str(PROFILE),candidate=profile['candidate_endpoint'])))

if __name__=='__main__':main()
