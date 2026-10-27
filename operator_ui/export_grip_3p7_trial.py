"""Export this supervised trial and stationary telemetry; no movement commands."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from execute_alignment_home import api

ROOT = Path(__file__).resolve().parents[1]


def main():
    state, sequence = api('/state'), api('/seq')
    result = sequence.get('result') or {}
    if (sequence.get('active') or sequence.get('name') != 'position_grip'
            or result.get('ok') is not True or result.get('target_e1_mm') != 3.7
            or state['robot']['errors']):
        raise RuntimeError('Require completed, fault-free 3.7 mm trial.')
    source = Path(result['record']).resolve()
    if source.parent != ROOT/'operator_ui/demonstrations/reference_grip':
        raise RuntimeError('Unexpected trial record.')
    grip = json.loads(source.read_bytes())
    samples = []
    for _ in range(3):
        current = api('/state')
        if current['sequence']['active'] or current['robot']['errors']:
            raise RuntimeError('State changed; telemetry review stopped.')
        for axis in ('X', 'Y', 'Z', 'Rz'):
            if abs(current['robot']['pose_mm'][axis]-grip['pose_mm'][axis]) > .05:
                raise RuntimeError('Arm moved; torque no longer matches grip pose.')
        report = api('/gripper', {'action': 'torque'})
        if (not report.get('ok') or report.get('telemetry_live') is not True
                or abs(report['e1_position']-3.7) > .05):
            raise RuntimeError('Fresh stationary torque unavailable.')
        samples.append(report)
        time.sleep(.2)
    audit = api('/audit/status')
    session = ROOT/'operator_ui/logs/audit'/audit['session']
    workflows = []
    for path in sorted(session.glob('events_*.jsonl')):
        with path.open('rb') as stream:
            for line in stream:
                if not line.endswith(b'\n'):
                    break
                event = json.loads(line)
                if event.get('event') == 'classic_pickup_finished':
                    workflows.append(event)
    record = dict(
        at=datetime.now(timezone.utc).isoformat(),
        authorization='e1_3p7_20261020.json',
        status='closure_completed_awaiting_visual_inspection',
        operator_contact_clearance='Plate flat in holder; jaws free; hands clear; E-stop supervised',
        home_return_before_calibration_completed=True,
        home_return_plan_id='2026-10-20T09:13:35.011383+00:00:1792487615011',
        grip_record=source.relative_to(ROOT).as_posix(),
        workflow=workflows[-1] if workflows else None,
        audit_session=audit['session'],
        final_state=api('/state'),
        stationary_torque_samples=samples,
        mean_stationary_e1_torque_raw=sum(x['e1_torque'] for x in samples)/len(samples),
        force_limits_changed=False, force_target=None,
        lift_started=False, grasp_verified=False,
        limitation='Controller torque units are raw; these observations do not establish grip strength.')
    output = source.parent/'e1_3p7_20261020_result.json'
    with output.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, indent=2, allow_nan=False)
    print(json.dumps(dict(file=str(output), torque_samples=samples,
                         mean_torque_raw=record['mean_stationary_e1_torque_raw'])))


if __name__ == '__main__':
    main()
