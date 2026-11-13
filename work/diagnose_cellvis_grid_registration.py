"""Offline well-ring versus rim comparison; no hardware access."""
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'operator_ui'))
import cv2,numpy as np
from cellvis24_calibration import reference,OBSERVATION
from cellvis24_image_pipeline import median5,prepare_raw,decode_reference
from cellvis24_observation import measure,teach,transform,target_from_mark
from grid_preview import detect
from grid_pattern import GridPatternTracker

def target(corners,disks,cfg):
    h=cv2.getPerspectiveTransform(np.array([[0,0],[1,0],[1,1],[0,1]],np.float32),np.float32(corners)*2.56)
    centers=[]
    for c in disks['virtual_circles']:
        a=transform(c['normalized_plate_outline'],h)
        fit=np.linalg.lstsq(np.column_stack([2*a,np.ones(len(a))]),np.sum(a*a,axis=1),rcond=None)[0]
        centers.append(fit[:2])
    big,small=centers
    mark=[*((big+small)/2),float(np.degrees(np.arctan2(*(small-big)[::-1]))%360)]
    return target_from_mark(OBSERVATION,{'mark':mark},cfg)

def main():
    d=reference();obs=ROOT/d['files']['observation']['path'];saved=json.loads(obs.read_bytes())
    image=median5([decode_reference(obs.with_name(f'burst_2_{j}.jpg').read_bytes()) for j in range(5)])
    grid=detect(image,4,6);centers=transform(np.array([[c,r] for r in range(4) for c in range(6)],float),grid['h'])/2.56
    tracker=object.__new__(GridPatternTracker)
    tracker.refinement_motion=cv2.MOTION_AFFINE;tracker.full_resolution_refinement=True
    tracker.ref=tracker.gray(image);tracker.reference_signal=tracker.signal(tracker.ref)
    masks=[np.zeros(tracker.ref.shape,np.uint8) for _ in range(2)]
    for i,p in enumerate(centers):
        cv2.circle(masks[(i//6+i%6)%2],tuple(np.rint(p).astype(int)),round(.43*grid['pitch']/2.56),255,round(.15*grid['pitch']/2.56))
    corners=np.array(saved['bursts'][2]['measurement']['corners_preview_px'])
    disks=json.loads((ROOT/d['files']['disks']['path']).read_bytes());cfg=next(c for c in teach._configs() if c['name']=='Wide')
    report=[]
    for name in ['d96640d3884f498195b07bb8d245b85b','d16d8e267e1a4503838e27d9cc02fe4f','c1d0b78a69674a9cae642d05b10200ff','633b3cebf767442ead7dbe91f6366786']:
        folder=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'/name
        for i in range(3):
            img=median5([prepare_raw(cv2.imread(str(folder/f'calibration_{i}_{j}.png'))) for j in range(5)])
            gray=tracker.gray(img);fits=[tracker.refine(gray,np.eye(3),m) for m in masks]
            qs=[transform(corners,h) for cc,h in fits];ts=[target(q,disks,cfg) for q in qs]
            result=dict(run=name,burst=i,correlations=[cc for cc,h in fits],targets=ts,
                shift_mm=[float(np.hypot(t['x']-d['raw_target']['x'],t['y']-d['raw_target']['y'])) for t in ts],
                corner_group_spread_px=float(np.linalg.norm(qs[0]-qs[1],axis=1).max()),
                transforms=[h.tolist() for cc,h in fits])
            report.append(result);print(json.dumps({k:v for k,v in result.items() if k!='transforms'}),flush=True)
    out=ROOT/'operator_ui/reports/plate_session/cellvis24_validation/grid_registration_diagnosis.json'
    out.write_text(json.dumps(report,indent=2))

if __name__=='__main__':main()
