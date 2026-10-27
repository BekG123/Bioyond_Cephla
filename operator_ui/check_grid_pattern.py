"""Offline, fixed-reference whole-grid registration experiment. Never moves hardware."""
from check_multiview_rim import ROOT, cv2, json, commissioned_tracker, DetectionError
from grid_preview import fit_grid
from project_taught_disks import transform
import numpy as np


def gray(image):
    a = cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), (1200,800), interpolation=cv2.INTER_AREA)
    return a


def signal(a):
    a = a.astype(np.float32)/255
    return cv2.GaussianBlur(a, (5,5), 1) - cv2.GaussianBlur(a, (0,0), 12)


def refine(ref, image, seed, mask):
    aligned = cv2.warpPerspective(image, np.linalg.inv(seed), (1200,800))
    small = np.diag([.5,.5,1.])
    cc, h = cv2.findTransformECC(cv2.resize(signal(ref), (600,400)),
        cv2.resize(signal(aligned), (600,400)), np.eye(3,dtype=np.float32),
        cv2.MOTION_HOMOGRAPHY, (cv2.TERM_CRITERIA_COUNT|cv2.TERM_CRITERIA_EPS,80,1e-6),
        cv2.resize(mask,(600,400),interpolation=cv2.INTER_NEAREST), 5)
    return cc, seed @ np.linalg.inv(small) @ h @ small


if __name__ == '__main__':
    report = json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
    ref_image = cv2.imread(report['images']['target']['path'])
    ref = gray(ref_image)
    enhanced = cv2.GaussianBlur(cv2.createCLAHE(2,(8,8)).apply(ref),(5,5),1.2)
    circles = cv2.HoughCircles(enhanced,cv2.HOUGH_GRADIENT,1.2,75,param1=80,param2=26,minRadius=32,maxRadius=46)
    f = fit_grid(circles[0,:,:2])
    grid = np.array([[c,r] for r in range(6) for c in range(8)],float)
    masks = [np.zeros(ref.shape,np.uint8) for _ in range(2)]
    for g,p in zip(grid,transform(grid,f['h'])):
        cv2.circle(masks[int(sum(g))%2], tuple(np.rint(p).astype(int)), 40, 255, 14)
    tracker = commissioned_tracker(ROOT,report,ref_image)
    points = np.vstack([c['pixels'] for c in report['virtual_circles']])*1200/ref_image.shape[1]
    folders = ROOT/'operator_ui/reports/projected_disk_pilot'
    prior = {}
    for folder in ('wider_view_validation_20261026','wider_view_followup_20261026'):
        for path in sorted((folders/folder).glob('fresh_*.jpg')):
            image = cv2.imread(str(path)); seeds=[]
            for name,t,h0,rms in tracker.views:
                try:
                    r=t.track(image)
                    seeds.append((r['registration_rmse_px']+(rms or 0),name,np.array(r['H_preview_from_reference_preview'])@h0))
                except DetectionError: pass
            if not seeds:
                print(json.dumps(dict(image=str(path.relative_to(ROOT)),ok=False,error='No checked seed')),flush=True)
                continue
            _,name,seed=min(seeds,key=lambda x:x[0])
            try:
                fits=[refine(ref,gray(image),seed,m) for m in masks]
                cc,h=fits[0]
                projected=transform(points,h)
                baseline=prior.setdefault(folder,projected)
                print(json.dumps(dict(image=str(path.relative_to(ROOT)),ok=True,seed=name,correlation=cc,
                    seed_change_px=float(np.linalg.norm(projected-transform(points,seed),axis=1).max()),
                    checkerboard_disk_spread_px=float(np.linalg.norm(projected-transform(points,fits[1][1]),axis=1).max()),
                    correlations=[x[0] for x in fits],
                    stationary_disk_shift_px=float(np.linalg.norm(projected-baseline,axis=1).max()),H=h.tolist())),flush=True)
            except cv2.error as e:
                print(json.dumps(dict(image=str(path.relative_to(ROOT)),ok=False,error=str(e))),flush=True)
