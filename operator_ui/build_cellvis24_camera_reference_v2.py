"""Reproduce commissioned JPEG processing offline; never teach a new target."""
import hashlib,json
from cellvis24_image_pipeline import decode_reference,median5,metadata
from cellvis24_observation import ROOT,measure,teach

SOURCE=ROOT/'Pick and Hold/Calibration/plate_profiles/cellvis24_camera_reference_v1.json'
OUTPUT=SOURCE.with_name('cellvis24_camera_reference_v2.json')

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def build():
    d=json.loads(SOURCE.read_bytes())
    for item in d['files'].values():
        if digest(ROOT/item['path'])!=item['sha256']:raise ValueError('Reference source changed')
    obs=ROOT/d['files']['observation']['path'];saved=json.loads(obs.read_bytes())
    seed=json.loads((ROOT/d['files']['seed']['path']).read_bytes())['fitted']
    disks=json.loads((ROOT/d['files']['disks']['path']).read_bytes())
    cfg=next(c for c in teach._configs() if c['name']=='Wide')
    pose=saved['before']['robot']['pose_mm'];proof=[]
    for i in range(3):
        frames=[]
        for j in range(5):
            p=obs.with_name(f'burst_{i}_{j}.jpg');frames.append(decode_reference(p.read_bytes()))
            d['files'][f'reference_frame_{i}_{j}']=dict(path=p.relative_to(ROOT).as_posix(),sha256=digest(p))
        median=median5(frames);m=measure(median,seed,disks,pose,cfg)
        original=saved['bursts'][i]['measurement']
        delta={k:m['target'][k]-original['target'][k] for k in ('x','y','rz')}
        if max(abs(v) for v in delta.values())>1e-8:raise ValueError('Canonical reference does not reproduce commissioned math')
        proof.append(dict(burst=i,target=m['target'],target_delta=delta,median_sha256=hashlib.sha256(median.tobytes()).hexdigest()))
    if proof[-1]['target']!=d['raw_target']:raise ValueError('Would change commissioned target')
    d['files']['legacy_reference']=dict(path=SOURCE.relative_to(ROOT).as_posix(),sha256=digest(SOURCE))
    d.update(schema_version=2,image_pipeline=metadata(),reference_reproduction=proof,
             note='Same commissioned target and limits; raw live frames use commissioned JPEG82 decode before median. No physical retargeting.')
    return d

if __name__=='__main__':
    d=build()
    with OUTPUT.open('x') as f:json.dump(d,f,indent=2,allow_nan=False)
    print(json.dumps(dict(path=str(OUTPUT),sha256=digest(OUTPUT),target=d['raw_target'],reproduction=d['reference_reproduction'])))
