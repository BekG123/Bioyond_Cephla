"""Read-only current-camera grid initialization diagnostic. No motion calls."""
from check_multiview_rim import ROOT,cv2,json,DetectionError
from grid_pattern import commissioned_grid_tracker
from live_projection import Tracker
from project_taught_disks import transform
from urllib.request import urlopen
import numpy as np
import time
r=json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
ref=cv2.imread(r['images']['target']['path'])
t=commissioned_grid_tracker(ROOT,r,ref)
seed_tracker=Tracker(t.anchor.ref,t.anchor.corners,t.anchor.outlines,mode='rim')
landmarks=np.vstack([t.original.corners,*t.original.outlines.values()])
for n in range(5):
    with urlopen('http://127.0.0.1:5002/frame',timeout=6) as response:
        if response.headers.get('X-Error'):raise RuntimeError(response.headers['X-Error'])
        frame=cv2.imdecode(np.frombuffer(response.read(),np.uint8),cv2.IMREAD_COLOR)
    try:
        keys,desc=seed_tracker.sift.detectAndCompute(seed_tracker.feature_gray(frame),None)
        matcher=cv2.BFMatcher(cv2.NORM_L2)
        def match(a,b):return {m.queryIdx:m.trainIdx for pair in matcher.knnMatch(a,b,k=2) if len(pair)==2 for m,q in [pair] if m.distance<.7*q.distance}
        forward=match(seed_tracker.desc,desc);reverse=match(desc,seed_tracker.desc)
        pairs=[(i,j) for i,j in forward.items() if reverse.get(j)==i]
        source=np.float32([seed_tracker.keys[i].pt for i,j in pairs]);target=np.float32([keys[j].pt for i,j in pairs])
        h,inside=cv2.findHomography(source,target,cv2.RANSAC,3.,maxIters=3000,confidence=.999)
        if inside is None or inside.sum()<25:raise DetectionError('Insufficient texture seed')
        a=t.anchor.track(frame,seed=h)
        combinations=[transform(landmarks,np.array(b)@np.array(h)) for b in a['group_homographies'] for h in t.registration['group_homographies']]
        errors=np.array([np.linalg.norm(x-y,axis=1) for x in combinations for y in combinations])
        print(json.dumps(dict(frame=n+1,seed_inliers=int(inside.sum()),seed_matches=len(pairs),wells=a['supported_wells'],
            disk_spread=float(errors[:,4:].max()),extent_spread=float(errors.max()),correlations=a['pattern_correlations'])),flush=True)
    except DetectionError as e:print(json.dumps(dict(frame=n+1,error=str(e))),flush=True)
    time.sleep(1)
