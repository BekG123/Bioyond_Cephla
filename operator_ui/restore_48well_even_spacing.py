"""Restore the recorded 25/25 mm gap reference after the failed manual trial.

File changes only. Retain Z73.718; do not add another radial/forward offset.
"""
import json
import time
from copy import deepcopy
import projected_pickup as p
from correct_48well_centering import save


def main():
    current,digest=p.load()
    if (current.get('manual_alignment')!='operator_ui/reports/projected_alignment/manual_alignment_teaching_20261027.json'
            or any(current['candidate_endpoint'][k]!=v for k,v in
                   dict(X=308.971,Y=-64.539,Z=73.718,Rz=89.439).items())):
        raise p.TransferError('Source manual trial changed; review before replacement.')
    source=p.ROOT/'operator_ui/reports/projected_alignment/restored_centering_lower_candidate_20261027.json'
    baseline,baseline_sha=p.load(source)
    if baseline_sha!='7a6b065a536254e0f2b9ad6512267a144bd22f08f44c4b4b93b03603589a509a':
        raise p.TransferError('Known even-spacing reference changed.')
    backup,backup_sha=save('profile_after_manual_grip_fault_20261027.json',current)
    feedback,feedback_sha=save('restore_even_spacing_request_20261027.json',dict(
        at=time.time(),operator_feedback='Manual alignment did not retain 25 mm on each side. Reset performed by operator; return Home and repeat using the recorded even-spacing alignment.',
        previous_profile=backup,previous_profile_sha256=backup_sha,
        failed_grip_record='operator_ui/demonstrations/reference_grip/7a2e0ac419274311a5849fbc71e3ac38.json',
        restored_profile=source.relative_to(p.ROOT).as_posix(),restored_profile_sha256=baseline_sha,
        candidate_endpoint=baseline['candidate_endpoint'],
        prior_open_gap_report_mm=[25,25],combined_endpoint_verified=False,
        automatic_grip=False,motion_started=False))
    candidate=deepcopy(baseline)
    candidate.update(previous_profile=backup,previous_profile_sha256=backup_sha,
        correction_feedback=feedback,correction_feedback_sha256=feedback_sha,
        alignment_source='Exact recorded 25/25 mm open-gap reference; no cumulative offsets',
        forward_adjustment_pending_mm=0.,
        candidate_z_basis='Retain accepted Z73.718; open-claw inspection required with restored even-spacing XY/yaw.')
    path,new_sha=save('even_spacing_repeat_profile_20261027.json',candidate)
    p.load(p.ROOT/path)
    temp=p.PROFILE.with_suffix('.tmp');temp.write_bytes((p.ROOT/path).read_bytes());temp.replace(p.PROFILE)
    print(json.dumps(dict(profile_sha256=new_sha,endpoint=candidate['candidate_endpoint'],motion_started=False)))


if __name__=='__main__':main()
