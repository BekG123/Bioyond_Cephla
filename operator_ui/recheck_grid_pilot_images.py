"""Replay saved image measurements offline; never connects to hardware."""
import json
import sys
import numpy as np
import cv2
from projected_disk_trial import ROOT,Perception,DetectionError

events=[json.loads(s) for s in (ROOT/sys.argv[1]).read_text().splitlines()]
p=Perception('anchored_grid',5)
for e in events:
    if e['event']!='stationary_image_burst':continue
    try:
        r=p.measure(cv2.imread(e['median_image']),e['pose'])
        print(json.dumps(dict(image=e['median_image'],ok=True,pose=e['pose'],error_xy=r['error_xy_mm'],initialization=r['tracking']['initialization'])),flush=True)
    except DetectionError as ex:print(json.dumps(dict(image=e['median_image'],ok=False,error=str(ex))),flush=True)
