"""Offline same-plate scale study; does not validate original-disk mapping."""
import json,sys
import cv2
import numpy as np
from projected_disk_trial import ROOT,Perception,same_pose,DetectionError
from projected_height_trial import verify_scale

p=Perception('anchored_grid',5);t=p.tracker;t.template_scale_search=True
previous_pose=None;seed=None;before=None
for line in (ROOT/sys.argv[1]).read_text().splitlines():
    e=json.loads(line)
    if e['event']!='stationary_image_burst':continue
    image=cv2.imread(e['median_image']);pose=e['pose']
    if previous_pose is None or not same_pose(previous_pose,pose):seed=None
    try:
        if seed is None:seed,info=t.template_seed(image)
        r=t.anchor.track(image,seed=seed)
        seed=np.asarray(r['H_preview_from_reference_preview'])
        result=dict(image=e['median_image'],z=pose['Z'],ok=True,wells=r['supported_wells'],disk=r['disk_group_spread_px'],extent=r['extent_group_spread_px'])
        if before is None:before=(pose,dict(tracking=r))
        if pose['Z']>before[0]['Z']+.1:result['scale_response']=verify_scale(before[1],dict(tracking=r),pose['Z']-before[0]['Z'])
        previous_pose=pose
    except DetectionError as ex:result=dict(image=e['median_image'],ok=False,error=str(ex))
    print(json.dumps(result),flush=True)
