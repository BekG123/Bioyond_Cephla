"""Offline locally optimized, spatially constrained hypothesis search."""
exec((__import__('pathlib').Path(__file__).with_name('probe_rim_search.py')).read_text().split('for ident in')[0])
import numpy as np
def search(x,c,inside,indices):
    rng=np.random.default_rng(0);rows=np.arange(len(x));ids=np.flatnonzero(np.isfinite(c).any(axis=1));pool={}
    if len(ids)<50:return inside,indices
    for _ in range(5000):
        i,j=rng.choice(ids,2,replace=False)
        if abs(x[i]-x[j])<.2:continue
        di=rng.choice(c[i,np.isfinite(c[i])]);dj=rng.choice(c[j,np.isfinite(c[j])])
        slope=(dj-di)/(x[j]-x[i]);intercept=di-slope*x[i]
        if abs(slope)>6:continue
        residual=np.nan_to_num(abs(c-(slope*x[:,None]+intercept)),nan=1e6)
        idx=np.argmin(residual,axis=1);err=residual[rows,idx];mask=err<1
        if min(np.histogram(x[mask],bins=np.linspace(.12,.88001,5))[0])<15:continue
        key=(mask.tobytes(),idx[mask].tobytes())
        pool[key]=((int(mask.sum()),-float(err[mask].mean())),mask,idx)
    best=None
    for _,mask,idx in sorted(pool.values(),key=lambda v:v[0],reverse=True)[:128]:
        mask,idx=rim_edges.refine_consensus(x,c,mask,idx)
        if mask.sum()<104 or min(np.histogram(x[mask],bins=np.linspace(.12,.88001,5))[0])<15:continue
        slope,intercept=np.polyfit(x[mask],c[rows,idx][mask],1)
        rms=float(np.sqrt(np.mean((c[rows,idx][mask]-(slope*x[mask]+intercept))**2)))
        if rms>.6 or abs(slope)>6:continue
        score=(int(mask.sum()),-rms)
        if best is None or score>best[0]:best=(score,mask,idx,slope,intercept)
    print('search',len(pool),None if best is None else [best[0],best[3],best[4]],flush=True)
    return (inside,indices) if best is None else best[1:3]
for ident in ['a04cc11d024b4461b295820402b30245','9b9c05b4a29b4a818b5cb44f763fc601']:
    image=cv2.resize(cv2.imread(str(ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'/ident/'prepared_median_0.png')),(1200,800))
    m=types.ModuleType('probe');exec(source,m.__dict__);m.refine_consensus=search
    try:
        corners,edges=m.rim_edges(image,seed,[-1]*4)
        print(json.dumps(dict(id=ident,corners=corners.tolist(),edges=[{k:e[k] for k in ['inliers','rms_px','slope_px','normal_offset_px']} for e in edges])),flush=True)
    except Exception as e:print(ident,str(e),flush=True)
