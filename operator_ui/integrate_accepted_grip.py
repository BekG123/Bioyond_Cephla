"""Install operator-requested profiles offline; never connects to hardware."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRIP = ROOT/'Pick and Hold/Grip'
DESCENT = ROOT/'Pick and Hold/Descend/corrected_endpoint.json'


def write(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def main():
    reference_path = GRIP/'accepted_grip_reference.json'
    reference = json.loads(reference_path.read_bytes())
    archive = GRIP/'accepted_grip_previous_descent.json'
    if archive.exists():
        raise RuntimeError('Integration already prepared; review before repeating.')
    old_raw = DESCENT.read_bytes()
    old = json.loads(old_raw)
    archive.write_bytes(old_raw)
    old_rel = DESCENT.relative_to(ROOT).as_posix()
    archived_rel = archive.relative_to(ROOT).as_posix()
    for item in reference['evidence']:
        if item['path'] == old_rel:
            assert item['sha256'] == hashlib.sha256(old_raw).hexdigest()
            item['path'] = archived_rel
    reference['integration']['descent_profile']['path'] = archived_rel
    # The reference remains historical evidence, distinct from current activation.
    write(reference_path, reference)
    evidence = dict(
        kind='operator_accepted_grip_endpoint',
        endpoint={k:reference['closure']['pose_mm_degrees'][k] for k in ('X','Y','Z','Rz')},
        vision_reference_z_mm=old.get('vision_reference_z_mm', old['endpoint']['Z']),
        prior_descent_profile=archived_rel,
        prior_descent_sha256=hashlib.sha256(old_raw).hexdigest(),
        grip_reference=reference_path.relative_to(ROOT).as_posix(),
        grip_reference_sha256=hashlib.sha256(reference_path.read_bytes()).hexdigest(),
        operator_instruction='Integrate the new grip reference into full calibration and integrate the new descent-pose',
        scope='Fixed endpoint accepted during grip tests; no claim that the newly placed plate matches until fresh calibration checks pass.')
    evidence_path = GRIP/'accepted_descent_endpoint.json'
    write(evidence_path, evidence)
    current = dict(old, id='accepted_grip_endpoint_20261020',
                   endpoint=evidence['endpoint'],
                   vision_reference_z_mm=evidence['vision_reference_z_mm'],
                   evidence=evidence_path.relative_to(ROOT).as_posix(),
                   evidence_sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                   note='Operator accepted endpoint used for even 3.8 mm grip and loaded Home transfer. Correct above plate at Z300; descend to this fixed endpoint. Preserve the previous vision-height band.')
    write(DESCENT, current)
    profile_path = GRIP/'fast_position_profile.json'
    profile = json.loads(profile_path.read_bytes())
    profile.update(live_enabled=True, status='integrated_for_supervised_validation',
                   physical_full_approach_validated=False,
                   activation_utc=datetime.now(timezone.utc).isoformat())
    write(profile_path, profile)
    print(json.dumps(dict(endpoint=current['endpoint'], vision_reference_z_mm=current['vision_reference_z_mm'],
                          old_endpoint_preserved=str(archive), supervised_trial=True), indent=2))


if __name__ == '__main__':
    main()
