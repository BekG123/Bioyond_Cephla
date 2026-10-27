"""Live camera-only tracking of projected taught disks. Never commands the arm.

Uses only GET /frame and GET /state on the existing console. A fixed reference,
mutual SIFT matches and distributed RANSAC inliers prevent accumulating drift.
Tracking quality is image registration quality, not metric calibration accuracy.
"""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import time
from urllib.request import urlopen

import cv2
import numpy as np
from project_taught_disks import transform, quadrilateral
from vision import DetectionError


class Tracker:
    def __init__(self, reference, corners, outlines, mode='full'):
        if mode not in ('full','rim'):raise DetectionError('Unknown tracking mode.')
        self.mode=mode
        self.size=(1200,round(reference.shape[0]*1200/reference.shape[1]))
        self.scale=1200/reference.shape[1]
        self.corners=quadrilateral(corners)*self.scale
        self.outlines={k:np.array(v)*self.scale for k,v in outlines.items()}
        self.sift=cv2.SIFT_create(nfeatures=2500,contrastThreshold=.025)
        mask=np.zeros((self.size[1],self.size[0]),np.uint8)
        cv2.fillConvexPoly(mask,np.rint(self.corners).astype(np.int32),255)
        mask=cv2.erode(mask,np.ones((17,17),np.uint8))
        if self.mode=='rim':
            distance=cv2.distanceTransform(mask,cv2.DIST_L2,5)
            mask=np.uint8((distance>0)&(distance<35))*255
        self.reference_gray=self.feature_gray(reference)
        self.keys,self.desc=self.sift.detectAndCompute(self.reference_gray,mask)
        if self.desc is None or len(self.keys)<40:
            raise DetectionError('Too few reference features for tracking.')

    def gray(self, image):
        if abs(image.shape[1]/image.shape[0]-self.size[0]/self.size[1])>.005:
            raise DetectionError('Camera aspect ratio changed.')
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
        return cv2.resize(gray,self.size,interpolation=cv2.INTER_AREA)

    def feature_gray(self,image):
        gray=self.gray(image)
        return cv2.createCLAHE(2,(8,8)).apply(gray) if self.mode=='rim' else gray

    def track(self, image):
        gray=self.feature_gray(image)
        keys,desc=self.sift.detectAndCompute(gray,None)
        if desc is None or len(keys)<40: raise DetectionError('Plate texture unavailable.')
        matcher=cv2.BFMatcher(cv2.NORM_L2)
        ratio=.6 if self.mode=='rim' else .7
        def good(a,b):
            return {m.queryIdx:m.trainIdx for pair in matcher.knnMatch(a,b,k=2)
                    if len(pair)==2 for m,n in [pair] if m.distance<ratio*n.distance}
        fwd,rev=good(self.desc,desc),good(desc,self.desc)
        matches=[(i,j) for i,j in fwd.items() if rev.get(j)==i]
        if len(matches)<30: raise DetectionError('Fewer than 30 mutual plate-feature matches.')
        source=np.float32([self.keys[i].pt for i,j in matches])
        target=np.float32([keys[j].pt for i,j in matches])
        candidate_count=len(matches)
        if self.mode=='rim':
            # Align the image patches before translation-only LK refinement.
            # A descriptor-derived seed is not an accepted pose: final tracks
            # must still pass every independent flow/geometric quality gate.
            cv2.setRNGSeed(0)
            seed,seed_mask=cv2.findHomography(source,target,cv2.RANSAC,3.,maxIters=3000,confidence=.999)
            if seed is None or seed_mask is None or int(seed_mask.sum())<25:
                raise DetectionError('Insufficient rim geometry for patch rectification.')
            seed_inside=seed_mask.ravel().astype(bool)
            if cv2.contourArea(cv2.convexHull(source[seed_inside]))/cv2.contourArea(self.corners)<.35:
                raise DetectionError('Rim rectification seed has insufficient coverage.')
            inverse=np.linalg.inv(seed)
            rectified=cv2.warpPerspective(gray,inverse,self.size)
            seeded_target=transform(target,inverse).astype(np.float32)
            # More rim context stabilizes subpixel flow on this low-contrast,
            # transparent plate. Descriptor seeds still bound displacement;
            # neither the fixed reference nor acceptance gates are relaxed.
            # SIFT already supplies the large displacement. One pyramid level
            # keeps the refinement footprint from reaching far into the wells.
            settings=dict(winSize=(41,41),maxLevel=1,
                criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,40,.001),flags=cv2.OPTFLOW_USE_INITIAL_FLOW)
            forward,status,_=cv2.calcOpticalFlowPyrLK(self.reference_gray,rectified,source[:,None,:],seeded_target[:,None,:].copy(),**settings)
            if forward is None or status is None:raise DetectionError('Forward rim tracking failed.')
            reverse,back_status,_=cv2.calcOpticalFlowPyrLK(rectified,self.reference_gray,forward,source[:,None,:].copy(),**settings)
            if reverse is None or back_status is None:raise DetectionError('Reverse rim tracking failed.')
            refined=transform(forward[:,0,:],seed)
            valid=(status.ravel()>0)&(back_status.ravel()>0)&(np.linalg.norm(reverse[:,0,:]-source,axis=1)<.5)&(np.linalg.norm(refined-target,axis=1)<3)
            source=source[valid];target=refined[valid]
            if len(source)<25:raise DetectionError('Too few bidirectional rim tracks.')
            cv2.setRNGSeed(0)
        h,mask=cv2.findHomography(source,target,cv2.RANSAC,1.5,maxIters=3000,confidence=.999)
        if h is None or mask is None: raise DetectionError('No consistent plate transform.')
        inside=mask.ravel().astype(bool)
        # Keep the ORIGINAL descriptor-match denominator. Removing unreliable
        # optical-flow tracks must not artificially inflate the agreement rate.
        if inside.sum()<25 or inside.sum()/candidate_count<.65:
            raise DetectionError(f'Too many inconsistent plate matches: {int(inside.sum())}/{candidate_count} '
                                 f'({inside.sum()/candidate_count:.1%}) agree; require at least 25 and 65%. '
                                 f'{len(source)} survived refinement.')
        hull=cv2.contourArea(cv2.convexHull(source[inside]))/cv2.contourArea(self.corners)
        if hull<.35: raise DetectionError('Matches do not cover enough of the plate.')
        q=quadrilateral(transform(self.corners,h))
        area=cv2.contourArea(q)/cv2.contourArea(self.corners)
        angle=np.degrees(np.arctan2(*(q[1]-q[0])[::-1])-np.arctan2(*(self.corners[1]-self.corners[0])[::-1]))
        if not .65<area<1.5 or abs(angle)>30:
            raise DetectionError('Scale/orientation outside the local tracking range.')
        if np.any(q<3) or np.any(q[:,0]>self.size[0]-3) or np.any(q[:,1]>self.size[1]-3):
            raise DetectionError('Tracked plate is clipped.')
        errors=np.linalg.norm(transform(source[inside],h)-target[inside],axis=1)
        rms=float(np.sqrt(np.mean(errors**2)))
        if rms>.8 or errors.max()>2: raise DetectionError('Plate registration residual too large.')
        contours={k:transform(v,h) for k,v in self.outlines.items()}
        return dict(status='tracking',motion_authorized=False,metric_pose_estimated=False,
            tracking_mode=self.mode,inlier_fraction=float(inside.sum()/candidate_count),
            refinement_window_px=41 if self.mode=='rim' else None,
            patch_rectified=self.mode=='rim',
            refined_matches=len(source),
            orientation_resolved=False,coordinate_frame='preview_image_pixels',
            image_size_px=list(self.size),inliers=int(inside.sum()),matches=len(matches),
            coverage_fraction=float(hull),registration_rmse_px=rms,
            H_preview_from_reference_preview=h.tolist(),corners_px=q.tolist(),
            virtual_circles=[dict(label=k,pixels=v.tolist()) for k,v in contours.items()])


class Monitor:
    def __init__(self, report, output, mode='full'):
        self.report=json.loads(report.read_text())
        entry=self.report['images']['target']
        ref=Path(entry['path'])
        if hashlib.sha256(ref.read_bytes()).hexdigest()!=entry['sha256']:
            raise DetectionError('Reference image changed since annotation.')
        image=cv2.imread(str(ref))
        self.tracker=Tracker(image,self.report['corners_native_px']['target'],
            {c['label']:c['pixels'] for c in self.report['virtual_circles']},mode=mode)
        self.output=output
        output.mkdir(parents=True,exist_ok=True)
        self.count=0

    def observe(self):
        started=time.monotonic()
        with urlopen('http://127.0.0.1:5002/frame',timeout=6) as response:
            if response.headers.get('X-Error'): raise DetectionError(response.headers['X-Error'])
            data=response.read()
        with urlopen('http://127.0.0.1:5002/state',timeout=6) as response:
            state=json.load(response)
        camera=state.get('camera',{})
        if not camera.get('open') or camera.get('error') or camera.get('age_s',999)>.8:
            raise DetectionError('Camera frame is stale or unavailable.')
        image=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
        if image is None: raise DetectionError('Invalid camera image.')
        if time.monotonic()-started>3: raise DetectionError('Camera feedback took too long.')
        try:
            result=self.tracker.track(image)
        except DetectionError as error:
            result=dict(status='rejected',reason=str(error),motion_authorized=False)
        self.count+=1
        result.update(timestamp=time.time(),sample=self.count,camera=camera,
            robot_pose_mm=state.get('robot',{}).get('pose_mm'),
            note='Live perception only. No arm, gripper, controller or calibration commands are sent.')
        canvas=cv2.resize(image,self.tracker.size)
        for c in result.get('virtual_circles',[]):
            color=(0,190,255) if c['label']=='large' else (255,180,30)
            cv2.polylines(canvas,[np.rint(c['pixels']).astype(np.int32)],True,color,3)
        cv2.rectangle(canvas,(0,0),(canvas.shape[1],50),(25,25,25),-1)
        cv2.putText(canvas,'LIVE PERCEPTION ONLY - '+result['status'],(15,33),cv2.FONT_HERSHEY_SIMPLEX,.7,(255,255,255),2)
        if not cv2.imwrite(str(self.output/'latest.jpg'),canvas):
            raise OSError('Cannot save latest live overlay.')
        with (self.output/'observations.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(result)+'\n')
        ok,jpeg=cv2.imencode('.jpg',canvas)
        if not ok: raise DetectionError('Overlay encoding failed.')
        return dict(result=result,image=base64.b64encode(jpeg).decode())


PAGE='''<!doctype html><meta charset="utf-8"><title>Projected disks — live check</title>
<style>body{font:17px system-ui;background:#f5f6f8;color:#20252c;max-width:1200px;margin:30px auto}button{font:inherit;padding:10px 24px;border:1px solid #9aa6b2;border-radius:10px;background:white}img{width:100%;border-radius:14px}p{line-height:1.5}</style>
<h2>Projected disks · live camera check</h2><p>Perception only. This page cannot move the arm. Position calibration and descent height are not verified.</p>
<button id="toggle">Pause camera check</button><p id="status">Reading camera…</p><img id="view">
<script>let paused=false;toggle.onclick=()=>{paused=!paused;toggle.textContent=paused?'Resume camera check':'Pause camera check'};
async function tick(){if(!paused){try{const x=await(await fetch('/observe',{cache:'no-store'})).json();if(x.error){view.removeAttribute('src');statusText(x.error)}else{view.src='data:image/jpeg;base64,'+x.image;const r=x.result;statusText(r.status==='tracking'?`${(100*r.inlier_fraction).toFixed(1)}% agreement · ${r.inliers}/${r.matches} matches · error ${r.registration_rmse_px.toFixed(2)} px · no movement`:r.reason)}}catch(e){view.removeAttribute('src');statusText('Camera check unavailable')}}setTimeout(tick,1200)}function statusText(t){document.getElementById('status').textContent=t}tick();</script>'''


def serve(monitor,port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path=='/': payload=PAGE.encode();kind='text/html; charset=utf-8'
            elif self.path=='/observe':
                try: content=monitor.observe()
                except Exception as error: content=dict(error=str(error),motion_authorized=False)
                payload=json.dumps(content).encode();kind='application/json'
            else: self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',kind)
            self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(payload)
        def log_message(self,*args): pass
    HTTPServer(('127.0.0.1',port),Handler).serve_forever()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--samples',type=int,default=3)
    parser.add_argument('--serve',type=int)
    parser.add_argument('--tracking-mode',choices=('full','rim'),default='full')
    args=parser.parse_args()
    monitor=Monitor(args.reference,args.output,mode=args.tracking_mode)
    if args.serve: serve(monitor,args.serve)
    else:
        for i in range(args.samples):
            observation=monitor.observe()['result']
            print(json.dumps({k:v for k,v in observation.items() if k not in ('virtual_circles','H_preview_from_reference_preview','camera')},indent=2),flush=True)
            if i+1<args.samples: time.sleep(1)
