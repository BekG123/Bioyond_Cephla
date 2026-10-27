"""Read saved trials and compare matched portions; never commands hardware."""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path

from autonomy import wrap


def stamp(row):
    return datetime.fromisoformat(row['at']).timestamp()


def distance(a,b):
    return math.dist([a[k] for k in ('X','Y','Z')],[b[k] for k in ('X','Y','Z')])


def window(rows, endpoint=None):
    start=rows[0]['pose_mm']
    first=next(i for i,r in enumerate(rows) if distance(start,r['pose_mm'])>.1 or abs(wrap(start['Rz']-r['pose_mm']['Rz']))>.1)
    last=len(rows)-1
    if endpoint:
        last=min(range(first,len(rows)),key=lambda i:distance(endpoint,rows[i]['pose_mm'])**2+wrap(endpoint['Rz']-rows[i]['pose_mm']['Rz'])**2)
        if distance(endpoint,rows[last]['pose_mm'])>2 or abs(wrap(endpoint['Rz']-rows[last]['pose_mm']['Rz']))>2:
            raise ValueError('Trials do not have a sufficiently close common endpoint.')
    slow=0.
    peak=0.
    for a,b in zip(rows[first:last],rows[first+1:last+1]):
        dt=stamp(b)-stamp(a)
        speed=distance(a['pose_mm'],b['pose_mm'])/dt
        angular=abs(wrap(b['pose_mm']['Rz']-a['pose_mm']['Rz']))/dt
        peak=max(peak,speed)
        if speed<.5 and angular<.5:slow+=dt
    duration=stamp(rows[last])-stamp(rows[first])
    return dict(upload_and_preparation_s=stamp(rows[first])-stamp(rows[0]),motion_window_s=duration,
                near_stationary_s=slow,near_stationary_percent=100*slow/duration,
                peak_sampled_tcp_speed_mm_s=peak,endpoint_sample=rows[last]['index'],
                endpoint_distance_mm=distance(endpoint,rows[last]['pose_mm']) if endpoint else 0)


def compare(previous,current):
    old=json.loads(Path(previous).read_text())
    new=json.loads(Path(current).read_text())
    if not new['sequence']['result']['ok']:
        raise ValueError('Grouped replay did not complete.')
    if old['invalid_samples'] or new['invalid_samples']:
        raise ValueError('Compare only trials with complete valid telemetry.')
    endpoint=old['trajectory'][-1]['pose_mm']
    return dict(previous_trial=str(previous),grouped_trial=str(current),
                grouped_total_s=new['observed_duration_s'],
                grouped_full=window(new['trajectory']),
                common_prefix=dict(previous=window(old['trajectory']),grouped=window(new['trajectory'],endpoint)),
                grouped_endpoint_error=new['endpoint_error'],
                limitations=['Earlier ungrouped queue stopped at about 64.5%; full-route times are not directly comparable.',
                             'About 5 Hz controller feedback is not a jerk or acceleration measurement.',
                             'Near-stationary means sampled TCP speed below 0.5 mm/s and yaw speed below 0.5 deg/s.',
                             'No equivalent measured vendor Home trial exists; equal homing smoothness is not established.'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('previous')
    parser.add_argument('current')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    report=compare(args.previous,args.current)
    if args.output:args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
