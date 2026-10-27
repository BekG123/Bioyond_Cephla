"""Archive the outward-corrected open-claw trial; no hardware commands."""
import json,time
from urllib.request import urlopen
from projected_pickup import ROOT,PROFILE,load
from autonomy import ensure_arrival

def main():
    with urlopen('http://127.0.0.1:5002/state',timeout=8) as r:s=json.load(r)
    with urlopen('http://127.0.0.1:5002/seq',timeout=8) as r:q=json.load(r)
    p,digest=load()
    assert not q['active'] and q['name']=='researcher_descend' and q['state']=='done'
    assert q['result']['ok'] and q['result']['open_claw_trial']
    assert q['result']['descent_correction']['profile_sha256']==digest
    assert s['robot'].get('connected') and not s['robot']['errors']
    ensure_arrival(s['robot']['pose_mm'],p['candidate_endpoint'])
    assert 27.98<=s['robot']['external_axes']['E1']<=28.05
    report=dict(at=time.time(),status='open_claw_descent_completed_visual_inspection_pending',
        calibration_log='operator_ui/reports/projected_disk_pilot/20261027_010100_f3d591dc.jsonl',
        initial_no_xy_motion_rejection='operator_ui/reports/projected_disk_pilot/20261027_005906_546568da.jsonl',
        calibration_recovery='Returned to previously verified camera observation XY at Z289.129, then checked fresh images: 48 wells, residual about 0.74 mm.',
        corrected_alignment='operator_ui/reports/projected_alignment/alignment_outward_trial_20261027.json',
        correction='2 mm away from robot base, applied once to fresh alignment; replaces previous inward correction.',
        profile=p,profile_sha256=digest,state=s,sequence=q,
        grip_executed=False,lift_executed=False,operator_visual_acceptance=False)
    out=ROOT/'operator_ui/reports/projected_alignment/outward_open_claw_descent_20261027.json'
    if out.exists():raise RuntimeError('Do not overwrite recorded trial.')
    out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(report=str(out),pose=s['robot']['pose_mm'],e1=s['robot']['external_axes']['E1'],ok=True)))

if __name__=='__main__':main()
