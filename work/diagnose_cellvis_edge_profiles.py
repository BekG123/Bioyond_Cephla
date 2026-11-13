"""Fixed edge-profile displacement experiment; no hardware access."""
from diagnose_cellvis_grid_registration import *

def profiles(image,corners):
    g=cv2.cvtColor(cv2.resize(image,(1200,800),interpolation=cv2.INTER_AREA),cv2.COLOR_BGR2GRAY).astype(np.float32)
    g=cv2.GaussianBlur(g,(5,5),1)
    offsets=np.arange(-20,20.01,.25);result=[]
    for a,b in zip(corners,np.roll(corners,-1,axis=0)):
        v=(b-a)/np.linalg.norm(b-a);n=np.array([-v[1],v[0]])
        bases=a+np.linspace(.12,.88,160)[:,None]*(b-a)
        p=bases[:,None]+offsets[None,:,None]*n
        samples=cv2.remap(g,p[:,:,0].astype(np.float32),p[:,:,1].astype(np.float32),cv2.INTER_LINEAR)
        result.append(np.gradient(samples,.25,axis=1))
    return result

def fit(ref,cur,corners):
    lines=[];quality=[]
    for side,(a,b,x,y) in enumerate(zip(corners,np.roll(corners,-1,axis=0),ref,cur)):
        template=x[:,48:113];template=template-template.mean(axis=1,keepdims=True)
        scores=[]
        for shift in range(-32,33):
            window=y[:,48+shift:113+shift];window=window-window.mean(axis=1,keepdims=True)
            scores.append(np.sum(template*window,axis=1)/(np.linalg.norm(template,axis=1)*np.linalg.norm(window,axis=1)+1e-9))
        scores=np.array(scores).T;best=scores.argmax(axis=1);offset=(best-32)*.25
        for i,k in enumerate(best):
            if 0<k<64:offset[i]+=.25*.5*(scores[i,k-1]-scores[i,k+1])/(scores[i,k-1]-2*scores[i,k]+scores[i,k+1])
        good=(scores.max(axis=1)>.95)&(best>0)&(best<64)
        f=np.linspace(.12,.88,160);rng=np.random.default_rng(0);model=None
        for _ in range(300):
            if good.sum()<2:raise ValueError('No correlated edge profiles')
            ids=rng.choice(np.flatnonzero(good),2,replace=False)
            if abs(f[ids[0]]-f[ids[1]])<.2:continue
            slope,intercept=np.polyfit(f[ids],offset[ids],1)
            inside=good&(abs(offset-(slope*f+intercept))<.4)
            if model is None or inside.sum()>model.sum():model=inside
        if model is None or model.sum()<104:raise ValueError(f'Only {0 if model is None else model.sum()} correlated edge profiles side {side}')
        slope,intercept=np.polyfit(f[model],offset[model],1)
        v=(b-a)/np.linalg.norm(b-a);n=np.array([-v[1],v[0]])
        line=np.cross([*(a+intercept*n),1],[*(b+(intercept+slope)*n),1]);lines.append(line)
        quality.append(dict(side=side,inliers=int(model.sum()),offset=float(intercept),slope=float(slope),rmse=float(np.std(offset[model]-slope*f[model]-intercept))))
    qs=[]
    for i in range(4):
        p=np.cross(lines[i-1],lines[i]);qs.append(p[:2]/p[2])
    return np.array(qs),quality

def main():
    d=reference();obs=ROOT/d['files']['observation']['path'];saved=json.loads(obs.read_bytes())
    image=median5([decode_reference(obs.with_name(f'burst_2_{j}.jpg').read_bytes()) for j in range(5)])
    corners=np.array(saved['bursts'][2]['measurement']['corners_preview_px']);ref=profiles(image,corners)
    disks=json.loads((ROOT/d['files']['disks']['path']).read_bytes());cfg=next(c for c in teach._configs() if c['name']=='Wide')
    report=[]
    for name in ['d96640d3884f498195b07bb8d245b85b','d16d8e267e1a4503838e27d9cc02fe4f','c1d0b78a69674a9cae642d05b10200ff','633b3cebf767442ead7dbe91f6366786']:
        folder=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'/name
        for i in range(3):
            img=median5([prepare_raw(cv2.imread(str(folder/f'calibration_{i}_{j}.png'))) for j in range(5)])
            r=dict(run=name,burst=i)
            try:
                qs,q=fit(ref,profiles(img,corners),corners);t=target(qs,disks,cfg)
                r.update(target=t,quality=q,shift_mm=float(np.hypot(t['x']-d['raw_target']['x'],t['y']-d['raw_target']['y'])))
            except Exception as e:r['error']=str(e)
            report.append(r);print(json.dumps(r),flush=True)
    (ROOT/'operator_ui/reports/plate_session/cellvis24_validation/edge_profile_diagnosis.json').write_text(json.dumps(report,indent=2))

if __name__=='__main__':main()
