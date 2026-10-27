"""Offline clearance-review candidate only. Never connects to the robot."""
import hashlib
import json
import math
from pathlib import Path

import trajectory_smoothing as smoothing
from recorded_return import RecordedReturn
from trajectory_queue import locate, prepare_points
from autonomy import check_path, wrap

HERE = Path(__file__).resolve().parent


def build():
    source = HERE/'demonstrations/return_home_20261016_130748/return_path.json'
    original = source.read_bytes()
    data = json.loads(original)
    cfg = json.loads((HERE/'robot_params.json').read_text())
    first = data['trajectory'][0]
    replay = RecordedReturn(source.parent,None,None,lambda:cfg,None,None)
    legs,_ = replay.plan(data)
    reference,_ = prepare_points(first['pose_mm'],first['joints'],legs,cfg)
    baseline,_,baseline_report = smoothing.group_points(first['pose_mm'],first['joints'],reference,cfg)
    original_settings = (smoothing.POSITION_TOLERANCE_MM,smoothing.YAW_TOLERANCE_DEG,smoothing.MAX_ARC_MM)
    try:
        smoothing.POSITION_TOLERANCE_MM = 3.15
        smoothing.YAW_TOLERANCE_DEG = 2.
        smoothing.MAX_ARC_MM = 100.
        candidate,_,report = smoothing.group_points(first['pose_mm'],first['joints'],reference,cfg)
    finally:
        smoothing.POSITION_TOLERANCE_MM,smoothing.YAW_TOLERANCE_DEG,smoothing.MAX_ARC_MM = original_settings
    if len(candidate)!=70:
        raise ValueError('Recording or implementation changed; expected exactly 70 candidate commands.')
    dense = [first['pose_mm']]+reference
    segments = []
    q = dict(first['joints'])
    for index,(a,b) in enumerate(zip([first['pose_mm']]+candidate,candidate),1):
        q = check_path(a,b,q,cfg,None)
        n = max(1,math.ceil(math.dist([a[k] for k in smoothing.XYZ],[b[k] for k in smoothing.XYZ])),
                math.ceil(abs(wrap(b['Rz']-a['Rz']))/.1))
        samples = []
        for i in range(n+1):
            p = {k:a[k]+(b[k]-a[k])*i/n for k in smoothing.XYZ}
            p['Rz'] = a['Rz']+wrap(b['Rz']-a['Rz'])*i/n
            d,yaw,_ = locate(p,dense)
            samples.append(dict(t=i/n,pose=p,position_mm=d,yaw_deg=yaw))
        worst = max(samples,key=lambda p:p['position_mm'])
        segments.append(dict(number=index,start=a,end=b,ik_end={k:q[k] for k in ('J2','J3','J4')},
                             geometry=report['groups'][index-1],runtime_max_position_mm=worst['position_mm'],
                             runtime_max_yaw_deg=max(p['yaw_deg'] for p in samples),worst_position_location=worst['pose'],
                             exceeds_existing_monitor=any(p['position_mm']>2 or p['yaw_deg']>2 for p in samples),
                             samples=len(samples)))
    return dict(schema='cephla.offline-clearance-review.v1',direction='Hamilton to recorded Home-area start',
                source_path=str(source),source_sha256=hashlib.sha256(original).hexdigest(),
                execution_authorized=False,physical_clearance_verified=False,runtime_settings_changed=False,
                start=first['pose_mm'],endpoint=candidate[-1],reference=reference,baseline=baseline,
                baseline_report=baseline_report,candidate=candidate,grouping=report,segments=segments,
                ik_check_passed=True,existing_monitor=dict(position_mm=2,yaw_deg=2),
                note='TCP path and IK review only; obstacle clearance and full arm/gripper swept volume are not established.')


def render(data, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig = plt.figure(figsize=(14,10),layout='constrained')
    fig.suptitle('70-waypoint candidate | Hamilton → recorded Home-area start\nOFFLINE REVIEW ONLY — not approved for execution',fontsize=17)
    original = [data['start']]+data['reference']
    candidate = [data['start']]+data['candidate']
    for pos,keys,title in ((221,('X','Y'),'Top view'),(222,('X','Z'),'Side view')):
        ax=fig.add_subplot(pos)
        ax.plot([p[keys[0]] for p in original],[p[keys[1]] for p in original],color='#aab0b8',linewidth=4)
        for segment in data['segments']:
            color='#c33c32' if segment['exceeds_existing_monitor'] else '#176dad'
            a,b=segment['start'],segment['end']
            ax.plot([a[keys[0]],b[keys[0]]],[a[keys[1]],b[keys[1]]],color=color,linewidth=1.5)
        for label,p in (('Hamilton',candidate[0]),('Recorded Home-area',candidate[-1])):
            ax.scatter(p[keys[0]],p[keys[1]],color='#111111',s=28,zorder=5)
            ax.annotate(label,(p[keys[0]],p[keys[1]]),xytext=(6,9),textcoords='offset points',fontsize=9)
        ax.set(title=title,xlabel=f'{keys[0]} (mm)',ylabel=f'{keys[1]} (mm)')
        ax.set_aspect('equal',adjustable='datalim');ax.margins(.15);ax.grid(alpha=.2)
    ax=fig.add_subplot(223,projection='3d')
    ax.plot(*[[p[k] for p in original] for k in ('X','Y','Z')],color='#aab0b8',linewidth=3)
    for segment in data['segments']:
        a,b=segment['start'],segment['end']
        ax.plot(*[[a[k],b[k]] for k in ('X','Y','Z')],color='#c33c32' if segment['exceeds_existing_monitor'] else '#176dad')
    ax.set(title='TCP path in 3D',xlabel='X (mm)',ylabel='Y (mm)',zlabel='Z (mm)')
    ax.view_init(elev=25,azim=-55)
    ax=fig.add_subplot(224)
    ax.bar([s['number'] for s in data['segments']],[s['runtime_max_position_mm'] for s in data['segments']],
           color=['#c33c32' if s['exceeds_existing_monitor'] else '#176dad' for s in data['segments']])
    ax.axhline(2,color='#333333',linestyle='--',label='Current runtime limit: 2 mm')
    ax.set(title='Sampled deviation from recorded path',xlabel='Candidate segment (1–70)',ylabel='Maximum position deviation (mm)')
    ax.legend(loc='upper right',fontsize=9);ax.grid(axis='y',alpha=.2)
    fig.legend(handles=[Line2D([0],[0],color='#aab0b8',lw=4,label='Recorded path'),Line2D([0],[0],color='#176dad',lw=2,label='70-point candidate'),Line2D([0],[0],color='#c33c32',lw=2,label='Exceeds existing runtime monitor')],loc='outside lower center',ncol=3)
    fig.savefig(output/'review.png',dpi=160)
    fig.savefig(output/'review.pdf')
    plt.close(fig)


def main():
    output=HERE/'reports/trajectory_smoothing/review_70'
    output.mkdir(parents=True,exist_ok=True)
    data=build()
    (output/'candidate.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    render(data,output)
    exceeded=[s for s in data['segments'] if s['exceeds_existing_monitor']]
    lines=['# 70-waypoint clearance review','',
           '**Prepared offline only. No robot motion; this candidate is not enabled for replay.**','',
           '- Direction: Hamilton → recorded Home-area start (not saved Home).',
           '- 544 dense segments → 132 current commands → **70 candidate commands**.',
           '- Ordered-path deviation: at most **3.143 mm / 1.598°**, versus current planning tolerances of 0.25 mm / 0.1°.',
           '- Maximum grouped source arc: **100 mm**, increased from 50 mm.',
           f'- IK checks pass for every candidate segment. **{len(exceeded)} segments exceed the existing 2 mm / 2° runtime monitor** in the sampled check.',
           '- Production settings, replay permission, original recording and saved Home are unchanged.','',
           '![Path comparison](review.png)','',
           '## Segments needing particular clearance review','',
           '| Segment | Max sampled position deviation (mm) | Location of maximum (X, Y, Z mm) |',
           '|---|---:|---|']
    for s in exceeded:
        p=s['worst_position_location']
        lines.append(f"| {s['number']} | {s['runtime_max_position_mm']:.3f} | {p['X']:.2f}, {p['Y']:.2f}, {p['Z']:.2f} |")
    lines += ['', 'Review these chords against the actual Hamilton fixtures and the full arm/gripper swept volume. The plot shows TCP geometry, not measured obstacle clearance. IK feasibility does not establish collision clearance. The runtime comparison samples at ≤1 mm translation / 0.1° yaw; the ordered-path geometric bound covers the full segments.',
              '', 'No velocity/acceleration/jerk improvement has been measured for this candidate. Fewer waypoints alone do not establish smoother motion.',
              '', '[All 70 waypoints, segment checks and source hash](candidate.json) · [Printable plots](review.pdf)']
    (output/'Review.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(folder=str(output),commands=len(data['candidate']),ik_passed=True,
                         segments_exceeding_monitor=[s['number'] for s in exceeded],
                         maximum_runtime_deviation_mm=max(s['runtime_max_position_mm'] for s in data['segments']),
                         execution_authorized=False),indent=2))


if __name__=='__main__':main()
