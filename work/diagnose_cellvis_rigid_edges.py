"""Offline constrained rim fit, fixed original reference; no hardware calls."""
from diagnose_cellvis_edge_profiles import profiles
from diagnose_cellvis_grid_registration import *

def fit_global(ref,cur,corners):
    rows=[];shifts=[];valids=[];sides=[]
    center=corners.mean(axis=0)
    for side,(a,b,x,y) in enumerate(zip(corners,np.roll(corners,-1,axis=0),ref,cur)):
        template=x[:,48:113];template-=template.mean(axis=1,keepdims=True)
        scores=[]
        for shift in range(-32,33):
            w=y[:,48+shift:113+shift].copy();w-=w.mean(axis=1,keepdims=True)
            scores.append(np.sum(template*w,axis=1)/(np.linalg.norm(template,axis=1)*np.linalg.norm(w,axis=1)+1e-9))
        scores=np.array(scores).T;best=scores.argmax(axis=1);offset=(best-32)*.25
        for i,k in enumerate(best):
            if 0<k<64:
                den=scores[i,k-1]-2*scores[i,k]+scores[i,k+1]
                if abs(den)>1e-9:offset[i]+=.125*(scores[i,k-1]-scores[i,k+1])/den
        good=(scores.max(axis=1)>.95)&(best>0)&(best<64)
        n=np.array([-(b-a)[1],(b-a)[0]])/np.linalg.norm(b-a)
        for f,o,g in zip(np.linspace(.12,.88,160),offset,good):
            p=a+f*(b-a)-center
            rows.append([*n,n@np.array([-p[1],p[0]])]);shifts.append(o);valids.append(g);sides.append(side)
    A=np.array(rows);d=np.array(shifts);good=np.array(valids);sides=np.array(sides);rng=np.random.default_rng(0);best=None
    for _ in range(500):
        ids=rng.choice(np.flatnonzero(good),3,replace=False)
        if np.linalg.matrix_rank(A[ids])<3:continue
        x=np.linalg.lstsq(A[ids],d[ids],rcond=None)[0];inside=good&(abs(A@x-d)<.5)
        if best is None or inside.sum()>best.sum():best=inside
    for _ in range(3):
        x=np.linalg.lstsq(A[best],d[best],rcond=None)[0];best=good&(abs(A@x-d)<.5)
    angle=x[2];rot=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    q=(corners-center)@rot.T+center+x[:2]
    return q,dict(parameters=[*x[:2],float(np.degrees(angle))],inliers=[int((best&(sides==i)).sum()) for i in range(4)],rmse=float(np.sqrt(np.mean((A[best]@x-d[best])**2))))

def main():
    d=reference();obs=ROOT/d['files']['observation']['path'];saved=json.loads(obs.read_bytes())
    image=median5([decode_reference(obs.with_name(f'burst_2_{j}.jpg').read_bytes()) for j in range(5)])
    corners=np.array(saved['bursts'][2]['measurement']['corners_preview_px']);ref=profiles(image,corners)
    disks=json.loads((ROOT/d['files']['disks']['path']).read_bytes());cfg=next(c for c in teach._configs() if c['name']=='Wide')
    report=[]
    for name in ['d96640d3884f498195b07bb8d245b85b','d16d8e267e1a4503838e27d9cc02fe4f','c1d0b78a69674a9cae642d05b10200ff','633b3cebf767442ead7dbe91f6366786','1a1dbefadbc0413e8ad242d4e287fc75','3f0bfe8b02b143309ed28b7883a822fe']:
        folder=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'/name
        for i in range(3):
            img=median5([prepare_raw(cv2.imread(str(folder/f'calibration_{i}_{j}.png'))) for j in range(5)])
            q,quality=fit_global([v.copy() for v in ref],profiles(img,corners),corners);t=target(q,disks,cfg)
            r=dict(run=name,burst=i,quality=quality,target=t,shift_mm=float(np.hypot(t['x']-d['raw_target']['x'],t['y']-d['raw_target']['y'])),yaw_delta=t['rz']-d['raw_target']['rz'])
            report.append(r);print(json.dumps(r),flush=True)
    (ROOT/'operator_ui/reports/plate_session/cellvis24_validation/rigid_edge_diagnosis.json').write_text(json.dumps(report,indent=2))

if __name__=='__main__':main()
