"""Offline phase-correlation initializer evaluation; no hardware access."""
import json,sys,types
import cv2
import numpy as np
from projected_disk_trial import ROOT,Perception,DetectionError

def phase_seed(self,image):
    signal=self.anchor.signal(self.anchor.gray(image))
    window=cv2.createHanningWindow(self.size,cv2.CV_32F)
    shift,response=cv2.phaseCorrelate(self.anchor.reference_signal.copy(),signal.copy(),window)
    if response<.1 or not np.isfinite([*shift,response]).all() or np.linalg.norm(shift)>150:
        return None,None
    h=np.array([[1.,0,shift[0]],[0,1.,shift[1]],[0,0,1.]])
    return h,dict(method='phase_translation',response=response,shift=shift,accepted_pose=False)

for name in sys.argv[1:]:
    p=Perception('anchored_grid',5)
    p.tracker.texture_seed=types.MethodType(phase_seed,p.tracker)
    rows=[]
    for line in (ROOT/name).read_text().splitlines():
        e=json.loads(line)
        if e['event']!='stationary_image_burst':continue
        try:
            r=p.measure(cv2.imread(e['median_image']),e['pose'])
            rows.append(dict(ok=True,xy=r['error_xy_mm'],initialization=r['tracking']['initialization']))
        except DetectionError as ex:rows.append(dict(ok=False,error=str(ex)))
    print(json.dumps(dict(log=name,passed=sum(x['ok'] for x in rows),total=len(rows),rows=rows)),flush=True)
