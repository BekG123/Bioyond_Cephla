"""Offline comparison of successful Squid replay and calibration pickup transfer."""
import hashlib
import json
from pathlib import Path
from prepare_squid_destination import validate

ROOT = Path(__file__).resolve().parent / 'reports/squid_48well_approach'
def read(name):
    return json.loads((ROOT / name).read_bytes())
def delta(a, b):
    return {k: a[k] - b[k] for k in b if k in a}

def main():
    batch_name = 'repeatability_five_f3a19c71c8dc4a99b1b33bf8b8429d84.json'
    accepted_name = batch_name.replace('.json', '_operator_acceptance.json')
    recent_name = 'loaded_trial_57d0a25916d743b78968b2edcc77bbaf.json'
    route_name = 'destination_leveled_20261101T103159Z.json'
    batch, accepted, recent, route = map(read, (batch_name, accepted_name, recent_name, route_name))
    assert accepted['status'] == 'operator_accepted_five_successful_cycles'
    route_sha = hashlib.sha256((ROOT / route_name).read_bytes()).hexdigest()
    assert route_sha == batch['candidate_sha256'] == recent['candidate_sha256']
    successful = read(Path(batch['cycles'][0]['artifacts'][0]['path']).name)
    before = successful['source_state']['robot']
    after = recent['source_state']['robot']
    path = [after['pose_mm'], *route['routes']['forward'][1:]]
    checked = validate(path, after['joints'], route['cfg'], route['envelope'])
    report = dict(
        status='offline_comparison_complete_no_motion',
        source_hashes={n: hashlib.sha256((ROOT/n).read_bytes()).hexdigest()
                       for n in (batch_name, accepted_name, recent_name, route_name)},
        successful_home=before['pose_mm'], calibration_home=after['pose_mm'],
        home_delta=delta(after['pose_mm'], before['pose_mm']),
        home_joint_delta=delta(after['joints'], before['joints']),
        successful_arrival=successful['final_robot']['pose_mm'],
        recent_arrival=recent['final_robot']['pose_mm'],
        arrival_delta=delta(recent['final_robot']['pose_mm'], successful['final_robot']['pose_mm']),
        home_e1_mm=dict(successful=before['external_axes']['E1'], recent=after['external_axes']['E1']),
        successful_taught_destination=route['routes']['forward'][-1],
        route_preview_from_calibration_home=path, offline_validation=checked,
        same_route_sha256=route_sha,
        conclusion='Recorded Home and destination already match the successful taught route; no new geometric connector is justified by these measurements.',
        limitations=['Robot poses do not measure plate seating, tilt or plate-to-gripper transform.',
                     'IK validation does not establish collision clearance.',
                     'Recent transfer reached its commanded pose but operator rejected placement.'],
        required_next_evidence='Measure plate seating/pose relative to claws, or teach a corrected dropoff while holding a plate from the current calibration pickup.',
        hardware_commands=0)
    output=ROOT/'calibration_home_comparison_20261101.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(report=str(output), home_delta=report['home_delta'],
        home_joint_delta=report['home_joint_delta'], arrival_delta=report['arrival_delta'],
        validation_samples=checked['sample_count'], hardware_commands=0), indent=2))

if __name__ == '__main__':
    main()
