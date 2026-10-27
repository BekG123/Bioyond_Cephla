"""Offline comparison of physically motivated feature masks; no motion access."""
import argparse
import json
from pathlib import Path
import sys
import time
from urllib.request import urlopen
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'Pick and Hold/Align/plate_pose'))
from live_projection import Tracker
from project_taught_disks import transform


def feature_masks(gray,corners):
    plate=np.zeros(gray.shape,np.uint8)
    cv2.fillConvexPoly(plate,np.rint(corners).astype(np.int32),255)
    plate=cv2.erode(plate,np.ones((17,17),np.uint8))
    yield 'baseline',plate
    distance=cv2.distanceTransform(plate,cv2.DIST_L2,5)
    for width in (35,60,90):
        yield 'rim_'+str(width),np.uint8((distance>0)&(distance<width))*255
    enhanced=cv2.createCLAHE(2,(8,8)).apply(gray)
    enhanced=cv2.GaussianBlur(enhanced,(5,5),1.2)
    circles=cv2.HoughCircles(enhanced,cv2.HOUGH_GRADIENT,1.2,60,param1=80,param2=30,minRadius=28,maxRadius=55)
    if circles is not None:
        for fraction in (.65,.8,.9):
            top=plate.copy()
            for x,y,r in circles[0]:cv2.circle(top,(round(float(x)),round(float(y))),round(float(r)*fraction),0,-1)
            yield 'exclude_well_interiors_'+str(fraction),top


def evaluate(source_gray,target_gray,mask,corners,preprocessing='raw',refine=False,match_ratio=.7):
    sift=cv2.SIFT_create(nfeatures=2500,contrastThreshold=.025)
    if preprocessing=='clahe':
        source_gray=cv2.createCLAHE(2,(8,8)).apply(source_gray)
        target_gray=cv2.createCLAHE(2,(8,8)).apply(target_gray)
    a,ad=sift.detectAndCompute(source_gray,mask);b,bd=sift.detectAndCompute(target_gray,None)
    if ad is None or bd is None:return dict(accepted=False,reason='no features')
    matcher=cv2.BFMatcher(cv2.NORM_L2)
    def good(x,y):
        return {m.queryIdx:m.trainIdx for pair in matcher.knnMatch(x,y,k=2)
                if len(pair)==2 for m,n in [pair] if m.distance<match_ratio*n.distance}
    fwd,rev=good(ad,bd),good(bd,ad)
    pairs=[(i,j) for i,j in fwd.items() if rev.get(j)==i]
    if len(pairs)<4:return dict(accepted=False,matches=len(pairs),reason='too few matches')
    src=np.float32([a[i].pt for i,j in pairs]);dst=np.float32([b[j].pt for i,j in pairs])
    candidate_count=len(pairs)
    if refine:
        forward,status,_=cv2.calcOpticalFlowPyrLK(source_gray,target_gray,src[:,None,:],dst[:,None,:].copy(),
            winSize=(21,21),maxLevel=3,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,40,.001),flags=cv2.OPTFLOW_USE_INITIAL_FLOW)
        reverse,back_status,_=cv2.calcOpticalFlowPyrLK(target_gray,source_gray,forward,src[:,None,:].copy(),
            winSize=(21,21),maxLevel=3,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,40,.001),flags=cv2.OPTFLOW_USE_INITIAL_FLOW)
        good_flow=(status.ravel()>0)&(back_status.ravel()>0)&(np.linalg.norm(reverse[:,0,:]-src,axis=1)<.5)&(np.linalg.norm(forward[:,0,:]-dst,axis=1)<3)
        src=src[good_flow];dst=forward[good_flow,0,:]
        if len(src)<4:return dict(accepted=False,matches=candidate_count,reason='too few bidirectional tracks')
    cv2.setRNGSeed(0)
    h,inside=cv2.findHomography(src,dst,cv2.RANSAC,1.5,maxIters=3000,confidence=.999)
    if h is None:return dict(accepted=False,reason='no homography')
    inside=inside.ravel().astype(bool)
    errors=np.linalg.norm(transform(src[inside],h)-dst[inside],axis=1)
    coverage=cv2.contourArea(cv2.convexHull(src[inside]))/cv2.contourArea(corners.astype(np.float32))
    rms=float(np.sqrt(np.mean(errors**2)))
    q=transform(corners,h)
    area=cv2.contourArea(q.astype(np.float32))/cv2.contourArea(corners.astype(np.float32))
    angle=np.degrees(np.arctan2(*(q[1]-q[0])[::-1])-np.arctan2(*(corners[1]-corners[0])[::-1]))
    accepted=(len(pairs)>=30 and inside.sum()>=25 and inside.sum()/candidate_count>=.65 and coverage>=.35
        and rms<=.8 and errors.max()<=2 and .65<area<1.5 and abs(angle)<=30
        and cv2.isContourConvex(q.astype(np.float32)) and np.min(q)>=3
        and np.max(q[:,0])<=source_gray.shape[1]-3 and np.max(q[:,1])<=source_gray.shape[0]-3)
    return dict(accepted=bool(accepted),reference_features=len(a),matches=candidate_count,refined_matches=len(src),inliers=int(inside.sum()),
        inlier_fraction=float(inside.sum()/candidate_count),coverage=float(coverage),rmse_px=rms,max_error_px=float(errors.max()),
        corners_px=q.tolist(),H=h.tolist())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--target',type=Path,default=ROOT/'operator_ui/reports/projected_disk_pilot/after_second_step/raw.jpg')
    parser.add_argument('--refine',action='store_true')
    parser.add_argument('--validate-fresh',type=int,default=0)
    parser.add_argument('--match-ratio',type=float,default=.7)
    args=parser.parse_args()
    r=json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
    src=cv2.imread(r['images']['target']['path'])
    tracker=Tracker(src,r['corners_native_px']['target'],{c['label']:c['pixels'] for c in r['virtual_circles']})
    gray=tracker.gray(src)
    if args.validate_fresh:
        masks=dict(feature_masks(gray,tracker.corners))
        results=[]
        args.output.parent.mkdir(parents=True,exist_ok=True)
        origin=None
        for sample in range(args.validate_fresh):
            with urlopen('http://127.0.0.1:5002/state',timeout=5) as response: before=json.load(response)
            with urlopen('http://127.0.0.1:5002/frame',timeout=5) as response:
                if response.headers.get('X-Error'):raise RuntimeError(response.headers['X-Error'])
                data=response.read()
            with urlopen('http://127.0.0.1:5002/state',timeout=5) as response: after=json.load(response)
            poses=[before['robot']['pose_mm'],after['robot']['pose_mm']]
            origin=origin or poses[0]
            if any(any(abs(p[k]-origin[k])>.1 for k in ('X','Y','Z')) or abs((p['Rz']-origin['Rz']+180)%360-180)>.05 for p in poses):
                raise RuntimeError('Arm moved during stationary validation')
            if after['camera'].get('age_s',999)>.8:raise RuntimeError('Stale validation frame')
            path=args.output.parent/('validation_'+str(sample+1)+'.jpg');path.write_bytes(data)
            target=tracker.gray(cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR))
            for name,pre,refine in [('baseline','raw',False),('rim_35','clahe',True),('exclude_well_interiors_0.9','clahe',True)]:
                ratio=.7 if name=='baseline' else args.match_ratio
                result=evaluate(gray,target,masks[name],tracker.corners,pre,refine,ratio)
                results.append(dict(sample=sample+1,mask=name,preprocessing=pre,subpixel_refinement=refine,match_ratio=ratio,**result))
            if sample+1<args.validate_fresh:time.sleep(1)
        args.output.write_text(json.dumps(dict(stationary_validation=True,motion_started=False,pose=origin,results=results),indent=2),encoding='utf-8')
        print(json.dumps([{k:row.get(k) for k in ('sample','mask','accepted','matches','inliers','inlier_fraction','rmse_px','coverage')} for row in results],indent=2))
        return
    target=tracker.gray(cv2.imread(str(args.target)))
    report=[]
    for name,mask in feature_masks(gray,tracker.corners):
        for pre in ('raw','clahe'):
            result=evaluate(gray,target,mask,tracker.corners,pre,args.refine,args.match_ratio)
            report.append(dict(mask=name,preprocessing=pre,subpixel_refinement=args.refine,match_ratio=args.match_ratio,**result))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(dict(offline_only=True,motion_authorized=False,target=str(args.target),results=report),indent=2),encoding='utf-8')
    print(json.dumps([{k:v for k,v in row.items() if k not in ('H','corners_px')} for row in report],indent=2))


if __name__=='__main__':main()
