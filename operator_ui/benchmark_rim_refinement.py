"""Offline optical-flow ablation on fixed SIFT matches; no hardware access."""
import json
from pathlib import Path
import sys
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'Pick and Hold/Align/plate_pose'))
from live_projection import Tracker
from project_taught_disks import transform


def main():
    folder=ROOT/'operator_ui/reports/projected_disk_pilot/rim_refinement_20261026'
    report=json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
    src=cv2.imread(report['images']['target']['path'])
    dst=cv2.imread(str(folder/'validation_1.jpg'))
    tracker=Tracker(src,report['corners_native_px']['target'],
                    {c['label']:c['pixels'] for c in report['virtual_circles']},mode='rim')
    gray=tracker.feature_gray(dst);keys,desc=tracker.sift.detectAndCompute(gray,None)
    matcher=cv2.BFMatcher(cv2.NORM_L2)
    def good(a,b):
        return {m.queryIdx:m.trainIdx for pair in matcher.knnMatch(a,b,k=2)
                if len(pair)==2 for m,n in [pair] if m.distance<.6*n.distance}
    fwd,rev=good(tracker.desc,desc),good(desc,tracker.desc)
    pairs=[(i,j) for i,j in fwd.items() if rev.get(j)==i]
    source=np.float32([tracker.keys[i].pt for i,j in pairs]);target=np.float32([keys[j].pt for i,j in pairs])
    results=[]
    for pixels,a,b in [('clahe',tracker.reference_gray,gray),('raw',tracker.gray(src),tracker.gray(dst))]:
        for win in (11,15,21,31):
            for level in (0,1,2,3):
                settings=dict(winSize=(win,win),maxLevel=level,
                    criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,40,.001),flags=cv2.OPTFLOW_USE_INITIAL_FLOW)
                forward,status,_=cv2.calcOpticalFlowPyrLK(a,b,source[:,None,:],target[:,None,:].copy(),**settings)
                reverse,back_status,_=cv2.calcOpticalFlowPyrLK(b,a,forward,source[:,None,:].copy(),**settings)
                valid=(status.ravel()>0)&(back_status.ravel()>0)&(np.linalg.norm(reverse[:,0,:]-source,axis=1)<.5)&(np.linalg.norm(forward[:,0,:]-target,axis=1)<3)
                s,t=source[valid],forward[valid,0,:]
                if len(s)<4:continue
                cv2.setRNGSeed(0)
                h,mask=cv2.findHomography(s,t,cv2.RANSAC,1.5,maxIters=3000,confidence=.999)
                if h is None:continue
                inside=mask.ravel().astype(bool);errors=np.linalg.norm(transform(s[inside],h)-t[inside],axis=1)
                fraction=float(inside.sum()/len(source));rms=float(np.sqrt(np.mean(errors**2)))
                coverage=cv2.contourArea(cv2.convexHull(s[inside]))/cv2.contourArea(tracker.corners)
                results.append(dict(pixels=pixels,window=win,levels=level,matches=len(source),
                    flow_valid=int(valid.sum()),inliers=int(inside.sum()),fraction=fraction,rms=rms,coverage=coverage,
                    corners=transform(tracker.corners,h).tolist(),
                    agreement_and_residual_pass=bool(fraction>=.65 and rms<=.8 and errors.max()<=2 and coverage>=.35)))
    (folder/'flow_ablation.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps([{k:v for k,v in r.items() if k!='corners'} for r in results],indent=2))


if __name__=='__main__':main()
