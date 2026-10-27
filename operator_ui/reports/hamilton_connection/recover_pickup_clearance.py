"""Authorized pickup retry: vertical retraction, then one camera-clearance move."""
import asyncio
import json
import argparse
from pathlib import Path
from run_camera_pickup_trial import capture,execute

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-probe',type=Path,required=True)
    parser.add_argument('--travel-x-scale',type=int,choices=range(2,11),default=2)
    args=parser.parse_args()
    folder=capture([])
    p=json.loads((folder/'probe.json').read_text())
    q=p['tcp_queries']
    start={int(v['channel']):[v['position_x'],v['position_y'],v['position_z']] for v in q['PrepGetPositions']['positions']}
    reference=json.loads(args.reference_probe.read_text())
    expected={int(v['channel']):[v['position_x'],v['position_y'],v['position_z']] for v in reference['tcp_queries']['PrepGetPositions']['positions']}
    if set(start)!={1,2} or any(abs(start[c][i]-expected[c][i])>.2 for c in (1,2) for i in range(3)):
        raise RuntimeError('Stopped pickup position has changed; no recovery motion.')
    if not (40<=start[1][0]<=75 and 15<=start[1][1]<start[2][1]<=80 and 60<=start[1][2]<=80 and 165<=start[2][2]<=166):
        raise RuntimeError('Outside the reviewed stopped-pickup region; no recovery motion.')
    definition=next(d for d in q['PrepGetTipAndNeedleDefinitions']['definitions'] if d['id']==2 and d['label']=='300uL StdVolFilter')
    high={c:[v[0],v[1],165.5] for c,v in start.items()}
    aside={1:[289.30,344.99,165.5],2:[289.30,365.01,165.5]}
    plan={'start':start,'capture_time':p['time_utc'],'stored_tip_definition':definition,
          'clearance_only':True,'selected':[],
          'travel_x_scale':args.travel_x_scale,
          'path':[{'phase':'vertical_retract','positions':high},
                  {'phase':'continuous_camera_clearance','positions':aside}]}
    (folder/'recovery_plan.json').write_text(json.dumps(plan,indent=2))
    asyncio.run(execute(folder,plan))

if __name__=='__main__':main()
