"""Compare camera projections only. GET requests; no motion or calibration writes."""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import ProxyHandler, build_opener
import cv2
import numpy as np

ROOT = Path(__file__).parent / 'camera_height_comparison'
ROOT.mkdir(exist_ok=True)
BASE = 'http://192.168.100.101/NimbusLite/api/v1/'
opener = build_opener(ProxyHandler({}))

def get(path):
    with opener.open(BASE+path, timeout=15) as response:
        return response.read()

def groups(values):
    return np.array([np.mean(g) for g in np.split(values,np.where(np.diff(values)>1)[0]+1) if len(g)])

def regular_lines(values, count):
    assert len(values)>=count, values
    options=[values[i:i+count] for i in range(len(values)-count+1)]
    chosen=min(options,key=lambda a:np.std(np.diff(a)))
    assert np.std(np.diff(chosen))<1, chosen
    return chosen

assert json.loads(get('instruments/global-run-state')) == 'Idle'
assert json.loads(get('service-software-api/is-parked')) is True
results = []
for height in (60, 63, 66, 69, 72, 75):
    for name, endpoint in (
        ('plain', f'camera/position/3/0/{height}'),
        ('overlay', f'camera/position/tip-rack/3/{height}/255'),
    ):
        path = ROOT/f'{name}_{height}.png'
        if not path.exists():
            path.write_bytes(get(endpoint))
    plain = cv2.imread(str(ROOT/f'plain_{height}.png'),0)
    overlay = cv2.imread(str(ROOT/f'overlay_{height}.png'),0)
    h,w = plain.shape
    assert overlay.shape == plain.shape
    xl = groups(np.flatnonzero(np.mean(overlay[int(.085*h):int(.915*h)]>=230,axis=0)>.90))
    yl = groups(np.flatnonzero(np.mean(overlay[:,int(.082*w):int(.918*w)]>=230,axis=1)>.90))
    xl=xl[(xl>.065*w)&(xl<.94*w)]
    yl=yl[(yl>.06*h)&(yl<.94*h)]
    xl,yl=regular_lines(xl,13),regular_lines(yl,9)
    assert len(xl)==13 and len(yl)==9,(height,xl,yl)
    xs,ys=(xl[1:]+xl[:-1])/2,(yl[1:]+yl[:-1])/2
    circles=cv2.HoughCircles(cv2.GaussianBlur(plain,(5,5),1),cv2.HOUGH_GRADIENT,
        1,38,param1=80,param2=24,minRadius=19,maxRadius=27)[0]
    points=[]
    for x,y,radius in circles:
        c,r=int(np.argmin(abs(xs-x))),int(np.argmin(abs(ys-y)))
        if np.hypot(xs[c]-x,ys[r]-y)<26:
            points.append((c,r,float(x),float(y)))
    points=np.array(points)
    design=np.c_[points[:,:2],np.ones(len(points))]
    keep=np.ones(len(points),dtype=bool)
    for _ in range(5):
        fit=np.linalg.lstsq(design[keep],points[keep,2:],rcond=None)[0]
        residuals=np.linalg.norm(design@fit-points[:,2:],axis=1)
        keep=residuals<3
    pitch=np.array([np.mean(np.diff(xs)),np.mean(np.diff(ys))])
    center=np.array([5.5,3.5,1])@fit
    expected=np.array([np.mean(xs),np.mean(ys)])
    row={'api_camera_height_mm':height,'candidate_rims':len(circles),'inlier_rims':int(keep.sum()),
        'pitch_mismatch_percent':((np.array([fit[0,0],fit[1,1]])/pitch-1)*100).tolist(),
        'center_displacement_pixels':(center-expected).tolist(),
        'center_displacement_in_nominal_9mm_grid_units_mm':((center-expected)/pitch*9).tolist(),
        'column_angle_image_degrees':float(np.degrees(np.arctan2(fit[0,1],fit[0,0]))),
        'fit_rms_pixels':float(np.sqrt(np.mean(residuals[keep]**2)))}
    results.append(row)
    print(json.dumps(row),flush=True)
    (ROOT/'results.json').write_text(json.dumps({'time':datetime.now(timezone.utc).isoformat(),
        'read_only':True,'assumptions':'Stable rack; nominal 9 mm grid; circular outer-rim approximations. Heights are camera projection arguments, not measured pickup Z. Image axes are not verified robot axes.',
        'results':results},indent=2),encoding='utf-8')
