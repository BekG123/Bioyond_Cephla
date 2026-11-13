"""Compare rim sampling against known image warps; no hardware calls."""
from diagnose_cellvis_grid_registration import *
from rim_edges import rim_edges

d=reference();obs=ROOT/d['files']['observation']['path'];seed=json.loads((ROOT/d['files']['seed']['path']).read_bytes())['fitted']
ref=median5([decode_reference(obs.with_name(f'burst_2_{j}.jpg').read_bytes()) for j in range(5)])
disks=json.loads((ROOT/d['files']['disks']['path']).read_bytes());cfg=next(c for c in teach._configs() if c['name']=='Wide')
all_results={}
for method,interpolation in [('linear',cv2.INTER_LINEAR),('area',cv2.INTER_AREA)]:
    def fit(img):return rim_edges(cv2.resize(img,(1200,800),interpolation=interpolation),seed,polarities=[-1]*4,half_width=14)[0]
    base=fit(ref);base_t=target(base,disks,cfg);results=[]
    for dx,dy,theta in [(0,0,0),(.5,0,0),(1,0,0),(0,1,0),(3,-4,0),(0,0,.1),(0,0,-.1),(1,-3,.2),(-2,2,-.3)]:
        h=cv2.getRotationMatrix2D(tuple(base.mean(axis=0)*2.56),theta,1);h[:,2]+=[dx*2.56,dy*2.56]
        img=cv2.warpAffine(ref,h,(3072,2048),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT)
        expected=target(cv2.transform((base*2.56)[None],h)[0]/2.56,disks,cfg)
        try:
            actual=target(fit(img),disks,cfg)
            results.append(dict(dx=dx,dy=dy,theta=theta,xy_error=float(np.hypot(actual['x']-expected['x'],actual['y']-expected['y'])),yaw_error=actual['rz']-expected['rz']))
        except Exception as e:results.append(dict(dx=dx,dy=dy,theta=theta,error=str(e)))
    runs=[]
    for name in ['1a1dbefadbc0413e8ad242d4e287fc75','3f0bfe8b02b143309ed28b7883a822fe']:
        for i in range(3):
            img=cv2.imread(str(ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'/name/f'prepared_median_{i}.png'))
            t=target(fit(img),disks,cfg)
            runs.append(dict(run=name,burst=i,shift_mm=float(np.hypot(t['x']-base_t['x'],t['y']-base_t['y'])),yaw_delta=t['rz']-base_t['rz']))
    all_results[method]=dict(synthetic=results,runs=runs)
    print(json.dumps(dict(method=method,results=results,runs=runs)),flush=True)
(ROOT/'operator_ui/reports/plate_session/cellvis24_validation/sampling_diagnosis.json').write_text(json.dumps(all_results,indent=2))
