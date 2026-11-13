"""Offline replay of saved calibration frames. No hardware connection or motion."""
import json
from pathlib import Path
import cv2
import numpy as np
from projected_alignment import perception_at_height, target_from_mark

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'operator_ui/reports/plate48_diagnosis_20261101'
OUT.mkdir(exist_ok=True)
cases = [('successful', '20261101T082306Z_0410e145', 'fbbdbfd769bc4652a926061506a034d0'),
         ('failed', '20261101T085134Z_f92e3c78', '0f8003033101403a8803130b43db3c8d')]
results=[]
panels=[]
for label, session, run_id in cases:
    rows=[]
    for file in (ROOT/'operator_ui/logs/audit'/session).glob('*.jsonl'):
        rows.extend(json.loads(line) for line in file.open())
    frames=[r for r in rows if r.get('run_id')==run_id and r.get('event')=='plate48_stationary_image_burst']
    p,_,_=perception_at_height()
    for index,r in enumerate(frames):
        im=cv2.imread(r['median_image'])
        result=dict(case=label,image=r['median_image'],pose=r['pose'],
                    mean=float(im.mean()),std=float(im.std()),
                    clipped_bright_fraction=float((im>=250).mean()))
        try:
            m=p.measure(im,r['pose'])
            result.update(ok=True,target=target_from_mark(r['pose'],m,p.cfg),
                disk_spread=m['tracking']['disk_group_spread_px'],
                extent_spread=m['tracking']['extent_group_spread_px'])
        except Exception as error:
            result.update(ok=False,error=str(error))
        results.append(result)
        print(json.dumps(result),flush=True)
        if index==0:
            panel=cv2.resize(im,(800,600))
            cv2.putText(panel,label,(20,35),cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,255),2)
            panels.append(panel)
(OUT/'replay.json').write_text(json.dumps(results,indent=2))
cv2.imwrite(str(OUT/'comparison.jpg'),np.hstack(panels))
