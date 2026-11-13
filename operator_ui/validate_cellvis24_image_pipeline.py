"""Offline saved-run comparison; never captures images or moves hardware."""
import hashlib,json
import cv2
from cellvis24_image_pipeline import prepare_raw,median5,metadata
from cellvis24_calibration import reference,ROOT,OBSERVATION,evaluate
from cellvis24_observation import measure,teach

RUN_IDS=['d96640d3884f498195b07bb8d245b85b','d16d8e267e1a4503838e27d9cc02fe4f',
         'c1d0b78a69674a9cae642d05b10200ff','633b3cebf767442ead7dbe91f6366786']

def evaluate_saved(name):
    folder=ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'/name
    d=reference();seed=json.loads((ROOT/d['files']['seed']['path']).read_bytes())['fitted']
    disks=json.loads((ROOT/d['files']['disks']['path']).read_bytes())
    cfg=next(c for c in teach._configs() if c['name']=='Wide')
    record=dict(source=str(folder/'run.json'),source_sha256=hashlib.sha256((folder/'run.json').read_bytes()).hexdigest(),bursts=[])
    measurements=[]
    for i in range(3):
        frames=[cv2.imread(str(folder/f'calibration_{i}_{j}.png')) for j in range(5)]
        median=median5([prepare_raw(frame) for frame in frames])
        try:
            m=measure(median,seed,disks,OBSERVATION,cfg,rim_sample_span=d.get('rim_sample_span',(.12,.88)),rim_tangent_radius=d.get('rim_tangent_radius',0));measurements.append(m)
            record['bursts'].append(dict(index=i,measurement=m,median_sha256=hashlib.sha256(median.tobytes()).hexdigest()))
        except Exception as error:record['bursts'].append(dict(index=i,error=str(error)))
    record['assessment']=evaluate(measurements) if len(measurements)==3 else dict(ok=False,code='grid_or_rim_rejected')
    return record

if __name__=='__main__':
    report=dict(motion_sent=False,image_pipeline=metadata(),runs={})
    for name in RUN_IDS:
        r=evaluate_saved(name);report['runs'][name]=r
        print(json.dumps(dict(run=name,assessment=r['assessment'])),flush=True)
    output=ROOT/'operator_ui/reports/plate_session/cellvis24_validation/image_pipeline_v3_offline_validation.json'
    output.write_text(json.dumps(report,indent=2,allow_nan=False));print(str(output))
