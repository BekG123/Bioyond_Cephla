"""Archive a completed repeat without enabling Grip or sending hardware commands."""
import argparse,json,time
from urllib.request import urlopen
from projected_pickup import ROOT,load,sha
from autonomy import ensure_arrival

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calibration-log',required=True)
    parser.add_argument('--alignment-plan',default='operator_ui/reports/projected_alignment/corrected_repeat_plan_20261027.json')
    parser.add_argument('--output',default='operator_ui/reports/projected_alignment/corrected_full_repeat_20261027.json')
    parser.add_argument('--new-placement-trial',action='store_true')
    args=parser.parse_args()
    log=ROOT/args.calibration_log
    events=[json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    final=events[-1]['result']
    assert final['ok'] and final['xy_centered']
    with urlopen('http://127.0.0.1:5002/state',timeout=8) as response:s=json.load(response)
    with urlopen('http://127.0.0.1:5002/seq',timeout=8) as response:q=json.load(response)
    p,digest=load()
    assert not q['active'] and q['name']=='researcher_descend' and q['state']=='done'
    assert q['result']['ok'] and q['result']['open_claw_trial']
    assert q['result']['descent_correction']['profile_sha256']==digest
    assert s['robot'].get('connected') and not s['robot']['errors']
    assert 27.98<=s['robot']['external_axes']['E1']<=28.05
    ensure_arrival(s['robot']['pose_mm'],p['candidate_endpoint'])
    alignment=ROOT/args.alignment_plan
    report=dict(at=time.time(),status='calibration_alignment_descent_trial_completed' if args.new_placement_trial else 'calibration_alignment_descent_repeat_completed',
        calibration_log=args.calibration_log,calibration_log_sha256=sha(log.read_bytes()),
        calibration=final,alignment=json.loads(alignment.read_bytes()),
        state=s,sequence=q,profile=p,profile_sha256=digest,
        previous_corrected_position_visually_confirmed=True,prior_operator_reported_gaps_mm=[25,25],
        new_placement_trial=args.new_placement_trial,
        repeat_visual_inspection_pending=True,grip_executed=False,lift_executed=False)
    out=ROOT/args.output
    if out.exists():raise RuntimeError('Existing trial must not be overwritten.')
    out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(report=str(out),pose=s['robot']['pose_mm'],e1=s['robot']['external_axes']['E1'])))

if __name__=='__main__':main()
