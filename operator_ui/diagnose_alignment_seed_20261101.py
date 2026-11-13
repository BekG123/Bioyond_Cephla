"""Offline fresh-vs-reused initializer comparison; no robot or camera access."""
import json
from pathlib import Path
import cv2
from projected_alignment import perception_at_height,target_from_mark

ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'operator_ui/reports/projected_alignment/20261101_011711_e2f1c379.jsonl'
rows=[json.loads(line) for line in path.read_text().splitlines()]
frames=[r for r in rows if r['event']=='stationary_image_burst']
for mode in ('reused','fresh'):
    p,_,_=perception_at_height()
    for row in frames:
        if mode=='fresh':p.tracker.previous_verified_seed=None
        try:
            m=p.measure(cv2.imread(row['median_image']),row['pose'])
            result=dict(ok=True,spread=m['tracking']['disk_group_spread_px'],
                        target=target_from_mark(row['pose'],m,p.cfg))
        except Exception as error:result=dict(ok=False,error=str(error))
        print(json.dumps(dict(mode=mode,image=Path(row['median_image']).name,**result)),flush=True)
