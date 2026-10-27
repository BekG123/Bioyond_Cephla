"""Record the 2026-10-27 supervised repeat from existing evidence; no motion."""
import hashlib
import json
import math
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]

def main():
    folder=ROOT/'operator_ui/reports/projected_disk_pilot'
    paths=sorted(folder.glob('20261027_00*.jsonl'))
    trials=[]
    for path in paths:
        rows=[json.loads(line) for line in path.read_text().splitlines()]
        result=rows[-1].get('result',{})
        observations=[r for r in rows if r['event']=='observation']
        moved=any(r['event']=='movement_requested' for r in rows)
        trials.append(dict(path=path.relative_to(ROOT).as_posix(),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            ok=result.get('ok'),motion_requested=moved,
            error=result.get('error'),final_pose=result.get('final_pose'),
            last_observation_pose=observations[-1]['pose'] if observations else None,
            last_observed_error_xy_mm=observations[-1]['measurement']['error_xy_mm'] if observations else None,
            last_observed_supported_wells=observations[-1]['measurement']['tracking']['supported_wells'] if observations else None))
    assert trials and trials[-1]['ok'] is False
    home_path=max((ROOT/'operator_ui/reports/ik_home').glob('*.json'),key=lambda p:p.stat().st_mtime)
    home=json.loads(home_path.read_bytes())
    with urlopen('http://127.0.0.1:5002/state',timeout=8) as response:state=json.load(response)
    assert not state['sequence']['active']
    report=dict(date='2026-10-27',task='True Home then fresh 48-well calibration',
        home_evidence=dict(path=home_path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(home_path.read_bytes()).hexdigest(),record=home),
        observation_lift=dict(target_z_mm=268.02,speed=5,reported_arrival_z_mm=268.024),
        trials=trials,verified_xy_moves=sum(t['ok'] is True and t['motion_requested'] for t in trials),
        moves_with_failed_post_verification=sum(t['ok'] is False and t['motion_requested'] for t in trials),
        last_single_observation_error_mm=math.hypot(*trials[-1]['last_observed_error_xy_mm']),
        stopped_state=state,calibration_complete=False,alignment_run=False,descent_run=False,grip_run=False,
        diagnosis='Grid reacquisition failed on most stopped post-move image bursts. One final measurement passed, insufficient for the three-consecutive-observation requirement. No controller fault.',
        correction_status='2 mm base-directed descent candidate retained separately; not activated or trialed.',
        last_motion_note='No further motion requested after the failed image verification.')
    out=folder/'repeat_from_home_20261027.json'
    out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(report=str(out),verified_xy_moves=report['verified_xy_moves'],
        moves_with_failed_post_verification=report['moves_with_failed_post_verification'],
        last_single_observation_error_mm=report['last_single_observation_error_mm'],
        current_pose=state['robot'].get('pose_mm'),errors=state['robot'].get('errors'))))

if __name__=='__main__':main()
