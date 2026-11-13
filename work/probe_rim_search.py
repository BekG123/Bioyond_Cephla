"""Offline hypothesis-search comparison; no robot calls."""
import sys,json,time,types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'operator_ui'))
sys.path.insert(0,str(ROOT/'Pick and Hold/Align/plate_pose'))
from cellvis24_calibration import reference
import rim_edges,cv2
d=reference();seed=json.loads((ROOT/d['files']['seed']['path']).read_bytes())['fitted']
source=Path(rim_edges.__file__).read_text()
for ident in ['a04cc11d024b4461b295820402b30245','9b9c05b4a29b4a818b5cb44f763fc601','7c29ef6a68724ffeb9a4365456a98e33']:
    image=cv2.resize(cv2.imread(str(ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'/ident/'prepared_median_0.png')),(1200,800))
    for iterations in [1000,5000,20000]:
        m=types.ModuleType('probe');exec(source.replace('range(1000)',f'range({iterations})'),m.__dict__)
        start=time.monotonic()
        try:
            corners,edges=m.rim_edges(image,seed,[-1]*4)
            result=dict(corners=corners.tolist(),edges=[{k:e[k] for k in ['inliers','initial_inliers','rms_px','slope_px','normal_offset_px']} for e in edges])
        except Exception as e:result=dict(error=str(e))
        print(json.dumps(dict(id=ident,iterations=iterations,seconds=time.monotonic()-start,**result)),flush=True)
