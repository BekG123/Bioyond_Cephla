"""Offline smooth robust fit comparison; no camera or hardware commands."""
exec((__import__('pathlib').Path(__file__).with_name('probe_rim_search.py')).read_text().split('for ident in')[0])
import numpy as np
def robust(x,c,inside,indices):
    rows=np.arange(len(x));A=np.column_stack([x,np.ones(len(x))]);coef=np.polyfit(x[inside],c[rows,indices][inside],1)
    for _ in range(40):
        error=np.nan_to_num(abs(c-A.dot(coef)[:,None]),nan=1e6);idx=np.argmin(error,axis=1)
        y=c[rows,idx];valid=np.isfinite(y);r=error[rows,idx]
        weights=1/(1+(r/.5)**2)**2;weights[~valid]=0
        new=np.linalg.lstsq(A[valid]*np.sqrt(weights[valid,None]),y[valid]*np.sqrt(weights[valid]),rcond=None)[0]
        if np.max(abs(A.dot(new-coef)))<1e-5:coef=new;break
        coef=new
    return coef
m=types.ModuleType('probe');exec(source,m.__dict__);m.robust=robust
code=source.replace('slope,intercept=np.polyfit(fractions[best],displacement[best],1)','slope,intercept=robust(fractions,candidate_offsets,best,best_indices)')
exec(code,m.__dict__)
for name in ['rim_consensus_1794447406716340500','rim_consensus_1794447736863324000','rim_consensus_1794447906966131400']:
    qs=[]
    for p in sorted((ROOT/'operator_ui/reports/plate_session/cellvis24_validation'/name).glob('median_*.png')):
        try:
            q,es=m.rim_edges(cv2.resize(cv2.imread(str(p)),(1200,800)),seed,[-1]*4,sample_span=(.25,.75),tangent_radius=2);qs.append(q)
        except Exception as e:print(name,p.name,str(e),flush=True)
    if len(qs)==3:
        q=np.array(qs);print(name,'spread',float(np.linalg.norm(q[:,None]-q[None,:],axis=3).max()),flush=True)
