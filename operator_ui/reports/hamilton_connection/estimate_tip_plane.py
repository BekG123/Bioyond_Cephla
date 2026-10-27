"""Offline camera pose investigation. Never issues motion or calibration writes."""
import json
import argparse
from pathlib import Path
import cv2
import numpy as np
import hashlib

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root',type=Path,default=Path(__file__).parent/'camera_height_comparison')
root=parser.parse_args().root
d=json.loads((root/'deck-calibration.json').read_text())
K=np.array(d['CameraCalibration']['CameraMatrix']['Data'],dtype=float)
dist=np.array(d['CameraCalibration']['DistortionCoefficients']['Data'],dtype=float)
Rdeck=np.array(d['Rotation']['Data'],dtype=float)
tdeck=np.array(d['Translation']['Data'],dtype=float).reshape(3)
raw=cv2.imread(str(root/'raw_current.png'),0)
full=cv2.undistort(raw,K,dist,None,K)
crop=cv2.imread(str(root/'crop_current75.png'),0)
sift=cv2.SIFT_create(nfeatures=5000)
# Deck-coordinate crops may reverse image handedness; SIFT itself is not
# reflection invariant. Return feature coordinates to the original crop.
k1,d1=sift.detectAndCompute(cv2.flip(crop,1),None)
k2,d2=sift.detectAndCompute(full,None)
pairs=cv2.BFMatcher().knnMatch(d1,d2,k=2)
good=[m for m,n in pairs if m.distance<.65*n.distance]
src=np.float32([[crop.shape[1]-1-k1[m.queryIdx].pt[0],k1[m.queryIdx].pt[1]] for m in good])
dst=np.float32([k2[m.trainIdx].pt for m in good])
H,mask=cv2.findHomography(src,dst,cv2.RANSAC,2)
assert H is not None and mask.sum()>50, 'Insufficient crop registration'
proj=cv2.perspectiveTransform(src.reshape(-1,1,2),H).reshape(-1,2)
registration_rms=float(np.sqrt(np.mean(np.sum((proj[mask.ravel()>0]-dst[mask.ravel()>0])**2,axis=1))))

detected=cv2.HoughCircles(cv2.GaussianBlur(crop,(5,5),1),cv2.HOUGH_GRADIENT,
    1,38,param1=80,param2=24,minRadius=19,maxRadius=27)
if detected is None:
    raise SystemExit('No tip-rim grid detected at the selected site; no alignment estimate produced.')
circles=detected[0]
points=[]
for x,y,radius in circles:
    col=int(round((x-96)/56.1));row=int(round((y-83)/55.6))
    if 0<=col<12 and 0<=row<8:
        points.append((col,row,float(x),float(y)))
points=np.array(points)
design=np.c_[points[:,:2],np.ones(len(points))]
keep=np.ones(len(points),dtype=bool)
for _ in range(5):
    fit=np.linalg.lstsq(design[keep],points[keep,2:],rcond=None)[0]
    keep=np.linalg.norm(design@fit-points[:,2:],axis=1)<3
points=points[keep]
assert len(points)>50
obj=np.c_[points[:,:2]*9,np.zeros(len(points))].astype(np.float64)
image=cv2.perspectiveTransform(points[:,2:].astype(np.float64).reshape(-1,1,2),H).reshape(-1,2)
ok,rv,tv=cv2.solvePnP(obj,image,K,np.zeros(5),flags=cv2.SOLVEPNP_ITERATIVE)
assert ok
Rtip=cv2.Rodrigues(rv)[0]
pred=cv2.projectPoints(obj,rv,tv,K,np.zeros(5))[0].reshape(-1,2)
camera_center=Rtip@np.array([49.5,31.5,0])+tv.ravel()
deck_center=Rdeck.T@(camera_center-tdeck)
deck_normal=Rdeck.T@Rtip[:,2]
expected_crop_center=np.array([[[405.0,270.5]]],dtype=np.float64)
expected_pixel=cv2.perspectiveTransform(expected_crop_center,H).reshape(2)
camera_origin=-Rdeck.T@tdeck
ray=Rdeck.T@np.linalg.inv(K)@np.r_[expected_pixel,1]
expected_deck_center=camera_origin+(75-camera_origin[2])/ray[2]*ray
grid_indices=np.array([(col,row) for row in range(8) for col in range(12)],dtype=float)
grid_object=np.c_[grid_indices*9,np.zeros(96)]
grid_camera=(Rtip@grid_object.T).T+tv.ravel()
grid_export=(Rdeck.T@(grid_camera-tdeck).T).T
grid_crop=np.c_[grid_indices,np.ones(96)]@fit
observed={(int(p[0]),int(p[1])) for p in points}
preview=cv2.cvtColor(crop,cv2.COLOR_GRAY2BGR)
for index,pixel in zip(grid_indices,grid_crop):
    color=(80,200,80) if tuple(map(int,index)) in observed else (0,170,255)
    cv2.circle(preview,tuple(np.round(pixel).astype(int)),5,color,2)
# Select well-separated openings in the same image column for review only.
# Row/column orientation has not been mapped to vendor A1 or channel order.
selected=[(5,2),(5,5)]
for number,index in enumerate(selected,1):
    pixel=grid_crop[index[1]*12+index[0]]
    xy=tuple(np.round(pixel).astype(int))
    cv2.circle(preview,xy,19,(255,180,0),3)
    cv2.putText(preview,str(number),(xy[0]+20,xy[1]),cv2.FONT_HERSHEY_SIMPLEX,.65,(255,180,0),2)
preview=cv2.copyMakeBorder(preview,40,0,0,0,cv2.BORDER_CONSTANT,value=(25,25,25))
cv2.putText(preview,'ALIGNMENT PREVIEW - not a motion target',(12,27),cv2.FONT_HERSHEY_SIMPLEX,.65,(255,255,255),1)
cv2.imwrite(str(root/'alignment_preview.png'),preview)
corners=np.array([[0.,0.],[crop.shape[1]-1.,0.],[crop.shape[1]-1.,crop.shape[0]-1.],[0.,crop.shape[0]-1.]])
result={
    'purpose':'Exploratory estimate in exported calibration coordinates, not an executable motion target',
    'assumptions':['Nominal 9 mm pitch','Detected outer-rim centers approximate the opening plane',
        'Export rotation/translation map deck coordinates to camera coordinates',
        'Calibration matrix applies to full-resolution raw camera image',
        'Physical rack unchanged during captures'],
    'crop_match_count':len(good),'crop_registration_inliers':int(mask.sum()),
    'crop_registration_rms_pixels':registration_rms,
    'crop_corners_in_undistorted_full_image':cv2.perspectiveTransform(corners.reshape(-1,1,2),H).reshape(-1,2).tolist(),
    'tip_rims_used':len(points),
    'pose_reprojection_rms_pixels':float(np.sqrt(np.mean(np.sum((pred-image)**2,axis=1)))),
    'estimated_grid_center_in_exported_deck_frame':deck_center.tolist(),
    'overlay_center_intersected_with_exported_z75_plane':expected_deck_center.tolist(),
    'estimated_xy_difference_from_overlay_reference_mm':(deck_center[:2]-expected_deck_center[:2]).tolist(),
    'estimated_plane_normal_in_exported_deck_frame':deck_normal.tolist(),
    'estimated_tilt_degrees':float(np.degrees(np.arccos(np.clip(abs(deck_normal[2])/np.linalg.norm(deck_normal),0,1)))),
    'operator_height_above_metal_deck_mm':75,
    'deck_frame_origin_relative_to_metal_surface_verified':False,
    'motion_authorized_by_this_estimate':False,
    'calibration_sha256':hashlib.sha256((root/'deck-calibration.json').read_bytes()).hexdigest(),
    'raw_image_sha256':hashlib.sha256((root/'raw_current.png').read_bytes()).hexdigest(),
    'grid_index_convention':'Zero-based columns left-to-right and rows top-to-bottom in crop; not vendor well names',
    'grid_basis_in_exported_frame':(Rdeck.T@Rtip).tolist(),
    'grid_points':[
        {'column':int(index[0]),'row':int(index[1]),'observed':tuple(map(int,index)) in observed,
         'crop_pixel':pixel.tolist(),'exported_frame_xyz_mm':xyz.tolist()}
        for index,pixel,xyz in zip(grid_indices,grid_crop,grid_export)
    ],
    'selected_preview_openings':[{'column':col,'row':row} for col,row in selected],
    'controller_targets':None,
    'blockers':['Camera-to-controller transform has not been independently verified',
                'Physical metal reference and firmware Z origin are not reconciled',
                'Pickup seating depth and direct-driver stop/interlock behavior are not commissioned'],
}
(root/'tip_plane_estimate.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='grid_points'},indent=2))
