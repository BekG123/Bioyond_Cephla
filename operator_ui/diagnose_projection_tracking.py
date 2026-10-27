"""Read-only post-pilot tracking diagnostic. No controller writes or retries."""
import json
from pathlib import Path
import sys
from urllib.request import urlopen
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'Pick and Hold/Align/plate_pose'))
from live_projection import Tracker


def main():
    ref=json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
    image=cv2.imread(ref['images']['target']['path'])
    tracker=Tracker(image,ref['corners_native_px']['target'],{c['label']:c['pixels'] for c in ref['virtual_circles']})
    with urlopen('http://127.0.0.1:5002/state',timeout=5) as response: before=json.load(response)
    with urlopen('http://127.0.0.1:5002/frame',timeout=5) as response:
        if response.headers.get('X-Error'): raise RuntimeError(response.headers['X-Error'])
        raw=response.read()
    with urlopen('http://127.0.0.1:5002/state',timeout=5) as response: after=json.load(response)
    start,end=before['robot']['pose_mm'],after['robot']['pose_mm']
    if any(abs(start[k]-end[k])>.1 for k in ('X','Y','Z')) or abs((start['Rz']-end['Rz']+180)%360-180)>.05:
        raise RuntimeError('Robot moved during diagnostic')
    if after['camera'].get('age_s',999)>.8: raise RuntimeError('Stale diagnostic frame')
    frame=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
    keys,desc=tracker.sift.detectAndCompute(tracker.gray(frame),None)
    matcher=cv2.BFMatcher(cv2.NORM_L2)
    def good(a,b):
        return {m.queryIdx:m.trainIdx for pair in matcher.knnMatch(a,b,k=2)
                if len(pair)==2 for m,n in [pair] if m.distance<.7*n.distance}
    fwd,rev=good(tracker.desc,desc),good(desc,tracker.desc)
    pairs=[(i,j) for i,j in fwd.items() if rev.get(j)==i]
    src=np.float32([tracker.keys[i].pt for i,j in pairs]);dst=np.float32([keys[j].pt for i,j in pairs])
    cv2.setRNGSeed(0)
    h,mask=cv2.findHomography(src,dst,cv2.RANSAC,1.5,maxIters=3000,confidence=.999)
    inliers=mask.ravel().astype(bool)
    center=tracker.corners.mean(axis=0)
    canvas=cv2.resize(frame,tracker.size)
    for p,ok in zip(dst,inliers):cv2.circle(canvas,tuple(np.rint(p).astype(int)),3,(50,220,50) if ok else (20,20,240),-1)
    result=dict(diagnostic_only=True,motion_started=False,
        pose=after['robot']['pose_mm'],controller_errors=after['robot']['errors'],
        matches=len(pairs),inliers=int(inliers.sum()),inlier_fraction=float(inliers.mean()),
        required_fraction=.65,median_inlier_shift_px=np.median(dst[inliers]-src[inliers],axis=0).tolist(),
        inlier_mean_reference_position_px=src[inliers].mean(axis=0).tolist(),
        outlier_mean_reference_position_px=src[~inliers].mean(axis=0).tolist(),
        cause='Single-plane registration did not meet its existing consistency threshold.' if inliers.mean()<.65 else 'This later stationary sample passed the inlier ratio; the failed physical trial remains stopped.')
    folder=ROOT/'operator_ui/reports/projected_disk_pilot/after_second_step'
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'raw.jpg').write_bytes(raw)
    cv2.imwrite(str(folder/'matches.jpg'),canvas)
    (folder/'diagnostic.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
