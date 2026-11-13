"""Read and save the operator-taught pose; no motion or active route changes."""
import hashlib
import json
import time
from datetime import datetime, timezone
from projected_pickup import ROOT, PROFILE
from test_squid_destination_empty import api
from scope_step_trial import near

def main():
    first = api('state')
    time.sleep(.3)
    state = api('state')
    robot = state['robot']
    if not robot.get('connected') or robot.get('errors') or state['sequence']['active']:
        raise RuntimeError('Connected, idle, fault-free state required for capture')
    near(first['robot']['pose_mm'], robot['pose_mm'], .05)
    raw = PROFILE.read_bytes()
    profile = json.loads(raw)
    source = ROOT/'operator_ui/reports/squid_48well_approach/destination_leveled_20261101T103159Z.json'
    prior = json.loads(source.read_bytes())['routes']['forward'][-1]
    target = {k:robot['pose_mm'][k] for k in ('X','Y','Z','Rz')}
    stamp = datetime.now(timezone.utc)
    record = dict(status='operator_designated_ideal_pose_captured_not_deployed',
        captured_at=stamp.isoformat(), target=target, source_state=state,
        prior_destination=str(source), prior_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        delta_from_prior={k:target[k]-prior[k] for k in target},
        pickup_profile_sha256=hashlib.sha256(raw).hexdigest(),
        recorded_pickup_correction=profile['pickup_correction'],
        source_approach='loaded_trial_5db59c49149947c8b2ffff5174b946d0.json',
        operator_note='Save current coordinate as ideal; operator believes it resembles original +Y11.4 mm. Offset change not yet clarified.',
        observed_e1_mm=robot['external_axes']['E1'],
        limitations='Captured following manual positioning. Plate seating and any manual grip adjustment are not measured by this capture.',
        pickup_offset_changed=False, active_route_changed=False, hardware_motion_commands_sent=False)
    output=source.with_name('ideal_from_calibration_'+stamp.strftime('%Y%m%dT%H%M%SZ')+'.json')
    with output.open('x', encoding='utf-8') as stream:
        json.dump(record,stream,indent=2,allow_nan=False)
    print(json.dumps(dict(saved=str(output), target=target, delta=record['delta_from_prior'],
                         pickup_offset=profile['pickup_correction']['distance_mm'],e1=record['observed_e1_mm'])))

if __name__ == '__main__':
    main()
