"""Generate a three-segment route preview, without touching controller settings."""
import hashlib
import json
from pathlib import Path
from straight_transfer import plan_straight_transfer

HERE=Path(__file__).resolve().parent


def main():
    source=HERE/'demonstrations/return_home_20261016_130748/return_path.json'
    raw=source.read_bytes();data=json.loads(raw)
    cfg=json.loads((HERE/'robot_params.json').read_text())
    parent=HERE/'reports/trajectory_smoothing/pruned_middle/candidate.json'
    parent_raw=parent.read_bytes();base=json.loads(parent_raw)
    height=max(p['Z'] for p in [base['start']]+base['reference'])
    home,ham=data['trajectory'][-1],data['trajectory'][0]
    routes={}
    for name,a,b in (('to_hamilton',home,ham),('toward_home',ham,home)):
        routes[name]=plan_straight_transfer(a['pose_mm'],b['pose_mm'],a['joints'],cfg,height)
    result=dict(schema='cephla.straight-transfer-review.v1',source_sha256=hashlib.sha256(raw).hexdigest(),
                parent_candidate_sha256=hashlib.sha256(parent_raw).hexdigest(),height_mm=height,routes=routes,
                execution_authorized=False,physical_clearance_verified=False,
                runtime_connected=False,previous_length_mm=base['pruning']['pruned_length_mm'])
    out=HERE/'reports/trajectory_smoothing/straight_transfer';out.mkdir(parents=True,exist_ok=True)
    (out/'candidate.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    old=[base['start']]+base['pruned'];new=[routes['to_hamilton']['start']]+routes['to_hamilton']['points']
    fig=plt.figure(figsize=(13,6),layout='constrained')
    fig.suptitle('Straight transfer proposal — three motion segments\nOffline only: new transit and vertical columns need clearance review',fontsize=16)
    ax=fig.add_subplot(121)
    ax.plot([p['X'] for p in old],[p['Y'] for p in old],color='#b1b5bb',label='Previous route')
    ax.plot([p['X'] for p in new],[p['Y'] for p in new],'o-',color='#176dad',linewidth=2,label='Straight horizontal transfer')
    for name,p in (('Home-area',new[0]),('Hamilton',new[-1])):ax.annotate(name,(p['X'],p['Y']),xytext=(8,8),textcoords='offset points')
    ax.set(title='Top view: no intermediate turns',xlabel='X (mm)',ylabel='Y (mm)');ax.grid(alpha=.2);ax.legend()
    ax=fig.add_subplot(122,projection='3d')
    ax.plot(*[[p[k] for p in old] for k in ('X','Y','Z')],color='#b1b5bb',alpha=.8)
    colors=('#538e35','#176dad','#c14734')
    for i,(a,b) in enumerate(zip(new,new[1:])):
        ax.plot(*[[a[k],b[k]] for k in ('X','Y','Z')],color=colors[i],linewidth=3,label=('1. Lift','2. Straight transfer','3. Descend')[i])
    ax.set(title='Lift → transfer → descend',xlabel='X (mm)',ylabel='Y (mm)',zlabel='Z (mm)');ax.view_init(elev=24,azim=-50);ax.legend(loc='upper left')
    fig.savefig(out/'comparison.png',dpi=160);plt.close(fig)
    route=routes['to_hamilton'];saving=100*(1-route['length_mm']/result['previous_length_mm'])
    lines=['# Straight transfer: intermediate bends removed','',
           '**Offline candidate only. No movement has been commanded.**','',
           'Three continuous straight segments replace the curved transit. The two transitions between vertical and horizontal movement remain; this is not a continuous-velocity corner blend.','',
           '| Phase toward Hamilton | Target X | Target Y | Target Z | Rz |','|---|---:|---:|---:|---:|']
    for s in route['segments']:
        p=s['end'];lines.append(f"| {s['kind']} | {p['X']:.2f} | {p['Y']:.2f} | {p['Z']:.2f} | {p['Rz']:.2f}° |")
    lines += ['',f"Travel: **{route['length_mm']:.1f} mm**, versus {result['previous_length_mm']:.1f} mm for the loop-pruned route (**{saving:.1f}% shorter**). Full-segment IK passes in both directions. Saved Home is unchanged; endpoints are the taught Home-area and Hamilton points.",'',
              '![Comparison](comparison.png)','',
              '## Required clearance review','',
              '- Straight transit at Z253.8 between the two station XY positions, including the complete arm, camera and gripper swept volume.',
              '- Full Hamilton vertical column from Z48.61 to Z253.80; the taught route previously approached at roughly Z111 before lowering.',
              '- Home-area vertical column from Z166.41 to Z253.80.',
              '', 'The chosen height comes from the recorded route, not an obstacle-height measurement. No fixture model establishes clearance along this new route. The original replay limits and permissions remain unchanged. This candidate exceeds the existing segment caps (the transit is about 448 mm and one vertical segment about 205 mm), so it is deliberately not executable through the current reviewed-route API.',
              '', '[Three-segment coordinates and both-direction IK results](candidate.json)']
    (out/'Review.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(report=str(out/'Review.md'),commands=3,length_mm=route['length_mm'],shorter_percent=saving,
                         height_mm=height,ik_both_directions=True,hardware_run=False),indent=2))


if __name__=='__main__':main()
