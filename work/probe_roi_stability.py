exec((__import__('pathlib').Path(__file__).with_name('probe_rim_search.py')).read_text().split('for ident in')[0])
import numpy as np
paths=list((ROOT/'operator_ui/reports/plate_session/cellvis24_validation/rim_consensus_1794447406716340500').glob('median_*.png'))
paths += [ROOT/'operator_ui/reports/plate_session/cellvis24_workflows/a04cc11d024b4461b295820402b30245/prepared_median_0.png']
for radius in [0,1,2]:
    m=types.ModuleType('probe')
    code=source.replace('values=cv2.remap(gray,samples[:,:,0].astype(np.float32),samples[:,:,1].astype(np.float32),cv2.INTER_LINEAR)',f'values=np.mean([cv2.remap(gray,(samples[:,:,0]+t*v[0]).astype(np.float32),(samples[:,:,1]+t*v[1]).astype(np.float32),cv2.INTER_LINEAR) for t in np.arange(-{radius},{radius}+1)],axis=0)')
    exec(code.replace('hi-lo<.6-1e-9','hi-lo<.5-1e-9'),m.__dict__);qs=[]
    for p in paths:
        image=cv2.resize(cv2.imread(str(p)),(1200,800))
        try:
            q,es=m.rim_edges(image,seed,[-1]*4,sample_span=(.25,.75));qs.append(q)
            print(json.dumps(dict(radius=radius,file=p.parent.name+'/'+p.name,inliers=[e['inliers'] for e in es])),flush=True)
        except Exception as e:print(radius,p.name,str(e),flush=True)
    if len(qs)==4:
        q=np.array(qs[:3]);print('spread',radius,float(np.linalg.norm(q[:,None]-q[None,:],axis=3).max()),flush=True)
