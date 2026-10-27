"""Offline Z-stop diagnosis and a bounded 75-command candidate; no hardware calls."""
from datetime import datetime
import hashlib
import json
from pathlib import Path

from trajectory_queue import prepare_points
from trajectory_smoothing import coalesce_vertical_runs

HERE=Path(__file__).resolve().parent


def build():
    parent=HERE/'reports/trajectory_smoothing/pruned_middle/candidate.json'
    raw=parent.read_bytes();base=json.loads(raw)
    source=HERE/'demonstrations/return_home_20261016_130748/return_path.json'
    source_raw=source.read_bytes();data=json.loads(source_raw)
    if hashlib.sha256(source_raw).hexdigest()!=base['source_sha256']:raise ValueError('Recording changed')
    cfg=json.loads((HERE/'robot_params.json').read_text())
    start=base['start'];q=data['trajectory'][-1]['joints']
    points,_,report=coalesce_vertical_runs(start,q,base['grouped'],cfg)
    points,_=prepare_points(start,q,points,cfg,reviewed=True,vertical_runs=True)
    if len(points)!=75:raise ValueError('Expected 75 reviewed commands; regenerate review after a route change')
    reverse=list(reversed([start]+points))
    prepare_points(reverse[0],data['trajectory'][0]['joints'],reverse[1:],cfg,reviewed=True,vertical_runs=True)
    return dict(schema='cephla.vertical-smoothing-review.v1',execution_authorized=False,
                source_sha256=base['source_sha256'],parent_candidate_sha256=hashlib.sha256(raw).hexdigest(),
                direction='Recorded Home-area start to Hamilton',start=start,endpoint=points[-1],grouped=points,
                reference=base['grouped'],smoothing=report,forward_and_reverse_ik_passed=True,
                speed=40,zone=-1,acceleration_settings_changed=False,
                changes='Two straight Z runs are coalesced; turns, endpoints, and first/last 10 mm point detail retained.')


def plot_diagnosis(data,out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    trial=json.loads((HERE/'demonstrations/return_path_trials_20261016_131713/trial_38117_38612.json').read_text())
    rows=trial['trajectory'];stamp=lambda r:datetime.fromisoformat(r['at']).timestamp()
    t0=stamp(rows[0]);sample=[]
    for i,r in enumerate(rows[1:-1],1):
        p=r['pose_mm']
        if abs(p['X']-283.4)<.5 and abs(p['Y']+44.13)<.5 and p['Z']>112:
            speed=(rows[i+1]['pose_mm']['Z']-rows[i-1]['pose_mm']['Z'])/(stamp(rows[i+1])-stamp(rows[i-1]))
            sample.append(dict(t_s=stamp(r)-t0,z_mm=p['Z'],vz_mm_s=speed))
    fig,axes=plt.subplots(3,1,figsize=(11,10),layout='constrained')
    fig.suptitle('Z-motion fix: remove two artificial intermediate stops',fontsize=17)
    axes[0].plot([r['t_s'] for r in sample],[r['z_mm'] for r in sample],color='#176dad',marker='.',markersize=4)
    axes[0].set(title='Measured 78-point run: vertical lift',ylabel='Z (mm)',xlabel='Time from run start (s)')
    axes[1].plot([r['t_s'] for r in sample],[r['vz_mm_s'] for r in sample],color='#176dad',marker='.',markersize=4)
    axes[1].set(title='Measured vertical speed — repeated slowing at command boundaries',ylabel='Z velocity (mm/s)',xlabel='Time from run start (s)')
    boundaries=[]
    for z in (155.71,204.07):
        nearest=min(sample,key=lambda r:abs(r['z_mm']-z));boundaries.append(nearest)
        for ax in axes[:2]:ax.axvline(nearest['t_s'],color='#c33c32',linestyle='--')
        axes[1].annotate(f"Z{z:.1f}: {nearest['vz_mm_s']:.1f} mm/s",(nearest['t_s'],nearest['vz_mm_s']),xytext=(8,14),textcoords='offset points',fontsize=10)
    z=[110.97,155.71,204.07,253.8]
    axes[2].plot(z,[1]*4,'o-',label='Before: three MoveL commands',color='#c33c32',linewidth=3)
    axes[2].plot([z[0],z[-1]],[0,0],'o-',label='Prepared: one MoveL command',color='#176dad',linewidth=3)
    axes[2].set(yticks=[0,1],yticklabels=['Prepared','Before'],ylim=(-.6,1.8),xlabel='Z (mm)',title='Same endpoints; maximum geometric change 0.038 mm / 0.017°')
    axes[2].legend(loc='upper center',fontsize=10)
    for ax in axes:ax.grid(alpha=.2)
    fig.savefig(out/'z_motion_comparison.png',dpi=160);plt.close(fig)
    return dict(source_trial='trial_38117_38612.json',measured_dips=boundaries,samples=sample,
                limitation='About 5 Hz controller feedback; speed is a finite-difference estimate, not a jerk measurement. No new hardware result yet.')


def main():
    data=build();out=HERE/'reports/trajectory_smoothing/vertical_smoothing';out.mkdir(parents=True,exist_ok=True)
    (out/'candidate.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    diagnosis=plot_diagnosis(data,out)
    (out/'diagnosis.json').write_text(json.dumps(diagnosis,indent=2),encoding='utf-8')
    text='''# Vertical-motion smoothing

The last hardware log shows vertical speed falling from about **21 mm/s to 4.5–4.7 mm/s** at Z155.7 and Z204.1. These coincide with intermediate MoveL endpoints on the otherwise straight Z110.97→253.80 lift. The 50 mm grouping cap inserted those boundaries.

Implemented a strict vertical-run coalescer: **78 → 75 commands**, in both directions. The 142.83 mm lift becomes one command; the 55.06 mm lift becomes one instead of two. Endpoints, real bends, Z reversals, and the first/last 10 mm waypoint detail remain intact. Maximum change for this route: **0.038 mm / 0.017°**. Full-segment IK passes in both directions.

Long segments are allowed only for separately reviewed, nearly vertical moves: ≤200 mm travel, ≤0.25 mm lateral endpoint drift and ≤0.1° endpoint yaw change. All other reviewed segments retain their 50 mm limit. The coalescer additionally bounds the whole intervening path change to 0.1 mm / 0.05°. The executor never silently regroups an approved artifact.

![Measured speed dips and prepared change](z_motion_comparison.png)

The native Lua executor still uses one final MOVFINISH and zone −1. Speed remains 40; acceleration, jerk and blending parameters were not guessed. The local Bioyond Works manual (PDF pages 47–50) lists SetAcc and SetAccTime but does not establish the required parameter units/ranges or zone −1 semantics.

**Prepared and tested offline; no hardware run of this version yet.** Horizontal corner slowdowns may remain. This removes specific artificial stops; it does not establish continuous velocity or jerk-limited motion throughout the whole route. A separate hash-bound approval is required for a future run, using `start-pruned` with `route: vertical` and the selected direction.

[75-point candidate](candidate.json) · [Measured baseline data](diagnosis.json)
'''
    (out/'Review.md').write_text(text,encoding='utf-8')
    print(json.dumps(dict(report=str(out/'Review.md'),commands=len(data['grouped']),merges=data['smoothing']['merges'],hardware_run=False),indent=2))


if __name__=='__main__':main()
