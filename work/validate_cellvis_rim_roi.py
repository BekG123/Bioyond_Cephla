"""Compare fixed Cellvis straight-rim ROI against archived and fresh images."""
import sys,json,time,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'operator_ui'))
import cv2,numpy as np
from dataclasses import replace
from cellvis24_calibration import OBSERVATION,projected_profile
from cellvis24_observation import measure,summarize,teach
from projected_plate_calibration import solve
d=json.loads((ROOT/'Pick and Hold/Calibration/plate_profiles/cellvis24_camera_reference_v3.json').read_bytes())
seed=json.loads((ROOT/d['files']['seed']['path']).read_bytes())['fitted'];disks=json.loads((ROOT/d['files']['disks']['path']).read_bytes())
cfg=next(c for c in teach._configs() if c['name']=='Wide')
folder=ROOT/'operator_ui/reports/plate_session/cellvis24_validation'/('rim_roi_'+str(time.time_ns()));folder.mkdir()
report=dict(motion_sent=False,groups=[])
paths=[ROOT/'operator_ui/reports/plate_session/cellvis24_validation/rim_consensus_1794447406716340500']
paths += [ROOT/'operator_ui/reports/plate_session/cellvis24_validation/rim_consensus_1794447736863324000']
root=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'
paths += sorted([p for p in root.iterdir() if (p/'prepared_median_0.png').exists()],key=lambda p:p.stat().st_mtime,reverse=True)[:15]
for p in paths:
    group=dict(path=str(p),images=[]);report['groups'].append(group);ms=[]
    for image_path in sorted(p.glob('prepared_median_*.png')) or sorted(p.glob('median_*.png')):
        image=cv2.imread(str(image_path));row=dict(path=str(image_path),sha256=hashlib.sha256(image_path.read_bytes()).hexdigest());group['images'].append(row)
        try:row['legacy_target']=measure(image,seed,disks,OBSERVATION,cfg)['target']
        except Exception as e:row['legacy_error']=str(e)
        try:
            m=measure(image,seed,disks,OBSERVATION,cfg,rim_sample_span=d['rim_sample_span'],rim_tangent_radius=d['rim_tangent_radius']);row['measurement']=m;ms.append(m)
        except Exception as e:row['error']=str(e)
    if len(ms)==3:
        group['stability']=summarize(ms)
        profile=replace(projected_profile(),reference_target=tuple(d['raw_target'][k] for k in ('x','y','rz')))
        try:group['solution']=solve(ms,profile)
        except Exception as e:group['solution_error']=str(e)
    print(json.dumps(dict(path=p.name,passed=len(ms),total=len(group['images']),stability=group.get('stability'),solution_error=group.get('solution_error'),errors=[m.get('error') for m in group['images'] if m.get('error')])),flush=True)
(folder/'run.json').write_text(json.dumps(report,indent=2));print(folder,flush=True)
