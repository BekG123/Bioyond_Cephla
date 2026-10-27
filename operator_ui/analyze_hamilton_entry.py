"""Read-only inspection of the recorded entrance, in its approach frame."""
import json
import math
import argparse
from pathlib import Path
from trajectory_queue import locate

HERE=Path(__file__).resolve().parent
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',default='straight_transfer_212')
    parser.add_argument('--trial',default='trial_47808_47976.json')
    args=parser.parse_args()
    root=HERE/'reports/trajectory_smoothing'
    c=json.loads((root/args.candidate/'candidate.json').read_text())['routes']['to_hamilton']
    t=json.loads((HERE/'demonstrations/return_path_trials_20261016_131713'/args.trial).read_text())
    a,b=c['start'],c['points'][-1]
    length=math.hypot(b['X']-a['X'],b['Y']-a['Y'])
    u={k:(b[k]-a[k])/length for k in ('X','Y')}
    hover=c['points'][1]
    first=min(range(len(t['trajectory'])),key=lambda i:sum((t['trajectory'][i]['pose_mm'][k]-hover[k])**2 for k in ('X','Y','Z')))
    rows=t['trajectory'][first:]
    projection=[sum((r['pose_mm'][k]-b[k])*u[k] for k in u) for r in rows]
    deviations=[locate(r['pose_mm'],[a]+c['points']) for r in t['trajectory']]
    print(json.dumps(dict(direction=u,entrance_samples=len(rows),observed_forward_advance_mm=projection[-1]-projection[0],forward_min_mm=min(projection),
                         forward_max_mm=max(projection),max_backward_sample_step_mm=max([0]+[x-y for x,y in zip(projection,projection[1:])]),
                         max_path_deviation_mm=max(x[0] for x in deviations),
                         proposed_hover={**b,'X':round(b['X']-3*u['X'],2),'Y':round(b['Y']-3*u['Y'],2),'Z':212}),indent=2))

if __name__=='__main__':main()
