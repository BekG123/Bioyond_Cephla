exec((__import__('pathlib').Path(__file__).with_name('probe_rim_search.py')).read_text().split('for ident in')[0])
import numpy as np
image=cv2.resize(cv2.imread(str(ROOT/'operator_ui/reports/plate_session/cellvis24_workflows/a04cc11d024b4461b295820402b30245/prepared_median_0.png')),(1200,800))
saved={}
def trace(frame,event,arg):
    if frame.f_code.co_name=='rim_edges' and event=='exception':saved.update(frame.f_locals)
    return trace
sys.settrace(trace)
try:rim_edges.rim_edges(image,seed,[-1]*4)
except Exception:pass
finally:sys.settrace(None)
x=saved['fractions'];c=saved['candidate_offsets'];mask=saved['best'];idx=saved['best_indices']
print(json.dumps(dict(seed=seed,side=saved['side'],counts=np.histogram(x[mask],bins=np.linspace(.12,.88001,5))[0].tolist(),candidate_rows=np.isfinite(c).any(axis=1).sum().item())))
out=cv2.applyColorMap(cv2.resize(np.uint8(np.clip(128+saved['gradient']*12,0,255)),(565,800)),cv2.COLORMAP_TURBO)
plot=np.full((800,565,3),255,np.uint8)
for i,row in enumerate(c):
    for j,val in enumerate(row):
        if np.isfinite(val):cv2.circle(plot,(int((val+14)*20),i*5+2),2,(0,0,0) if mask[i] and idx[i]==j else (0,120,240),-1)
cv2.imwrite(str(ROOT/'work/latest_rim_profiles.png'),np.concatenate([out,plot],axis=1))
np.savez(ROOT/'work/latest_rim_profiles.npz',x=x,c=c,gradient=saved['gradient'],values=saved['values'])
