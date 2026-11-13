"""Stationary image validation through the existing owner; no motion calls."""
import sys,time,json,hashlib
from pathlib import Path
from urllib.request import urlopen
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'operator_ui'),str(ROOT/'bioyond-s4-mcp')]
import cv2
from run_cellvis24_workflow import api
from cellvis24_calibration import reference,OBSERVATION,projected_solution
from cellvis24_observation import measure,summarize,teach
from cellvis24_image_pipeline import decode_reference,median5
from draggo import DragGoRPC

folder=ROOT/'operator_ui/reports/plate_session/cellvis24_validation'/('rim_consensus_'+str(time.time_ns()))
folder.mkdir()
record=dict(motion_sent=False,bursts=[])
def save():(folder/'run.json').write_text(json.dumps(record,indent=2))
def check():
    s=api('state');n=DragGoRPC('192.168.201.220').info()
    if s['sequence']['active'] or any(n.get(k,True) for k in ('moving','drag','error','emergency')):
        raise RuntimeError('Stationary, fault-free observation required.')
    p=s['robot'].get('pose_mm',{})
    if not p or any(abs(p[k]-v)>.05 for k,v in OBSERVATION.items()):
        raise RuntimeError('Not at the calibration observation pose; no motion requested.')
    return dict(pose=p,native=n)
try:
    if not api('state')['robot'].get('connected'):api('connect',{'ip':'192.168.201.220'})
    record['before']=check();d=reference()
    seed=json.loads((ROOT/d['files']['seed']['path']).read_bytes())['fitted']
    disks=json.loads((ROOT/d['files']['disks']['path']).read_bytes())
    cfg=next(c for c in teach._configs() if c['name']=='Wide')
    for i in range(3):
        frames=[];hashes=[]
        for j in range(5):
            time.sleep(.65);check()
            with urlopen('http://127.0.0.1:5002/frame',timeout=15) as response:
                raw=response.read()
                if response.headers.get('X-Error'):raise RuntimeError(response.headers['X-Error'])
            check();frames.append(decode_reference(raw));hashes.append(hashlib.sha256(raw).hexdigest())
            (folder/f'burst_{i}_{j}.jpg').write_bytes(raw)
        if len(set(hashes))<3:raise RuntimeError('Stale camera frames')
        median=median5(frames);cv2.imwrite(str(folder/f'median_{i}.png'),median)
        item=dict(hashes=hashes);record['bursts'].append(item);save()
        try:
            with patch('rim_edges.refine_consensus',side_effect=lambda x,c,b,idx:(b,idx)):
                old=measure(median,seed,disks,OBSERVATION,cfg)
            item['old_target']=old['target']
        except Exception as error:item['old_error']=str(error)
        try:item['measurement']=measure(median,seed,disks,OBSERVATION,cfg,rim_sample_span=d.get('rim_sample_span',(.12,.88)),rim_tangent_radius=d.get('rim_tangent_radius',0))
        except Exception as error:item['error']=str(error)
        save();print(json.dumps(dict(burst=i,old_error=item.get('old_error'),new_error=item.get('error'),inliers=[e['inliers'] for e in item.get('measurement',{}).get('edges',[])])),flush=True)
    ms=[b['measurement'] for b in record['bursts'] if 'measurement' in b]
    if len(ms)==3:
        record['summary']=summarize(ms)
        try:record['projected_solution']=projected_solution(ms)
        except Exception as error:record['projected_solution_error']=str(error)
    record['after']=check();record['status']='measured'
except Exception as error:
    record.update(status='rejected',error=str(error));raise
finally:
    save();print(str(folder/'run.json'),flush=True)
