"""Offline strip averaging of measured profiles to reduce dark-rim noise."""
exec((__import__('pathlib').Path(__file__).with_name('probe_rim_search.py')).read_text().split('for ident in')[0])
import numpy as np
for ident in ['a04cc11d024b4461b295820402b30245','9b9c05b4a29b4a818b5cb44f763fc601','7c29ef6a68724ffeb9a4365456a98e33']:
    image=cv2.resize(cv2.imread(str(ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'/ident/'prepared_median_0.png')),(1200,800))
    for radius in [2,4,6,8]:
        m=types.ModuleType('probe')
        code=source.replace('values=cv2.remap(gray,samples[:,:,0].astype(np.float32),samples[:,:,1].astype(np.float32),cv2.INTER_LINEAR)',f'values=np.mean([cv2.remap(gray,(samples[:,:,0]+t*v[0]).astype(np.float32),(samples[:,:,1]+t*v[1]).astype(np.float32),cv2.INTER_LINEAR) for t in np.arange(-{radius},{radius}+1)],axis=0)')
        exec(code,m.__dict__)
        try:
            corners,edges=m.rim_edges(image,seed,[-1]*4)
            result=dict(corners=corners.tolist(),edges=[{k:e[k] for k in ['inliers','rms_px','slope_px','normal_offset_px']} for e in edges])
        except Exception as e:result=dict(error=str(e))
        print(json.dumps(dict(id=ident,radius=radius,**result)),flush=True)
