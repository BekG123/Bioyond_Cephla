"""Generate a shorter route review and plots offline; no robot connection."""
import hashlib
import json
from pathlib import Path

from autonomy import check_path, wrap
from recorded_return import RecordedReturn
from trajectory_queue import prepare_points,locate
from trajectory_smoothing import group_points
from trajectory_pruning import prune_middle, distance, XYZ

HERE=Path(__file__).resolve().parent


def build():
    source=HERE/'demonstrations/return_home_20261016_130748/return_path.json'
    original=source.read_bytes();data=json.loads(original)
    cfg=json.loads((HERE/'robot_params.json').read_text())
    directed=RecordedReturn.directed(data,'to_hamilton');first=directed['trajectory'][0]
    replay=RecordedReturn('.',None,None,lambda:cfg,None,None)
    legs,_=replay.plan(directed)
    reference,_=prepare_points(first['pose_mm'],first['joints'],legs,cfg)
    pruned,report=prune_middle(first['pose_mm'],first['joints'],reference,cfg)
    grouped,_,grouping=group_points(first['pose_mm'],first['joints'],pruned,cfg)
    reverse=list(reversed([first['pose_mm']]+pruned));q=data['trajectory'][0]['joints']
    for a,b in zip(reverse,reverse[1:]):q=check_path(a,b,q,cfg,None)
    for bridge in report['bridges']:
        a,b=bridge['start'],bridge['end'];dmax=ymax=0.
        for i in range(101):
            p={k:a[k]+(b[k]-a[k])*i/100 for k in XYZ}
            p['Rz']=a['Rz']+wrap(b['Rz']-a['Rz'])*i/100
            d,y,_=locate(p,[first['pose_mm']]+reference);dmax=max(dmax,d);ymax=max(ymax,y)
        bridge['sampled_old_corridor_position_mm']=dmax
        bridge['sampled_old_corridor_yaw_deg']=ymax
    return dict(schema='cephla.pruned-route-review.v1',execution_authorized=False,
                physical_clearance_verified=False,source_sha256=hashlib.sha256(original).hexdigest(),
                direction='Recorded Home-area start to Hamilton',start=first['pose_mm'],endpoint=reference[-1],
                reference=reference,pruned=pruned,grouped=grouped,pruning=report,grouping=grouping,
                reverse_ik_passed=True,production_settings_changed=False,
                note='Candidate only. Review both new connectors and arm/gripper clearance; IK alone does not establish collision clearance.')


def plot(data,out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    fig=plt.figure(figsize=(13,10),layout='constrained')
    fig.suptitle('Remove middle loops — retain the taught Hamilton approach\nOffline candidate | 1,817 → 1,067 mm of TCP travel',fontsize=17)
    original=[data['start']]+data['reference'];pruned=[data['start']]+data['pruned']
    bridges=data['pruning']['bridges']
    for position,keys,title in ((221,('X','Y'),'Top view — full route'),(222,('X','Z'),'Side view — lift and descent preserved'),(224,('X','Y'),'New connectors — enlarged top view')):
        ax=fig.add_subplot(position)
        ax.plot(*[[p[k] for p in original] for k in keys],color='#e4b381',linewidth=3)
        ax.plot(*[[p[k] for p in pruned] for k in keys],color='#176dad',linewidth=1.6)
        for number,b in enumerate(bridges,1):
            a,c=b['start'],b['end']
            ax.plot(*[[a[k],c[k]] for k in keys],color='#bd2e39',linewidth=3)
            if position==224:
                ax.annotate(f"Connector {number}: {b['connector_mm']:.2f} mm",(c[keys[0]],c[keys[1]]),xytext=(8,12 if number==1 else -24),textcoords='offset points',fontsize=10)
        if position==224:
            ax.set_xlim(219,239);ax.set_ylim(-1,12)
        else:
            for name,p in (('Home-area',pruned[0]),('Hamilton',pruned[-1])):
                ax.scatter(p[keys[0]],p[keys[1]],color='#222222',s=25,zorder=6)
                ax.annotate(name,(p[keys[0]],p[keys[1]]),xytext=(6,7),textcoords='offset points')
        ax.set(title=title,xlabel=f'{keys[0]} (mm)',ylabel=f'{keys[1]} (mm)')
        ax.grid(alpha=.2)
    ax=fig.add_subplot(223,projection='3d')
    ax.plot(*[[p[k] for p in original] for k in XYZ],color='#e4b381',linewidth=2)
    ax.plot(*[[p[k] for p in pruned] for k in XYZ],color='#176dad',linewidth=2)
    for bridge in bridges:
        ax.plot(*[[bridge['start'][k],bridge['end'][k]] for k in XYZ],color='#bd2e39',linewidth=3)
    ax.set(title='3D route comparison',xlabel='X (mm)',ylabel='Y (mm)',zlabel='Z (mm)')
    ax.view_init(elev=27,azim=-55)
    fig.legend(handles=[Line2D([0],[0],color='#e4b381',lw=3,label='Original route, including loops'),Line2D([0],[0],color='#176dad',lw=2,label='Route with loops removed'),Line2D([0],[0],color='#bd2e39',lw=3,label='New connectors: clearance review')],loc='outside lower center',ncol=3)
    fig.savefig(out/'comparison.png',dpi=160);fig.savefig(out/'comparison.pdf');plt.close(fig)


def main():
    data=build();out=HERE/'reports/trajectory_smoothing/pruned_middle';out.mkdir(parents=True,exist_ok=True)
    (out/'candidate.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    plot(data,out)
    r=data['pruning'];g=data['grouping']
    lines=['# Middle-loop removal','', '**Offline candidate only. No hardware movement or replay-setting changes.**','',
           f"Two near-return loops at Z≈253.6–253.7 mm can be replaced by short connectors. TCP travel decreases from **{r['original_length_mm']:.1f} to {r['pruned_length_mm']:.1f} mm**, saving **{r['saved_mm']:.1f} mm ({r['saved_percent']:.1f}%)**.",'',
           f"Grouping the shorter route gives **{len(data['grouped'])} commands**, using the original **0.25 mm / 0.1°** grouping tolerances and 50 mm arc cap. These bounds are relative to the proposed pruned route, not the deleted detours. The previous 70-point proposal merely simplified those detours; this candidate removes them.",'',
           'The complete initial portion before the highest plateau and the final descent/Hamilton approach are preserved in the pruned polyline. Both forward and reverse IK checks pass. The original recording and its replay permission remain unchanged.','',
           '![Route comparison](comparison.png)','',
           '| Connector | Source point indices | Replaced travel | New travel | Yaw change |', '|---|---|---:|---:|---:|']
    for i,b in enumerate(r['bridges'],1):
        lines.append(f"| {i} | {b['first']} → {b['last']} | {b['removed_travel_mm']:.2f} mm | {b['connector_mm']:.2f} mm | {b['yaw_change_deg']:.2f}° |")
    lines += ['', '## Clearance review','',
              'Review the two red connectors near X225–231, Y3–8, Z254 mm, including the wrist/gripper and full arm swept volume. The plot describes TCP motion; no obstacle geometry was used. A hand-guided detour may have avoided an obstacle even when its endpoints are close.',
              '', 'The first connector reaches 2.19 mm from the old recorded corridor in the sampled check, exceeding its 2 mm monitor limit. A future approved route needs its own reviewed reference and permission; do not bypass or widen the existing monitor to execute this file.',
              '', 'Runtime replay is still bound to the original recording. This candidate is a separate artifact with execution disabled; it is not loaded into the controller. No speed or smoothness improvement is claimed until a supervised hardware test.',
              '', '[Coordinates, retained source indices and IK results](candidate.json) · [Printable comparison](comparison.pdf)']
    (out/'Review.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(report=str(out/'Review.md'),length_mm=r['pruned_length_mm'],saved_percent=r['saved_percent'],commands=len(data['grouped']),bridges=r['bridges'],execution_authorized=False),indent=2))


if __name__=='__main__':main()
