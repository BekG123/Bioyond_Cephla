"""Pure offline adapter into the existing alignment planner. No executor."""
import math
from pathlib import Path
import sys
import numpy as np
from vision import DetectionError, finite_array


def rigid(value,name):
    t=finite_array(value,(4,4),name)
    r=t[:3,:3]
    if not np.allclose(t[3],[0,0,0,1]) or not np.allclose(r.T@r,np.eye(3),atol=1e-6) or not np.isclose(np.linalg.det(r),1):
        raise DetectionError(name+' must be a rigid right-handed transform')
    return t


def preview(result,context):
    """T_A_B maps B coordinates into A; mm throughout. Context is a saved file.

    Requires calibrated camera-in-base at exposure and plate-to-desired-TCP.
    Does not infer either from the virtual disks or from a camera pose alone.
    """
    if result.get('offline_only') is not True or result.get('motion_authorized') is not False:
        raise DetectionError('Only offline perception results are accepted')
    if result.get('coordinate_frame')!='opencv_camera_mm' or 'pose' not in result:
        raise DetectionError('Image-only grid previews cannot supply a metric alignment target.')
    for key in ('model_id','calibration_id'):
        if context[key]!=result[key]: raise DetectionError('Context '+key+' does not match perception')
    if bool(context.get('synthetic')) != bool(result.get('synthetic')):
        raise DetectionError('Cannot mix synthetic and real calibration contexts')
    if not context.get('reference_id'): raise DetectionError('Named grasp/alignment reference required')
    base_camera=rigid(context['T_base_camera'],'T_base_camera')
    camera_plate=rigid(result['pose']['T_camera_plate'],'T_camera_plate')
    plate_tcp=rigid(context['T_plate_tcp'],'T_plate_tcp')
    base_tcp=base_camera@camera_plate@plate_tcp
    tilt=math.degrees(math.acos(float(np.clip(base_tcp[2,2],-1,1))))
    if tilt>1: raise DetectionError('Desired TCP tilt exceeds yaw-only arm capability')
    x,y,z=base_tcp[:3,3]
    yaw=math.degrees(math.atan2(base_tcp[1,0],base_tcp[0,0]))
    target=dict(x=float(x),y=float(y),z_calibrated=float(z),rz=yaw)
    repo=Path(__file__).resolve().parents[3]
    sys.path.insert(0,str(repo/'operator_ui'))
    from autonomy import alignment_plan
    points=alignment_plan(context['start_pose'],target,context['start_joints'],
        context['robot_params'],context['envelope'],hover_z=context['hover_z'],validate_descent=False)
    return dict(offline_only=True,motion_authorized=False,synthetic=result.get('synthetic',False),
        reference_id=context['reference_id'],target_preview=target,alignment_waypoints=points,
        note='Pure existing IK/limits planner only; no descent, grip, collision approval or execution.')
