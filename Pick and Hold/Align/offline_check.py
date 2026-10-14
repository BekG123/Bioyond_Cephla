"""Replay saved XY images through IC, without hardware or reference activation."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'operator_ui'))
from pick_and_hold.Align.ic import ICAligner, ICError
from pick_and_hold.Align.references import disk_initial, disk_roi


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    samples=json.loads((args.session/'collection.json').read_text())['samples']
    first=samples[0]
    template=cv2.imread(str(Path(first['sample'])/'rgb.png'))
    roi=disk_roi(first['detection'],template.shape)
    engine=ICAligner(template,roi)
    records=[]
    args.output.mkdir(parents=True,exist_ok=False)
    for s in samples:
        frame=cv2.imread(str(Path(s['sample'])/'rgb.png'))
        try:
            result=engine.align(frame,initial=disk_initial(first['detection'],s['detection']))
        except ICError as ex:
            result=dict(ok=False,reason=str(ex))
        result.update(index=s['index'],sample=Path(s['sample']).name)
        records.append(result)
        print(f"View {s['index']}: {'MATCH' if result['ok'] else result['reason']}",flush=True)
        if 'warp_reference_to_live' in result and s['index'] in (0,12,28):
            cv2.imwrite(str(args.output/f"view_{s['index']:02d}.jpg"),engine.overlay(frame,result))
    matched=[r for r in records if r['ok']]
    report=dict(created_utc=datetime.now(timezone.utc).isoformat(),count=len(records),matches=len(matched),
        template_sample=Path(first['sample']).name,roi=list(roi),
        median_ic_ms=float(np.median([r['seconds']*1000 for r in matched])) if matched else None,
        minimum_correlation=min((r['correlation'] for r in matched),default=None),
        note='Offline tracking only. First saved image is NOT a physically verified aligned-gripper reference. '
             'No robot/camera connection, new capture, active reference, metric labels or robot corrections.',
        records=records)
    (args.output/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='records'},indent=2))


if __name__=='__main__': main()
