"""Offline fixed rim registration experiment, no motion."""
from diagnose_cellvis_grid_registration import *

def run():
    d=reference();obs=ROOT/d['files']['observation']['path'];saved=json.loads(obs.read_bytes())
    image=median5([decode_reference(obs.with_name(f'burst_2_{j}.jpg').read_bytes()) for j in range(5)])
    corners=np.array(saved['bursts'][2]['measurement']['corners_preview_px'])
    t=object.__new__(GridPatternTracker);t.refinement_motion=cv2.MOTION_AFFINE;t.full_resolution_refinement=True
    t.ref=t.gray(image);t.reference_signal=t.signal(t.ref)
    masks=[np.zeros(t.ref.shape,np.uint8) for _ in range(2)]
    for side in range(4):
        a,b=corners[side],corners[(side+1)%4]
        for i in range(8):
            start=a+(b-a)*(.1+i*.1);end=a+(b-a)*(.18+i*.1)
            cv2.line(masks[i%2],tuple(np.rint(start).astype(int)),tuple(np.rint(end).astype(int)),255,16)
    disks=json.loads((ROOT/d['files']['disks']['path']).read_bytes());cfg=next(c for c in teach._configs() if c['name']=='Wide')
    report=[]
    for name in ['d96640d3884f498195b07bb8d245b85b','d16d8e267e1a4503838e27d9cc02fe4f','c1d0b78a69674a9cae642d05b10200ff','633b3cebf767442ead7dbe91f6366786']:
        folder=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'/name
        for i in range(3):
            img=median5([prepare_raw(cv2.imread(str(folder/f'calibration_{i}_{j}.png'))) for j in range(5)])
            fits=[t.refine(t.gray(img),np.eye(3),m) for m in masks]
            qs=[transform(corners,h) for cc,h in fits];ts=[target(q,disks,cfg) for q in qs]
            r=dict(run=name,burst=i,correlations=[cc for cc,h in fits],targets=ts,
                shift_mm=[float(np.hypot(q['x']-d['raw_target']['x'],q['y']-d['raw_target']['y'])) for q in ts],
                corner_group_spread_px=float(np.linalg.norm(qs[0]-qs[1],axis=1).max()),transforms=[h.tolist() for cc,h in fits])
            report.append(r);print(json.dumps({k:v for k,v in r.items() if k!='transforms'}),flush=True)
    (ROOT/'operator_ui/reports/plate_session/cellvis24_validation/rim_registration_diagnosis.json').write_text(json.dumps(report,indent=2))

if __name__=='__main__':run()
