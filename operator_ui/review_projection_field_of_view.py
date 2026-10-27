"""Read-only camera-fit forecast and optional wider-view IK proposal; no motion."""
import json
from pathlib import Path
import numpy as np
import teach
from autonomy import check_path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parent.parent
log=ROOT/'operator_ui/reports/projected_disk_pilot/20261026_205808_42a744b8.jsonl'
observations=[json.loads(line) for line in log.read_text().splitlines() if json.loads(line)['event']=='observation']
last=observations[-1];p=last['pose'];m=last['measurement'];cfg=next(c for c in teach._configs() if c['name']=='Wide')
def error(mark):
    current=teach.mark_in_robot_pose(cfg,mark)
    offset=np.zeros(6);offset[:2]=current[:2]-cfg['model_mark_robot'][:2]
    correction=teach.new_acc_pose([p['X'],p['Y'],p['Z'],0,0,p['Rz']],offset)
    return correction[:2]-[p['X'],p['Y']]
mark=np.asarray(m['mark']);e=error(mark)
j=np.column_stack([error(mark+np.eye(3)[axis])-e for axis in (0,1)])
delta=np.linalg.solve(j,-e)
corners=np.asarray(m['tracking']['corners_px']);scale=3072/1200
predicted=corners+delta/scale
with urlopen('http://127.0.0.1:5002/state',timeout=5) as stream:s=json.load(stream)
pose=s['robot']['pose_mm'];target={**pose,'Z':pose['Z']+20.}
params=json.loads((ROOT/'operator_ui/robot_params.json').read_text())
envelope={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
joints=check_path(pose,target,s['robot']['joints'],params,envelope)
record=dict(motion_started=False,source_log=str(log),observed_pose=p,current_error_xy_mm=e.tolist(),
    current_corners_preview_px=corners.tolist(),desired_mark_native_px=(mark[:2]+delta).tolist(),
    predicted_centered_corners_preview_px=predicted.tolist(),image_size=[1200,800],
    forecast_assumption='Fixed height and camera attitude; image translation to vendor XY target. Not collision validation.',
    proposed_wider_view_start=pose,proposed_wider_view_target=target,expected_joints=joints,
    proposed_speed=5,clearance_confirmed=False)
print(json.dumps(record,indent=2))
