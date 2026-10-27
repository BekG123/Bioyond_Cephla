"""Archive this supervised calibration result; never sends motion commands."""
import hashlib,json,math,time
from pathlib import Path
from urllib.request import urlopen
import numpy as np

ROOT=Path(__file__).resolve().parents[1]

def pinned(path):
    return dict(path=path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(path.read_bytes()).hexdigest())

def main():
    log=ROOT/'operator_ui/reports/projected_disk_pilot/20261027_004018_c770a647.jsonl'
    rows=[json.loads(line) for line in log.read_text().splitlines()]
    final=rows[-1]['result']
    assert final['ok'] and final['xy_centered'] and not final['motion_requested']
    observations=[r['measurement'] for r in rows if r['event']=='observation']
    assert len(observations)==6
    errors=np.array([r['error_xy_mm'] for r in observations])
    assert max(np.linalg.norm(e) for e in errors)<=.75
    spread=max(np.linalg.norm(a-b) for a in errors for b in errors)
    assert spread<=.25
    with urlopen('http://127.0.0.1:5002/state',timeout=8) as response:state=json.load(response)
    robot=state['robot']
    assert robot.get('connected') and robot.get('ok') and not robot.get('errors') and not state['sequence']['active']
    assert all(abs(robot['pose_mm'][k]-final['final_pose'][k])<.1 for k in ('X','Y','Z','Rz'))
    assert abs(robot['pose_mm']['Z']-289.129)<.1
    preview=ROOT/'operator_ui/reports/projected_alignment/prepared_route_20261027_repeat.json'
    reviewed=json.loads(preview.read_bytes())
    accepted=ROOT/'operator_ui/reports/projected_alignment/accepted_round_20261026.json'
    old=json.loads(accepted.read_bytes())['alignment_pose_mm'];new=reviewed['route']['target']
    report=dict(schema='cephla.projected-calibration-repeat.v1',at=time.time(),
        status='camera_centering_and_saved_observation_height_verified',
        final_pose=robot['pose_mm'],final_error_xy_mm=final['after']['error_xy_mm'],
        final_estimated_error_mm=float(np.linalg.norm(errors[-1])),
        stationary_observations=6,stationary_error_max_difference_mm=float(spread),
        supported_wells=[r['tracking']['supported_wells'] for r in observations],
        independent_absolute_depth_verified=False,alignment_executed=False,descent_executed=False,grip_executed=False,
        observed_new_alignment=new,previous_accepted_alignment=old,
        alignment_change_mm=math.hypot(new['x']-old['X'],new['y']-old['Y']),
        alignment_change_deg=(new['rz']-old['Rz']+180)%360-180,
        descent_candidate_status='Old 2 mm inward candidate retained, not activated; do not apply to the changed alignment estimate.',
        method=['Returned to true Home using the existing Lacry IK route.',
            'Preserved measured well-grid initialization; added bounded rotation-aware whole-plate fallback only when grid initialization fails.',
            'Preserved independent well-group, distributed support, geometry, motion-response and controller checks.',
            'Z268 view approached the frame edge; moved vertically at speed 5 to the already verified observation reference Z289.129.',
            'Used the pinned height-matched image reference and bounded XY corrections; six stationary final observations passed.'],
        limitations=['This run included reviewed failures and a reference-height change; it was not an uninterrupted unattended full pickup.',
            'New alignment differs from the accepted pose and has not been physically executed or visually accepted.'],
        final_evidence=pinned(log),alignment_preview=pinned(preview),previous_acceptance=pinned(accepted),
        home_evidence=pinned(max((ROOT/'operator_ui/reports/ik_home').glob('*.json'),key=lambda p:p.stat().st_mtime)),
        trials=[pinned(p) for p in sorted((ROOT/'operator_ui/reports/projected_disk_pilot').glob('20261027_00*.jsonl')) if p.name>='20261027_002808'],
        source=[pinned(ROOT/name) for name in ['Pick and Hold/Align/plate_pose/grid_rotation_seed.py',
            'Pick and Hold/Align/plate_pose/grid_pattern.py','operator_ui/projected_disk_trial.py']],
        controller_errors=robot['errors'])
    out=ROOT/'operator_ui/reports/projected_disk_pilot/calibration_verified_20261027.json'
    out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['status','final_pose','final_estimated_error_mm',
        'stationary_error_max_difference_mm','supported_wells','alignment_change_mm','alignment_change_deg']}))
    print(str(out))

if __name__=='__main__':main()
