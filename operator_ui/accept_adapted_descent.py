"""Promote the visually accepted trial to the shared GUI descent profile. No motion."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path

from execute_alignment_home import api
from pick_and_hold.Descend.correction import PROFILE, corrected_plan

ROOT=Path(__file__).resolve().parents[1]


def main(folder, feedback):
    FOLDER=Path(folder).resolve()
    if FOLDER.parent != (ROOT/'operator_ui/reports/descent_trials').resolve():
        raise RuntimeError('Use a saved descent trial folder.')
    if not feedback.strip():
        raise RuntimeError('Explicit operator visual acceptance is required.')
    state=api('/state')
    if state['sequence']['active']:
        raise RuntimeError('Wait until the active action is finished.')
    review_raw=(FOLDER/'review.json').read_bytes()
    trial_raw=(FOLDER/'trial_attempt.json').read_bytes()
    candidate_raw=(FOLDER/'candidate_profile.json').read_bytes()
    review,trial,candidate=map(json.loads,(review_raw,trial_raw,candidate_raw))
    if (trial['status']!='completed_awaiting_visual_inspection'
            or trial.get('result',{}).get('ok') is not True
            or not trial.get('baseline_restored')
            or trial['review_sha256']!=hashlib.sha256(review_raw).hexdigest()
            or review['candidate_sha256']!=hashlib.sha256(candidate_raw).hexdigest()):
        raise RuntimeError('Successful trial provenance could not be verified.')
    original=(FOLDER/'original_profile_bytes.json').read_bytes()
    if PROFILE.read_bytes()!=original:
        raise RuntimeError('Active profile changed; do not overwrite another update.')
    acceptance=dict(schema='cephla.descent-visual-acceptance.v1',
        recorded_at=datetime.now(timezone.utc).isoformat(),
        operator_feedback=feedback,
        operator_instruction='Save the visually accepted adapted descent.',
        visually_accepted=True, controller_descent_verified=True, grip_validated=False,
        endpoint=candidate['endpoint'],
        trial=str((FOLDER/'trial_attempt.json').relative_to(ROOT)),
        trial_sha256=hashlib.sha256(trial_raw).hexdigest(),
        candidate_sha256=hashlib.sha256(candidate_raw).hexdigest(),
        original_profile_sha256=hashlib.sha256(original).hexdigest(),
        scope='Current two-disk plate placement, orientation and support surface only.',
        integration='Shared ResearcherDescent profile used by standalone Descend and Full Calibration.')
    evidence_path=FOLDER/'visual_acceptance.json'
    with evidence_path.open('x',encoding='utf-8') as stream:
        json.dump(acceptance,stream,indent=2,allow_nan=False)
    candidate.update(scope=acceptance['scope'],
        evidence=evidence_path.relative_to(ROOT).as_posix(),
        evidence_sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        note='Supervised descent completed and operator visually accepted jaw alignment. GUI default: correct at Z300, verify fully open claws, descend at 137 with final 20 mm at 5. No automatic cumulative offset. Grip not validated by this trial.')
    accepted_path=FOLDER/'accepted_profile.json'
    with accepted_path.open('x',encoding='utf-8') as stream:
        json.dump(candidate,stream,indent=2,allow_nan=False)
    r=review['state']['robot']
    plan=corrected_plan(r['pose_mm'],r['joints'],review['state']['target'],
        review['config'],review['envelope'],review['band'],profile_path=accepted_path)
    if plan['endpoint']!=review['plan']['endpoint'] or plan['legs']!=review['plan']['legs']:
        raise RuntimeError('Promotion changed the tested geometry.')
    if api('/state')['sequence']['active'] or PROFILE.read_bytes()!=original:
        raise RuntimeError('State changed during promotion.')
    temporary=PROFILE.with_suffix('.accepted-tmp')
    temporary.write_bytes(accepted_path.read_bytes())
    os.replace(temporary,PROFILE)
    live_plan=corrected_plan(r['pose_mm'],r['joints'],review['state']['target'],
        review['config'],review['envelope'],review['band'])
    assert live_plan['endpoint']==review['plan']['endpoint']
    assert live_plan['legs']==review['plan']['legs']
    print(json.dumps(dict(gui_default_updated=True,profile=str(PROFILE),
        endpoint=live_plan['endpoint'],matches_tested_path=True,
        acceptance=str(evidence_path),robot_commands_sent=False,reload_required=False),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder')
    parser.add_argument('--feedback',required=True)
    args=parser.parse_args()
    main(args.folder,args.feedback)
