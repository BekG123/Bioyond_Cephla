import sys,json,math
from pathlib import Path
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'operator_ui'),str(ROOT/'Pick and Hold/Align/plate_pose')]
from grid_preview import fit_grid,clusters
from cellvis24_calibration import reference
from rim_edges import rim_edges
d=reference();seed=json.loads((ROOT/d['files']['seed']['path']).read_bytes())['fitted']
folder=ROOT/'operator_ui/reports/plate_session/cellvis24_adjustments/59cf68706a604467ab9ff5113f421f0d'
results=[]
for file in list(folder.glob('prepared_median_*.png'))+list((folder/'trial').glob('prepared_median_*.png')):
    image=cv2.imread(str(file));gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    small=cv2.resize(gray,None,fx=1200/3072,fy=1200/3072,interpolation=cv2.INTER_AREA)
    enhanced=cv2.GaussianBlur(cv2.createCLAHE(2,(8,8)).apply(small),(5,5),1.2)
    circles=cv2.HoughCircles(enhanced,cv2.HOUGH_GRADIENT,1.2,80,param1=80,param2=30,minRadius=37,maxRadius=74)[0]
    corners,edges=rim_edges(cv2.resize(image,(1200,800)),seed,polarities=[-1]*4,half_width=14)
    inside=np.array([cv2.pointPolygonTest(corners.astype(np.float32),tuple(map(float,p[:2])),True)>p[2]*.5 for p in circles])
    item=dict(file=str(file),count=len(circles),outside=circles[~inside].tolist(),corners=corners.tolist(),modes={})
    overlay=cv2.resize(image,(1200,800))
    for i,(x,y,r) in enumerate(circles):
        color=(0,255,0) if inside[i] else (0,0,255)
        cv2.circle(overlay,(round(x),round(y)),round(r),color,2)
        cv2.putText(overlay,str(i),(round(x),round(y)),cv2.FONT_HERSHEY_SIMPLEX,.5,color,1)
    cv2.polylines(overlay,[np.rint(corners).astype(np.int32)],True,(255,0,0),2)
    cv2.imwrite(str(file.with_name(file.stem+'_candidates.jpg')),overlay)
    for name,pts in [('all',circles[:,:2]),('rim_inside',circles[inside,:2])]:
        try:
            fit=fit_grid(pts,4,6);item['modes'][name]=dict(accepted=len(fit['points']),rmse=fit['rmse'],pitch=fit['pitch'])
        except Exception as error:
            item['modes'][name]=dict(error=str(error))
        delta=pts[None,:,:]-pts[:,None,:];distance=np.linalg.norm(delta,axis=2);np.fill_diagonal(distance,np.inf)
        pitch=float(np.median(distance.min(axis=1)));pairs=delta[(distance>.75*pitch)&(distance<1.3*pitch)]
        theta=float(np.angle(np.mean(np.exp(4j*np.arctan2(pairs[:,1],pairs[:,0]))))/4)
        debug=[]
        for angle in (theta,theta+math.pi/2):
            rotated=pts@np.array([[math.cos(angle),-math.sin(angle)],[math.sin(angle),math.cos(angle)]])
            try:
                ci=clusters(rotated[:,0],6);ri=clusters(rotated[:,1],4);ids=ri*6+ci
                debug.append(dict(angle=math.degrees(angle),unique=int(sum(np.sum(ids==x)==1 for x in ids)),duplicates=[int(x) for x in set(ids) if np.sum(ids==x)>1]))
            except Exception as error:debug.append(dict(error=str(error)))
        item['modes'][name]['debug']=debug
    results.append(item)
(folder/'grid_failure_diagnosis.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))

