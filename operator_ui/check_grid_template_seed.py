"""Offline whole-plate translation initializer study, no hardware access."""
import json,sys,types
import cv2
import numpy as np
from projected_disk_trial import ROOT,Perception,DetectionError

def template_seed(self,image):
    signal=self.anchor.signal(self.anchor.gray(image))
    low=np.floor(self.anchor.corners.min(axis=0)).astype(int)
    high=np.ceil(self.anchor.corners.max(axis=0)).astype(int)
    x,y=low;right,bottom=high
    template=self.anchor.reference_signal[y:bottom,x:right]
    scores=cv2.matchTemplate(signal,template,cv2.TM_CCOEFF_NORMED)
    _,score,_,location=cv2.minMaxLoc(scores)
    other=scores.copy();cx,cy=location
    other[max(0,cy-15):cy+16,max(0,cx-15):cx+16]=-1
    next_score=float(other.max())
    shift=np.array(location)-low
    if score<.65 or score-next_score<.03 or np.linalg.norm(shift)>150:return None,None
    return np.array([[1.,0,shift[0]],[0,1.,shift[1]],[0,0,1.]]),dict(method='whole_plate_template',score=score,margin=score-next_score,shift=shift.tolist(),accepted_pose=False)

for name in sys.argv[1:]:
    p=Perception('anchored_grid',5)
    p.tracker.texture_seed=types.MethodType(template_seed,p.tracker)
    rows=[]
    for line in (ROOT/name).read_text().splitlines():
        e=json.loads(line)
        if e['event']!='stationary_image_burst':continue
        try:
            r=p.measure(cv2.imread(e['median_image']),e['pose'])
            rows.append(dict(ok=True,xy=r['error_xy_mm'],initialization=r['tracking']['initialization']))
        except DetectionError as ex:rows.append(dict(ok=False,error=str(ex)))
    print(json.dumps(dict(log=name,passed=sum(x['ok'] for x in rows),total=len(rows),rows=rows)),flush=True)
