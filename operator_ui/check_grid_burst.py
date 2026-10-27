"""Read-only stationary camera-burst diagnostic. Never sends controller commands."""
from check_multiview_rim import ROOT,cv2,json,DetectionError
from grid_pattern import commissioned_grid_tracker
from urllib.request import urlopen
import numpy as np
import time
r=json.loads((ROOT/'operator_ui/reports/plate_projection_taught_48/result.json').read_text())
t=commissioned_grid_tracker(ROOT,r,cv2.imread(r['images']['target']['path']))
def read(endpoint):
    with urlopen('http://127.0.0.1:5002'+endpoint,timeout=6) as response:
        if response.headers.get('X-Error'):raise RuntimeError(response.headers['X-Error'])
        return response.read()
origin=None
for burst in range(3):
    images=[]
    for n in range(5):
        for phase in ('before','after'):
            state=json.loads(read('/state'));robot=state['robot']
            if not robot.get('connected') or not robot.get('ok') or state['sequence']['active']:raise RuntimeError('Require stationary healthy arm')
            pose=robot['pose_mm'];origin=origin or pose
            if any(abs(pose[k]-origin[k])>.1 for k in ('X','Y','Z','Rz')):raise RuntimeError('Arm moved during burst')
            if phase=='before':images.append(cv2.imdecode(np.frombuffer(read('/frame'),np.uint8),cv2.IMREAD_COLOR))
        time.sleep(1.)
    try:
        a=t.track(np.median(images,axis=0).astype(np.uint8))
        print(json.dumps(dict(burst=burst+1,ok=True,wells=a['supported_wells'],disk_spread=a['disk_group_spread_px'],extent_spread=a['extent_group_spread_px'],correlations=a['pattern_correlations'])),flush=True)
    except DetectionError as e:print(json.dumps(dict(burst=burst+1,ok=False,error=str(e))),flush=True)
