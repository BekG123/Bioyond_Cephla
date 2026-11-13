"""Compare stationary plate images before/after reseating; no hardware calls."""
from diagnose_cellvis_grid_registration import *

base=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'
before='1a1dbefadbc0413e8ad242d4e287fc75';after='3f0bfe8b02b143309ed28b7883a822fe'
records=[json.loads((base/n/'run.json').read_bytes()) for n in (before,after)]
visions=[next(s for s in r['steps'] if s['kind']=='vision')['measurement'] for r in records]
ref=cv2.imread(str(base/before/'prepared_median_2.png'))
grid=detect(ref,4,6);indices=np.array([[c,r] for r in range(4) for c in range(6)],float)
centers=transform(indices,grid['h'])/2.56
t=object.__new__(GridPatternTracker);t.refinement_motion=cv2.MOTION_AFFINE;t.full_resolution_refinement=True
t.ref=t.gray(ref);t.reference_signal=t.signal(t.ref)
masks=[np.zeros(t.ref.shape,np.uint8) for _ in range(2)]
for g,p in zip(indices,centers):
    cv2.circle(masks[int(sum(g))%2],tuple(np.rint(p).astype(int)),round(.43*grid['pitch']/2.56),255,round(.15*grid['pitch']/2.56))
corners=np.array(visions[0]['bursts'][2]['measurement']['corners_preview_px'])
report=dict(before=before,after=after,motion_sent=False,diagnostic_only=True,comparisons=[])
for i in range(3):
    img=cv2.imread(str(base/after/f'prepared_median_{i}.png'))
    fits=[t.refine(t.gray(img),np.eye(3),m) for m in masks]
    qs=[transform(corners,h) for cc,h in fits]
    yaw=[float(np.degrees(np.arctan2(*(q[1]-q[0])[::-1])-np.arctan2(*(corners[1]-corners[0])[::-1]))) for q in qs]
    r=dict(burst=i,correlations=[cc for cc,h in fits],relative_image_yaw_deg=yaw,
        center_delta_preview_px=[(q.mean(axis=0)-corners.mean(axis=0)).tolist() for q in qs],
        corner_group_spread_px=float(np.linalg.norm(qs[0]-qs[1],axis=1).max()),
        transforms=[h.tolist() for cc,h in fits])
    report['comparisons'].append(r);print(json.dumps({k:v for k,v in r.items() if k!='transforms'}),flush=True)
report['camera_assessments']=[v['assessment'] for v in visions]
report['note']='Independent well subsets provide an image-change cross-check, not new motion acceptance or ground-truth pose.'
(base/after/'repeat_comparison.json').write_text(json.dumps(report,indent=2,allow_nan=False))
