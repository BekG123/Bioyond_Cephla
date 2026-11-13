"""Offline comparison of archived images; no robot/camera calls."""
import json, math, hashlib
from pathlib import Path
import cv2
import numpy as np
from cellvis24_calibration import reference,ROOT,OBSERVATION
from cellvis24_observation import measure,teach,summarize
from projected_alignment import target_from_mark

folder=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows/633b3cebf767442ead7dbe91f6366786'
d=reference();base=d['raw_target'];seed=json.loads((ROOT/d['files']['seed']['path']).read_bytes())['fitted']
disks=json.loads((ROOT/d['files']['disks']['path']).read_bytes())
cfg=next(c for c in teach._configs() if c['name']=='Wide')
source=json.loads((ROOT/d['files']['observation']['path']).read_bytes())
bm=source['bursts'][-1]['measurement']

def brief(m):
    t=m['target'];delta=np.array([t['x']-base['x'],t['y']-base['y']])
    return dict(target=t,shift_mm=float(np.linalg.norm(delta)),delta_xy_mm=delta.tolist(),
        yaw_delta_deg=(t['rz']-base['rz']+180)%360-180,
        mark_delta=np.array(m['mark']).__sub__(bm['mark']).tolist(),
        center_delta_mm=(np.array(m['error_xy_mm'])-bm['error_xy_mm']).tolist(),
        wells=m['measured_wells'],grid_rmse_px=m['grid_rmse_px'],
        rim_delta_preview_px=(np.array(m['corners_preview_px'])-bm['corners_preview_px']).tolist(),
        edges=[{k:e[k] for k in ('side','inliers','rms_px','normal_offset_px','slope_px','median_strength')} for e in m['edges']])

result=dict(motion_sent=False,source=str(folder/'run.json'),baseline_target=base,
    baseline_pose=source.get('before',{}).get('robot',{}).get('pose_mm'),runs={},reprocessed=[])
for name in ['d96640d3884f498195b07bb8d245b85b','d16d8e267e1a4503838e27d9cc02fe4f','c1d0b78a69674a9cae642d05b10200ff','633b3cebf767442ead7dbe91f6366786']:
    p=folder.parent/name/'run.json';r=json.loads(p.read_bytes())
    vision=next(x for x in r['steps'] if x['kind']=='vision')
    ms=[b['measurement'] for b in vision.get('measurement',{}).get('bursts',[])]
    result['runs'][name]=dict(status=r['status'],error=r.get('error'),bursts=[brief(m) for m in ms])
    if len(ms)==3:
        xy=np.array([[m['target']['x'],m['target']['y']] for m in ms])
        result['runs'][name]['target_spread_mm']=float(np.linalg.norm(xy[:,None]-xy[None,:],axis=2).max())
        result['runs'][name]['summary']=summarize(ms)
        result['runs'][name]['median_target_shift_mm']=float(np.linalg.norm(np.median(xy,axis=0)-[base['x'],base['y']]))
for i in range(3):
    frames=[cv2.imread(str(folder/f'calibration_{i}_{j}.png')) for j in range(5)]
    compressed=[cv2.imdecode(cv2.imencode('.jpg',f,[cv2.IMWRITE_JPEG_QUALITY,82])[1],cv2.IMREAD_COLOR) for f in frames]
    entry=dict(burst=i)
    for label,images in [('raw',frames),('jpeg82',compressed)]:
        try:entry[label]=brief(measure(np.median(images,axis=0).astype(np.uint8),seed,disks,OBSERVATION,cfg))
        except Exception as e:entry[label]=dict(error=str(e))
    result['reprocessed'].append(entry)
    print(json.dumps({'burst':i,**{k:{x:v.get(x) for x in ('shift_mm','yaw_delta_deg','wells','error')} for k,v in entry.items() if k!='burst'}}),flush=True)
# Decompose the center shift and yaw contribution to transformed tool position.
current=json.loads((folder/'run.json').read_bytes())['steps'][-1]['measurement']['bursts']
result['transform_sensitivity']=[]
for b in current:
    mark=b['measurement']['mark'];m0=bm['mark'];v={}
    for label,m in [('center_only',[mark[0],mark[1],m0[2]]),('angle_only',[m0[0],m0[1],mark[2]])]:
        t=target_from_mark(OBSERVATION,{'mark':m},cfg)
        v[label]=[t['x']-base['x'],t['y']-base['y']]
    result['transform_sensitivity'].append(v)
out=folder/'offline_measurement_diagnosis.json';out.write_text(json.dumps(result,indent=2,allow_nan=False))
print(json.dumps({'report':str(out),'runs':{k:{'shifts':[round(b['shift_mm'],4) for b in v['bursts']],'target_spread':v.get('target_spread_mm'),'median_shift':v.get('median_target_shift_mm')} for k,v in result['runs'].items()},'sensitivity':result['transform_sensitivity']}),flush=True)
