"""Image-only well-grid detection for transparent 48/96-well plates.

Coordinates are dimensionless grid intervals and image pixels. This estimates
neither physical distance nor a grasp pose. Grid symmetry leaves A1 unknown.
No controller/camera imports, model calibration or production target writes.
"""
import argparse
import json
import math
from pathlib import Path
import cv2
import numpy as np
from vision import DetectionError


def supported(rows,columns):
    if (rows,columns) not in ((6,8),(8,12)):
        raise DetectionError('Choose a 6 x 8 or 8 x 12 grid.')


def clusters(values,count):
    """Deterministic one-dimensional clustering, ordered in image space."""
    centers=np.linspace(np.percentile(values,2),np.percentile(values,98),count)
    for _ in range(30):
        labels=np.argmin(abs(values[:,None]-centers[None,:]),axis=1)
        if len(set(labels))!=count:raise DetectionError('Grid does not span all expected rows/columns.')
        updated=np.array([np.median(values[labels==i]) for i in range(count)])
        if np.max(abs(updated-centers))<.001:break
        centers=updated
    gap=np.diff(centers)
    if min(gap)<.55*np.median(gap) or max(gap)>1.7*np.median(gap):
        raise DetectionError('Detected line spacing is inconsistent.')
    return labels


def fit_grid(points,rows=6,columns=8):
    supported(rows,columns)
    points=np.asarray(points,float)
    if points.ndim!=2 or points.shape[1]!=2 or not np.isfinite(points).all():
        raise DetectionError('Invalid measured centers.')
    required=math.ceil(rows*columns*5/6)
    if len(points)<required:raise DetectionError(f'Insufficient measured wells: {len(points)}; require at least {required}.')
    delta=points[None,:,:]-points[:,None,:]
    distance=np.linalg.norm(delta,axis=2);np.fill_diagonal(distance,np.inf)
    pitch=float(np.median(distance.min(axis=1)))
    if not math.isfinite(pitch) or pitch<=0:raise DetectionError('Measured wells are duplicate or degenerate.')
    pairs=delta[(distance>.75*pitch)&(distance<1.3*pitch)]
    angles=np.arctan2(pairs[:,1],pairs[:,0])
    # Adjacent rows and columns supply the two direction families.
    theta=float(np.angle(np.mean(np.exp(4j*angles)))/4)
    options=[]
    for candidate_angle in (theta,theta+math.pi/2):
        axes=np.array([[math.cos(candidate_angle),-math.sin(candidate_angle)],
                       [math.sin(candidate_angle),math.cos(candidate_angle)]])
        rotated=points@axes
        try:
            ci=clusters(rotated[:,0],columns);ri=clusters(rotated[:,1],rows)
        except DetectionError:continue
        ids=ri*columns+ci
        unique=np.array([i for i,x in enumerate(ids) if np.sum(ids==x)==1])
        if len(unique)<required:continue
        grid=np.column_stack([ci[unique],ri[unique]]).astype(float)
        h,mask=cv2.findHomography(grid,points[unique],cv2.RANSAC,.08*pitch)
        if h is None or mask is None:continue
        accepted=unique[mask.ravel().astype(bool)]
        if len(accepted)<required or len(set(ri[accepted]))!=rows or len(set(ci[accepted]))!=columns:continue
        # Require distributed support; a small regular patch cannot define the full plate.
        if min(np.bincount(ri[accepted],minlength=rows))<columns-2:continue
        if min(np.bincount(ci[accepted],minlength=columns))<rows-2:continue
        grid=np.column_stack([ci[accepted],ri[accepted]]).astype(float)
        h,_=cv2.findHomography(grid,points[accepted],0)
        predicted=cv2.perspectiveTransform(grid[None,:,:],h)[0]
        error=np.linalg.norm(predicted-points[accepted],axis=1)
        rmse=float(np.sqrt(np.mean(error**2)))
        if rmse>.06*pitch or error.max()>.15*pitch:continue
        options.append(dict(h=h,indices=accepted,grid=grid,rmse=rmse,pitch=pitch))
    if len(options)!=1:raise DetectionError('No unique complete grid layout; too few wells, outliers or excessive perspective.')
    result=options[0]
    result['points']=points[result['indices']]
    return result


def detect(image,rows=6,columns=8):
    supported(rows,columns)
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image.copy()
    factor=min(1.,1200/gray.shape[1])
    small=cv2.resize(gray,None,fx=factor,fy=factor,interpolation=cv2.INTER_AREA)
    enhanced=cv2.createCLAHE(2,(8,8)).apply(small)
    enhanced=cv2.GaussianBlur(enhanced,(5,5),1.2)
    # Broad range: well radii approximately 2–5% of image width in the initial
    # full-plate view. The grid fit, not a circle alone, determines acceptance.
    width=small.shape[1]
    layout_scale=8/columns
    circles=cv2.HoughCircles(enhanced,cv2.HOUGH_GRADIENT,1.2,width*.05*layout_scale,
        param1=80,param2=30,minRadius=round(width*.023*layout_scale),maxRadius=round(width*.046*layout_scale))
    if circles is None:raise DetectionError('No well-ring candidates found.')
    fit=fit_grid(circles[0,:,:2],rows,columns)
    scale=np.diag([1/factor,1/factor,1.])
    fit['h']=scale@fit['h'];fit['points']/=factor;fit['rmse']/=factor;fit['pitch']/=factor
    fit['candidate_count']=len(circles[0])
    return fit


def preview(image,rows=6,columns=8):
    fit=detect(image,rows,columns)
    h=fit['h'];overlay=cv2.cvtColor(image,cv2.COLOR_GRAY2BGR) if image.ndim==2 else image.copy()
    size=max(1,round(image.shape[1]/1200))
    def project(points):return cv2.perspectiveTransform(np.asarray(points,float)[None,:,:],h)[0]
    for r in range(rows):
        cv2.polylines(overlay,[np.rint(project([[0,r],[columns-1,r]])).astype(np.int32)],False,(0,170,70),size)
    for c in range(columns):
        cv2.polylines(overlay,[np.rint(project([[c,0],[c,rows-1]])).astype(np.int32)],False,(0,170,70),size)
    for p in fit['points']:cv2.circle(overlay,tuple(np.rint(p).astype(int)),4*size,(0,255,80),-1)
    virtual=[]
    for label,center,radius,color in [('large',[(columns-1)*.3,(rows-1)/2],.7,(0,190,255)),
                                      ('small',[(columns-1)*.7,(rows-1)/2],.35,(255,180,30))]:
        a=np.linspace(0,2*np.pi,100,endpoint=False)
        pixels=project(np.column_stack([center[0]+radius*np.cos(a),center[1]+radius*np.sin(a)]))
        cv2.polylines(overlay,[np.rint(pixels).astype(np.int32)],True,color,2*size)
        virtual.append(dict(label=label,center_grid_intervals=center,radius_grid_intervals=radius,pixels=pixels.tolist()))
    result=dict(status='image_grid_preview',offline_only=True,motion_authorized=False,
        coordinate_frame='raw_image_pixels',grid_size=dict(rows=rows,columns=columns),
        measured_wells=len(fit['points']),candidate_count=fit['candidate_count'],
        image_fit_rmse_px=fit['rmse'],well_pitch_px=fit['pitch'],
        H_image_from_grid_intervals=h.tolist(),well_centers_px=fit['points'].tolist(),
        grid_indices=fit['grid'].astype(int).tolist(),virtual_circles=virtual,
        orientation_resolved=False,metric_pose_estimated=False,
        blockers=['A1/orientation is not identified by the symmetric grid.',
                  'Physical dimensions and calibrated camera model are not supplied.',
                  'Circle positions are illustrative; original taught grasp mapping is not registered.',
                  'No live alignment, descent or grip target is produced.'])
    lines=[f"OFFLINE: {len(fit['points'])}/{rows*columns} measured wells | fit {fit['rmse']:.1f} px",
           'Illustrative circles only - A1, metric scale and grasp mapping unverified']
    for i,text in enumerate(lines):
        y=(30+i*28)*size
        cv2.rectangle(overlay,(8,y-24*size),(image.shape[1]-8,y+5*size),(25,25,25),-1)
        cv2.putText(overlay,text,(18,y),cv2.FONT_HERSHEY_SIMPLEX,.6*size,(255,255,255),size,cv2.LINE_AA)
    return result,overlay


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--rows',type=int,default=6);parser.add_argument('--columns',type=int,default=8)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    try:
        image=cv2.imread(str(args.image))
        if image is None:raise DetectionError('Cannot read saved input image.')
        result,overlay=preview(image,args.rows,args.columns)
        cv2.imwrite(str(args.output/'overlay.jpg'),overlay)
        result['input']=str(args.image.resolve())
    except (DetectionError,cv2.error) as error:
        result=dict(status='rejected',reason=str(error),offline_only=True,motion_authorized=False)
    (args.output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('H_image_from_grid_intervals','well_centers_px','grid_indices','virtual_circles')},indent=2))
    return 2 if result['status']=='rejected' else 0


if __name__=='__main__':raise SystemExit(main())
