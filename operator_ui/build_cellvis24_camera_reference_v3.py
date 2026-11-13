"""Re-measure the commissioned reference with a fixed straight-rim ROI. Offline."""
import hashlib,json
from cellvis24_image_pipeline import decode_reference,median5
from cellvis24_observation import ROOT,measure,summarize,teach

SOURCE=ROOT/'Pick and Hold/Calibration/plate_profiles/cellvis24_camera_reference_v2.json'
OUTPUT=SOURCE.with_name('cellvis24_camera_reference_v3.json')
SPAN=[.25,.75]

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def build():
    d=json.loads(SOURCE.read_bytes())
    for item in d['files'].values():
        if digest(ROOT/item['path'])!=item['sha256']:raise ValueError('Reference source changed')
    obs=ROOT/d['files']['observation']['path'];saved=json.loads(obs.read_bytes())
    seed=json.loads((ROOT/d['files']['seed']['path']).read_bytes())['fitted']
    disks=json.loads((ROOT/d['files']['disks']['path']).read_bytes())
    cfg=next(c for c in teach._configs() if c['name']=='Wide')
    pose=saved['before']['robot']['pose_mm'];proof=[];measurements=[]
    for i in range(3):
        frames=[decode_reference((ROOT/d['files'][f'reference_frame_{i}_{j}']['path']).read_bytes()) for j in range(5)]
        median=median5(frames)
        m=measure(median,seed,disks,pose,cfg,rim_sample_span=SPAN,rim_tangent_radius=2);measurements.append(m)
        proof.append(dict(burst=i,measurement=m,median_sha256=hashlib.sha256(median.tobytes()).hexdigest()))
    summary=summarize(measurements)
    if not summary['stationary_checks_passed']:raise ValueError('New reference ROI is not stable')
    d['files']['previous_reference']=dict(path=SOURCE.relative_to(ROOT).as_posix(),sha256=digest(SOURCE))
    d.update(schema_version=3,rim_sample_span=SPAN,rim_tangent_radius=2,rim_line_fit='gm-irls-1.5px-v1',raw_target=measurements[2]['target'],
             previous_raw_target=d['raw_target'],reference_reproduction=proof,reference_stability=summary,
             note='Same physical reference and taught grasp. Fixed central50% rim span avoids rounded corners/holder tabs; five-pixel tangent averaging reduces noise. Reference and live use identical processing; support fraction, residual and stability thresholds unchanged.')
    return d

if __name__=='__main__':
    d=build()
    with OUTPUT.open('x') as f:json.dump(d,f,indent=2,allow_nan=False)
    print(json.dumps(dict(path=str(OUTPUT),target=d['raw_target'],stability=d['reference_stability'])))
