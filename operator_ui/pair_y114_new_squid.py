"""Offline configuration change, preserving evidence; no hardware access."""
from copy import deepcopy
import json
from projected_pickup import ROOT, PROFILE, load, sha
from prepare_squid_destination import validate

def main():
    current = PROFILE.read_bytes()
    if sha(current) != '6118850380b7cd597bff9076be2b3719ea4314e94057d3db7a8a00ddbbb365ab':
        raise RuntimeError('Current pickup changed; review before applying')
    folder=ROOT/'operator_ui/reports/squid_48well_approach'
    taught_path=folder/'ideal_from_calibration_20261101T130737Z.json'
    taught=json.loads(taught_path.read_bytes())
    parent_path=folder/'destination_leveled_20261101T103159Z.json'
    if sha(parent_path.read_bytes()) != '255f431bf8eef3c100f9f163603d656fe666d9e825683f8d0f9e54850710047e':
        raise RuntimeError('Parent route changed')
    parent=json.loads(parent_path.read_bytes())
    target=taught['target']
    forward=deepcopy(parent['routes']['forward'])
    forward[-2]=dict(target,Z=forward[-2]['Z'])
    forward[-1]=target
    reverse=[target,dict(target,Z=target['Z']+5),*reversed(forward[:-1])]
    robot=taught['source_state']['robot']
    back=validate(reverse,robot['joints'],parent['cfg'],parent['envelope'])
    outward=validate(forward,back['final_joints'],parent['cfg'],parent['envelope'])
    if any(abs(outward['final_joints'][k]-robot['joints'][k])>.5 for k in robot['joints']):
        raise RuntimeError('Taught arrival winding mismatch')
    for path,initial in ((forward,back['final_joints']),(reverse,robot['joints'])):
        validate([{k:round(v,2) for k,v in p.items()} for p in path],initial,parent['cfg'],parent['envelope'])
    saved_profile=ROOT/'operator_ui/reports/projected_alignment/positive_y124_27612969ac91483cbc0059eadfad9677/previous_profile.json'
    profile,_=load(saved_profile)
    assert profile['pickup_correction']['distance_mm']==11.4
    expected=profile['pickup_correction']['source_endpoint']['Y']+11.4
    assert abs(profile['candidate_endpoint']['Y']-expected)<1e-9
    profile=deepcopy(profile)
    for key in ('accepted_grip_reference','accepted_grip_reference_sha256','descent_acceptance','descent_acceptance_sha256'):
        profile.pop(key,None)
    profile.update(descent_status='supervised_open_claw_trial_pending',
        physical_grip_validated_for_plate=False,current_placement_grip_tested=False,
        automatic_lift_enabled=False,full_pickup_verified=False)
    output=folder/'destination_calibration_y114_20261101.json'
    record=dict(status='offline_checked_pending_supervised_trial',
        parent=str(parent_path),parent_sha256=sha(parent_path.read_bytes()),
        taught_capture=str(taught_path),taught_capture_sha256=sha(taught_path.read_bytes()),
        source_state=taught['source_state'],cfg=parent['cfg'],envelope=parent['envelope'],
        routes=dict(forward=forward,reverse=reverse),validation=dict(forward=outward,reverse=back),
        pickup_offset_mm=11.4,pickup_at_capture_mm=12.2,
        change='Operator requested restoring +Y11.4 pickup and pairing it with newly taught Squid destination.',
        hardware_motion_commands_sent=False,collision_clearance_verified=False,
        combination_hardware_tested=False,
        limitations='Destination was taught with a +Y12.2 pickup and manually adjusted jaws. Compatibility with +Y11.4 requires a supervised trial.')
    backup=folder/'pickup_before_y114_new_squid_20261101.json'
    candidate=folder/'pickup_y114_new_squid_20261101.json'
    profile['squid_destination_candidate']=output.relative_to(ROOT).as_posix()
    for path,data in ((backup,current),(output,json.dumps(record,indent=2).encode()),
                      (candidate,json.dumps(profile,indent=2).encode())):
        with path.open('xb') as stream: stream.write(data)
    load(candidate)
    if PROFILE.read_bytes()!=current: raise RuntimeError('Active pickup changed')
    temporary=PROFILE.with_suffix('.paired.tmp')
    temporary.write_bytes(candidate.read_bytes())
    temporary.replace(PROFILE)
    print(json.dumps(dict(pickup=profile['candidate_endpoint'],destination=target,
        route=str(output),route_sha256=sha(output.read_bytes()),
        profile_sha256=sha(PROFILE.read_bytes()),hardware_commands=0,
        validation_samples=dict(forward=outward['sample_count'],reverse=back['sample_count']))))

if __name__=='__main__': main()
