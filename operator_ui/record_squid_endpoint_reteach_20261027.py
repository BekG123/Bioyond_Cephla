"""Record the operator-adjusted Squid endpoint and check routes offline only."""
import json
import time
from datetime import datetime, timezone
from proof_lift_plate import api, write
from projected_pickup import ROOT, sha
from draggo import DragGoRPC
import prepare_squid_48well_endpoint as planner

FOLDER=ROOT/'operator_ui/reports/projected_alignment'
SOURCE=FOLDER/'squid_48well_endpoint_reteach_e2_20261027.json'
OUTPUT=FOLDER/'squid_48well_endpoint_reteach_e2_candidate_20261027.json'

def main():
    if SOURCE.exists() or OUTPUT.exists():
        raise RuntimeError('This teaching record already exists; preserve it.')
    samples=[]
    for _ in range(5):
        state=api('state');robot=state['robot'];native=DragGoRPC('192.168.201.220').info()
        if not robot.get('connected') or not robot.get('ok') or robot.get('errors') or state['sequence']['active'] or native['moving']:
            raise RuntimeError('Healthy stationary feedback required; no recovery.')
        if native['external_units'].get('E2')!='degrees' or abs(native['external_axes']['E2']-1.77)>.05:
            raise RuntimeError('E2 does not match the operator reference.')
        samples.append(dict(at=time.time(),state=state,native=native));time.sleep(.2)
    robot=samples[-1]['state']['robot'];endpoint=robot['pose_mm']
    for sample in samples:
        if any(abs(sample['state']['robot']['pose_mm'][k]-endpoint[k])>.05 for k in ('X','Y','Z','Rz')):
            raise RuntimeError('Arm moved during capture; no endpoint saved.')
    previous=FOLDER/'squid_48well_nearby_trial_20261027.json'
    old=dict(X=215.79,Y=374.70,Z=268.48,Rz=83.95)
    record=dict(at=time.time(),utc=datetime.now(timezone.utc).isoformat(),
        status='operator_taught_candidate_not_yet_tested',endpoint=endpoint,joints=robot['joints'],samples=samples,
        external_axes=samples[-1]['native']['external_axes'],external_units=samples[-1]['native']['external_units'],
        e2_target_degrees=1.77,hardware_commands_sent=False,
        previous_trial=dict(path=previous.relative_to(ROOT).as_posix(),sha256=sha(previous.read_bytes()),
            operator_feedback='Tilted or catching an edge. The endpoint was not correct. The placement was not successful.',
            seating_success=False),
        operator_instruction='Record the current position that I moved it to, we will attempt this endgoal.',
        delta_from_failed_endpoint={k:endpoint[k]-old[k] for k in old},
        current_plate_contact_state='not_confirmed_after_manual_adjustment',
        exact_endpoint_required=True,seating_verified=False)
    write(SOURCE,record)
    print(json.dumps(dict(record=str(SOURCE),endpoint=endpoint,external_axes=record['external_axes'],delta=record['delta_from_failed_endpoint'])),flush=True)
    planner.SOURCE=SOURCE;planner.OUTPUT=OUTPUT
    try:
        planner.main()
    except Exception as exc:
        # Preserve the teaching even if the proposed route cannot pass checks.
        blocked=OUTPUT.with_name(OUTPUT.stem+'_blocked.json')
        write(blocked,dict(at=time.time(),source=str(SOURCE),source_sha256=sha(SOURCE.read_bytes()),
            status='offline_check_blocked',error=str(exc),hardware_commands_sent=False))
        raise

if __name__=='__main__':main()
