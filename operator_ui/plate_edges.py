"""Image-only plate corner/edge centering experiment. NEVER commands a robot.

No circle/ArUco detection, no assumed pixel-to-robot scale. A detected outline
needs operator verification before commissioning any closed-loop motion.
"""
from __future__ import annotations

import argparse
import json
import math
import itertools
from pathlib import Path

import cv2
import numpy as np


def ordered_corners(points):
    p = np.asarray(points, np.float32).reshape(4,2)
    c = p.mean(axis=0)
    p = p[np.argsort(np.arctan2(p[:,1]-c[1],p[:,0]-c[0]))]
    return np.roll(p,-int(np.argmin(p.sum(axis=1))),axis=0)


def quad_metrics(quad):
    p = ordered_corners(quad)
    v = np.roll(p,-1,axis=0)-p
    lengths = np.linalg.norm(v,axis=1)
    if min(lengths) < 1:
        return None
    # Mild perspective is allowed, but not arbitrary trapezoids/backgrounds.
    cosines = [abs(float(np.dot(v[i],v[(i+1)%4])/(lengths[i]*lengths[(i+1)%4]))) for i in range(4)]
    if max(cosines) > .30:
        return None
    sides = [(lengths[0]+lengths[2])/2,(lengths[1]+lengths[3])/2]
    ratio = max(sides)/min(sides)
    if not 1.15 <= ratio <= 2.3:
        return None
    if max(lengths[0]/lengths[2],lengths[2]/lengths[0],
           lengths[1]/lengths[3],lengths[3]/lengths[1]) > 1.3:
        return None
    long_i = 0 if sides[0] >= sides[1] else 1
    axis = v[long_i]/lengths[long_i] - v[(long_i+2)%4]/lengths[(long_i+2)%4]
    angle = (math.degrees(math.atan2(float(axis[1]),float(axis[0])))+90)%180-90
    return p, lengths, ratio, angle


def plate_center(corners):
    """Intersection of diagonals: projected center of a planar rectangle."""
    p=ordered_corners(corners)
    a,b=p[2]-p[0],p[3]-p[1]
    t=np.linalg.solve(np.column_stack((a,-b)),p[1]-p[0])[0]
    return p[0]+t*a


def line_quads(gray):
    """Fit interrupted straight sides; no marker/circle or known plate pose.

    Returns hypotheses only. The common geometry, visibility and independent
    Canny edge-support checks below must still accept all four sides.
    """
    raw = cv2.createLineSegmentDetector().detect(gray)[0]
    if raw is None:
        return []
    lines = []
    for row in raw.reshape(-1,4):
        a,b = row[:2],row[2:]
        length = float(np.linalg.norm(b-a))
        if length >= 35:
            angle = math.atan2(float(b[1]-a[1]),float(b[0]-a[0]))
            lines.append((a,b,length,angle))
    if len(lines) < 4:
        return []
    orientations = sorted(lines,key=lambda x:-x[2])[:8]
    hypotheses = []
    for _,_,_,theta in orientations:
        theta %= math.pi/2
        u=np.array([math.cos(theta),math.sin(theta)])
        v=np.array([-u[1],u[0]])
        groups=[[],[]]
        for a,b,length,angle in sorted(lines,key=lambda x:-x[2]):
            direction=(b-a)/length
            for kind,axis,normal in ((0,u,v),(1,v,u)):
                if abs(np.dot(direction,axis)) < math.cos(math.radians(9)):
                    continue
                offset=float(np.dot((a+b)/2,normal))
                match=next((g for g in groups[kind] if abs(g['offset']-offset)<8),None)
                if match is None:
                    match=dict(offset=offset,points=[],length=0)
                    groups[kind].append(match)
                match['points'].extend([a,b])
                match['length']+=length
        for gs in groups:
            gs.sort(key=lambda g:-g['length'])
            del gs[10:]
            for g in gs:
                dx,dy,x,y=cv2.fitLine(np.array(g['points'],np.float32),cv2.DIST_L2,0,.01,.01).reshape(-1)
                g['normal']=np.array([-dy,dx])
                g['d']=float(-dy*x+dx*y)
        def intersect(a,b):
            mat=np.array([a['normal'],b['normal']])
            if abs(np.linalg.det(mat)) < .5:
                return None
            return np.linalg.solve(mat,np.array([a['d'],b['d']]))
        for hs in itertools.combinations(groups[0],2):
            if abs(hs[0]['offset']-hs[1]['offset'])<100:
                continue
            for vs in itertools.combinations(groups[1],2):
                if abs(vs[0]['offset']-vs[1]['offset'])<100:
                    continue
                corners=[intersect(hs[i],vs[j]) for i,j in ((0,0),(0,1),(1,1),(1,0))]
                if all(c is not None for c in corners):
                    hypotheses.append(np.array(corners,np.float32))
    return hypotheses


def detect_plate(image):
    if image is None or image.size == 0:
        raise ValueError('image unavailable')
    gray = cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    h,w = gray.shape
    scale = min(1.,960/max(h,w))
    gray = cv2.resize(gray,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
    sh,sw = gray.shape
    enhanced = cv2.createCLAHE(clipLimit=2,tileGridSize=(8,8)).apply(gray)
    blur = cv2.GaussianBlur(enhanced,(5,5),0)
    candidates = []
    diagnostic_edges = cv2.Canny(blur,10,30)
    def accept(q,distance,method):
        metrics=quad_metrics(q)
        if metrics is None:
            return
        p,lengths,ratio,angle=metrics
        area=abs(cv2.contourArea(p))
        if not .08*sw*sh <= area <= .85*sw*sh:
            return
        if (p[:,0].min()<4 or p[:,1].min()<4 or
                p[:,0].max()>sw-5 or p[:,1].max()>sh-5):
            return
        support=[]
        for i in range(4):
            points=np.rint(p[i]+np.linspace(.08,.92,100)[:,None]*(p[(i+1)%4]-p[i])).astype(int)
            support.append(float(np.mean(distance[points[:,1],points[:,0]]<=4)))
        if min(support)<.65:
            return
        candidate=dict(corners=(p/scale).tolist(),center_px=(plate_center(p)/scale).tolist(),
                       angle_image_deg=angle,aspect_ratio=float(ratio),side_support=support,
                       score=float(min(support)),method=method)
        duplicate=next((c for c in candidates if np.linalg.norm(
            np.asarray(c['corners'])-np.asarray(candidate['corners']),axis=1).mean()<20/scale),None)
        if duplicate is None:
            candidates.append(candidate)
        elif candidate['score']>duplicate['score']:
            duplicate.update(candidate)
    for low,high in ((5,15),(10,30),(20,60),(40,100)):
        edges = cv2.Canny(blur,low,high)
        distance = cv2.distanceTransform(255-edges,cv2.DIST_L2,3)
        for kernel in (3,7,13):
            joined = cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((kernel,kernel),np.uint8))
            contours,_ = cv2.findContours(joined,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = abs(cv2.contourArea(contour))
                if not .08*sw*sh <= area <= .85*sw*sh:
                    continue
                hull = cv2.convexHull(contour)
                if area/max(1,cv2.contourArea(hull)) < .88:
                    continue
                for epsilon in (.012,.02,.03):
                    q = cv2.approxPolyDP(hull,epsilon*cv2.arcLength(hull,True),True)
                    if len(q) != 4:
                        continue
                    accept(q,distance,'closed_contour')
    distance=cv2.distanceTransform(255-diagnostic_edges,cv2.DIST_L2,3)
    for quad in line_quads(enhanced):
        accept(quad,distance,'four_fitted_sides')
    base = dict(image_size=[w,h],image_center_px=[(w-1)/2,(h-1)/2],
                motion_authorized=False, units='pixels/degrees in image only',
                center_definition='intersection of fitted plate diagonals',
                candidate_count=len(candidates))
    if len(candidates) != 1:
        reason = ('No reliably closed four-sided plate outline. All four corners/edges '
                  'must be visible with stronger contrast; no center or robot motion inferred.'
                  if not candidates else 'Multiple rectangular outlines: select/verify the plate; no motion inferred.')
        return {**base,'detected':False,'reason':reason,'candidates':candidates},diagnostic_edges
    plate = candidates[0]
    dx,dy = np.array(plate['center_px'])-np.array(base['image_center_px'])
    return {**base,**plate,'detected':True,'offset_px':[float(dx),float(dy)],
            'offset_fraction':[float(dx/w),float(dy/h)],
            'desired_image_rotation_deg':-plate['angle_image_deg'],
            'note':'Image centering is not gripper alignment or a metric robot command.'},diagnostic_edges


def annotate(image,result,edges):
    out = cv2.cvtColor(image,cv2.COLOR_GRAY2BGR) if image.ndim == 2 else image.copy()
    h,w = out.shape[:2]
    cx,cy = np.rint(result['image_center_px']).astype(int)
    cv2.drawMarker(out,(cx,cy),(255,180,0),cv2.MARKER_CROSS,70,3)
    # Image frame corners are the coordinate reference, not targets for the
    # plate corners: no demand to enlarge the plate to fill the whole image.
    cv2.rectangle(out,(8,8),(w-9,h-9),(255,180,0),3)
    if result['detected']:
        p=np.rint(result['corners']).astype(np.int32)
        cv2.polylines(out,[p],True,(0,255,0),4)
        for i,point in enumerate(p):
            cv2.circle(out,tuple(point),12,(0,255,255),-1)
            cv2.putText(out,str(i+1),tuple(point+[15,-15]),cv2.FONT_HERSHEY_SIMPLEX,1,(0,255,255),2)
        center=tuple(np.rint(result['center_px']).astype(int))
        cv2.drawMarker(out,center,(0,255,0),cv2.MARKER_CROSS,50,3)
        cv2.arrowedLine(out,center,(cx,cy),(0,255,255),4)
        label=f"Plate offset: {result['offset_px'][0]:+.1f}, {result['offset_px'][1]:+.1f} px; image angle {result['angle_image_deg']:+.2f} deg"
    else:
        edge_full=cv2.resize(edges,(w,h),interpolation=cv2.INTER_NEAREST)
        out[edge_full>0]=(0,220,255)
        label='NO VERIFIED 4-CORNER OUTLINE - image-only test, no motion'
    cv2.rectangle(out,(0,0),(w,65),(25,25,25),-1)
    cv2.putText(out,label,(20,44),cv2.FONT_HERSHEY_SIMPLEX,1,(255,255,255),2)
    return out


def preview_file(input_path,output_path):
    image = cv2.imread(str(input_path))
    result,edges = detect_plate(image)
    if not cv2.imwrite(str(output_path),annotate(image,result,edges)):
        raise RuntimeError('could not save edge diagnostic')
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    if Path(args.image).resolve() == Path(args.output).resolve():
        parser.error('output must not overwrite the source image')
    print(json.dumps(preview_file(args.image,args.output),indent=2))
