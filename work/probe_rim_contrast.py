exec((__import__('pathlib').Path(__file__).with_name('probe_rim_search.py')).read_text().split('for ident in')[0])
import numpy as np
for ident in ['a04cc11d024b4461b295820402b30245','9b9c05b4a29b4a818b5cb44f763fc601']:
    image=cv2.resize(cv2.imread(str(ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'/ident/'prepared_median_0.png'),0),(1200,800))
    for mode in ['gain1.5','gain2','gamma1.2','gamma1.5','clahe1','clahe2','clahe4']:
        if mode.startswith('gain'):corrected=image.astype(np.float32)*float(mode[4:])
        elif mode.startswith('gamma'):corrected=255*(image.astype(np.float32)/255)**float(mode[5:])
        else:corrected=cv2.createCLAHE(clipLimit=float(mode[5:]),tileGridSize=(8,8)).apply(image)
        try:
            corners,edges=rim_edges.rim_edges(corrected,seed,[-1]*4)
            result=dict(corners=corners.tolist(),edges=[{k:e[k] for k in ['inliers','rms_px','slope_px','normal_offset_px']} for e in edges])
        except Exception as e:result=dict(error=str(e))
        print(json.dumps(dict(id=ident,mode=mode,**result)),flush=True)
