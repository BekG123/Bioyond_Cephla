"""Offline comparison only: fixed-height affine anchor refinement."""
import json,sys,types
import cv2
import numpy as np
from projected_disk_trial import ROOT,Perception,DetectionError

def affine_refine(self,image,seed,mask):
    aligned=cv2.warpPerspective(image,np.linalg.inv(seed),self.size)
    small=np.diag([.5,.5,1.])
    try:
        cc,h=cv2.findTransformECC(cv2.resize(self.reference_signal,(600,400)),
            cv2.resize(self.signal(aligned),(600,400)),np.eye(2,3,dtype=np.float32),
            cv2.MOTION_AFFINE,(cv2.TERM_CRITERIA_COUNT|cv2.TERM_CRITERIA_EPS,80,1e-6),
            cv2.resize(mask,(600,400),interpolation=cv2.INTER_NEAREST),5)
    except cv2.error as ex:raise DetectionError('Affine registration did not converge') from ex
    if not np.isfinite(cc) or cc<.8:raise DetectionError('Weak affine correlation')
    return float(cc),seed@np.linalg.inv(small)@np.vstack([h,[0,0,1]])@small

for name in sys.argv[1:]:
    events=[json.loads(s) for s in (ROOT/name).read_text().splitlines()]
    p=Perception('anchored_grid',5)
    p.tracker.anchor.refine=types.MethodType(affine_refine,p.tracker.anchor)
    rows=[]
    for e in events:
        if e['event']!='stationary_image_burst':continue
        try:
            r=p.measure(cv2.imread(e['median_image']),e['pose'])
            row=dict(ok=True,xy=r['error_xy_mm'],disk=r['tracking']['disk_group_spread_px'],extent=r['tracking']['extent_group_spread_px'])
        except DetectionError as ex:row=dict(ok=False,error=str(ex))
        rows.append(row)
    print(json.dumps(dict(log=name,passed=sum(x['ok'] for x in rows),total=len(rows),rows=rows)),flush=True)
