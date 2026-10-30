"""Offline Home/replay comparison. Generates plans/reports, never connects to hardware."""
import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import statistics
import zipfile

from autonomy import wrap
from recorded_return import RecordedReturn
from trajectory_queue import prepare_points
from trajectory_smoothing import group_points

HERE=Path(__file__).resolve().parent


def distribution(start,points):
    lengths=[math.dist([a[k] for k in ('X','Y','Z')],[b[k] for k in ('X','Y','Z')]) for a,b in zip([start]+points,points)]
    return dict(commands=len(points),upload_batches=math.ceil(len(points)/3),path_length_mm=sum(lengths),
                median_segment_mm=statistics.median(lengths),segments_under_1_mm=sum(x<1 for x in lengths),
                max_segment_mm=max(lengths))


def compare(output):
    raw=(HERE/'demonstrations/return_home_20261016_130748/return_path.json').read_bytes()
    data=json.loads(raw)
    cfg=json.loads((HERE/'robot_params.json').read_text())
    plans={}
    for direction in ('to_hamilton','toward_home'):
        directed=RecordedReturn.directed(data,direction)
        first=directed['trajectory'][0]
        replay=RecordedReturn('.',None,None,lambda:cfg,None,None)
        legs,_=replay.plan(directed)
        points,_=prepare_points(first['pose_mm'],first['joints'],legs,cfg)
        grouped,q,report=group_points(first['pose_mm'],first['joints'],points,cfg)
        plans[direction]=dict(before=distribution(first['pose_mm'],points),after=distribution(first['pose_mm'],grouped),
                              validation=report,start=first['pose_mm'],points=grouped,expected_final_joints=q)
    trial_path=HERE/'demonstrations/return_path_trials_20261016_131713/trial_24915_26139.json'
    trial=json.loads(trial_path.read_text())
    rows=[r for r in trial['trajectory'] if r['valid']]
    time=lambda r:datetime.fromisoformat(r['at']).timestamp()
    start=rows[0]['pose_mm']
    first_motion=next(i for i,r in enumerate(rows) if math.dist([start[k] for k in ('X','Y','Z')],[r['pose_mm'][k] for k in ('X','Y','Z')])>.1 or abs(wrap(r['pose_mm']['Rz']-start['Rz']))>.1)
    near_stationary_s=0.
    samples=[]
    for a,b in zip(rows[first_motion:],rows[first_motion+1:]):
        dt=time(b)-time(a)
        speed=math.dist([a['pose_mm'][k] for k in ('X','Y','Z')],[b['pose_mm'][k] for k in ('X','Y','Z')])/dt
        angular=abs(wrap(b['pose_mm']['Rz']-a['pose_mm']['Rz']))/dt
        if speed<.5 and angular<.5:near_stationary_s+=dt
        samples.append(dict(t_s=time(b)-time(rows[first_motion]),speed_mm_s=speed,yaw_deg_s=angular))
    with zipfile.ZipFile(HERE.parent/'controller/main_hostpoint_trq.bin') as z:
        home=z.read('main/mod_Home.lua').decode().replace('\r','')
    result=dict(recording_sha256=hashlib.sha256(raw).hexdigest(),
        homing=dict(source='main_hostpoint_trq.bin:main/mod_Home.lua',motion='one MoveAbsJ per branch',
                    commands_per_call=1,zone=-1,code=home,measured_smoothness_comparison_available=False),
        routes=plans,
        previous_hardware_trial=dict(path=str(trial_path),completed=False,progress_percent=64.5,speed=40,
            total_duration_s=trial['observed_duration_s'],upload_and_preparation_s=time(rows[first_motion])-time(rows[0]),
            observed_motion_window_s=time(rows[-1])-time(rows[first_motion]),near_stationary_s=near_stationary_s,
            telemetry_interval_s=statistics.median(time(b)-time(a) for a,b in zip(rows,rows[1:])),speed_samples=samples),
        limitations=['Grouped replay has been tested offline, not on hardware.',
                     'Zone remains -1. Fewer commands do not guarantee continuous velocity at every corner.',
                     'Home uses a different joint-space path. Its movement cannot substitute for the taught Cartesian route.',
                     'Five-Hz telemetry misses brief stops and cannot measure true controller jerk reliably.',
                     'Geometric and kinematic validation does not certify obstacle clearance.'])
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    (output/'comparison.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    d=plans['to_hamilton']
    summary=f'''# Home versus taught replay

| Property | Vendor Home | Previous queued replay | Grouped replay |
|---|---:|---:|---:|
| Motion command | MoveAbsJ | MoveL | MoveL |
| Commands to Hamilton | 1, different destination/path | {d['before']['commands']} | {d['after']['commands']} |
| Upload batches | N/A | {d['before']['upload_batches']} | {d['after']['upload_batches']} |
| Median translation per command | N/A | {d['before']['median_segment_mm']:.2f} mm | {d['after']['median_segment_mm']:.2f} mm |
| Commands shorter than 1 mm | N/A | {d['before']['segments_under_1_mm']} | {d['after']['segments_under_1_mm']} |
| Zone setting | −1 | −1 | −1 (unchanged) |
| Hardware result | No matched benchmark captured | Ran to 64.5%, then monitoring stop | Not yet run |

Grouping removes {d['validation']['reduction_percent']}% of command boundaries. Maximum
planned deviation from the quantized reference is {d['validation']['max_position_error_mm']:.3f} mm and
{d['validation']['max_yaw_error_deg']:.3f}°. Endpoints and protected corners/reversals remain.
The first 5 mm and final 10 mm retain their original points. Full-path kinematic
checks pass in both directions. Live monitoring continues against the original path.

The previous partial hardware trial took {trial['observed_duration_s']:.1f} s including
upload/preparation ({result['previous_hardware_trial']['upload_and_preparation_s']:.1f} s).
Near-stationary telemetry intervals totalled {near_stationary_s:.1f} s during the
motion window; 5 Hz sampling cannot resolve every brief stop or controller jerk.
This is a measured baseline, not a forecast of the grouped trajectory's duration.

No Lua republish is needed. This groups points on the host before uploading them
to the already-published version 220101. A hardware trial is still required to
judge smoothness; no claim of Home-equivalent smoothness is made.
'''
    (output/'comparison.md').write_text(summary,encoding='utf-8')
    return dict(output=str(output.resolve()),to_hamilton={k:v for k,v in d.items() if k in ('before','after')},
                trial_summary={k:v for k,v in result['previous_hardware_trial'].items() if k!='speed_samples'})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default=str(HERE/'reports/trajectory_smoothing'))
    print(json.dumps(compare(parser.parse_args().output),indent=2))
