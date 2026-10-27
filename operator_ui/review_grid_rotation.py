"""Replay saved frames with rotation-aware initialization. No hardware access."""
import json,sys
from pathlib import Path
import cv2
from projected_disk_trial import ROOT,Perception,DetectionError
from grid_rotation_seed import rotation_seed

def main():
    path=ROOT/sys.argv[1]
    events=[json.loads(s) for s in path.read_text().splitlines()]
    p=Perception('anchored_grid',5,True)
    rows=[]
    for e in events:
        if e['event']!='stationary_image_burst':continue
        try:
            r=p.measure(cv2.imread(e['median_image']),e['pose'])
            row=dict(ok=True,image=e['median_image'],pose=e['pose'],xy=r['error_xy_mm'],
                wells=r['tracking']['supported_wells'],spread=r['tracking']['disk_group_spread_px'],
                initialization=r['tracking']['initialization'])
        except DetectionError as error:row=dict(ok=False,image=e['median_image'],error=str(error))
        rows.append(row);print(json.dumps(row),flush=True)
    print(json.dumps(dict(passed=sum(r['ok'] for r in rows),total=len(rows))),flush=True)

if __name__=='__main__':main()
