"""Offline-only comparison; never connects to hardware or edits reference images."""
import json
import types
import cv2
import numpy as np
from pathlib import Path
from projected_alignment import perception_at_height, target_from_mark
from plate48_workflow import reference, match_placement
from vision import DetectionError

ROOT=Path(__file__).resolve().parents[1]


def full_refine(self,image,seed,mask):
    aligned=cv2.warpPerspective(image,np.linalg.inv(seed),self.size)
    initial=np.eye(3,dtype=np.float32)[:2]
    cc,h=cv2.findTransformECC(self.reference_signal,self.signal(aligned),initial,
        cv2.MOTION_AFFINE,(cv2.TERM_CRITERIA_COUNT|cv2.TERM_CRITERIA_EPS,100,1e-7),mask,5)
    if not np.isfinite(cc) or cc<.8:raise DetectionError('Weak full-resolution fit')
    return float(cc),seed@np.vstack([h,[0.,0.,1.]])


if __name__=='__main__':
    rows=json.loads((ROOT/'operator_ui/reports/plate48_diagnosis_20261101/replay.json').read_text())
    p,_,_=perception_at_height()
    p.tracker.anchor.refine=types.MethodType(full_refine,p.tracker.anchor)
    raw=reference(require_grip=False)[2]
    for row in rows:
        p.tracker.previous_verified_seed=None
        try:
            m=p.measure(cv2.imread(row['image']),row['pose'])
            target=target_from_mark(row['pose'],m,p.cfg)
            match_placement(target,raw)
            print(json.dumps(dict(case=row['case'],ok=True,target=target,
                disks=m['tracking']['disk_group_spread_px'],extent=m['tracking']['extent_group_spread_px'])),flush=True)
        except Exception as e:print(json.dumps(dict(case=row['case'],ok=False,error=str(e))),flush=True)
