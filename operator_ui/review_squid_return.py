"""Diagnostic IK preview only. Does not change runtime limits or send POST."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from urllib.request import urlopen
from autonomy import check_path, wrap

ROOT=Path(__file__).resolve().parents[1]
SESSION=ROOT/'operator_ui/demonstrations/home_to_squid_attempt2_20261017_043419'
def get(path):
    with urlopen('http://127.0.0.1:5002/'+path,timeout=5) as f:return json.load(f)
def geometric_ik(x,y,reference,cfg):
    """Raw model diagnostic, separate from the unchanged guarded runtime IK."""
    x-=cfg['base_x_mm'];y-=cfg['base_y_mm'];a=cfg['link1_mm'];b=cfg['link2_mm']
    c=(x*x+y*y-a*a-b*b)/(2*a*b)
    if not -1<c<1:raise ValueError('Outside strict geometric reach')
    options=[]
    for beta in (-math.acos(c),math.acos(c)):
        q2=math.degrees(math.atan2(y,x)-math.atan2(b*math.sin(beta),a+b*math.cos(beta)))-cfg['j2_offset_deg']
        q3=math.degrees(beta)-cfg['j3_offset_deg']+cfg['j2_offset_deg']
        options.append(tuple(reference[i]+wrap(q-reference[i]) for i,q in enumerate((q2,q3))))
    return min(options,key=lambda q:sum((q[i]-reference[i])**2 for i in (0,1)))

if __name__=='__main__':
    state=get('state');cfg=get('robot_params');r=state['robot']
    start={k:r['pose_mm'][k] for k in ('X','Y','Z','Rz')}
    screenshot=dict(X=197.21,Y=392.78,Z=266.08,Rz=91.31)
    points=json.loads((ROOT/'operator_ui/points.json').read_text(encoding='utf-8-sig'))
    p=points['points'][points['roles']['home']]
    home=dict(X=p['x'],Y=p['y'],Z=p['z_grip'],Rz=p['rz'])
    envelope={k:(state['envelope'][k]['min'],state['envelope'][k]['max']) for k in ('X','Y','Z')}
    # A bent-elbow staging point from q2=80, q3=140 on the measured branch.
    q2,q3=80.,140.
    a=math.radians(q2+cfg['j2_offset_deg']);b=math.radians(q2+q3+cfg['j3_offset_deg'])
    retract=dict(X=round(cfg['base_x_mm']+cfg['link1_mm']*math.cos(a)+cfg['link2_mm']*math.cos(b),3),
                 Y=round(cfg['base_y_mm']+cfg['link1_mm']*math.sin(a)+cfg['link2_mm']*math.sin(b),3),Z=300.,Rz=start['Rz'])
    path=[dict(label='Current Squid pose',**start),dict(label='Raise at Squid',**{**start,'Z':300.}),
          dict(label='Bent-elbow staging',**retract),dict(label='Return corridor',X=350.,Y=200.,Z=300.,Rz=start['Rz']),
          dict(label='Above Home, preserve yaw',X=home['X'],Y=home['Y'],Z=300.,Rz=start['Rz'])]
    yaw_delta=wrap(home['Rz']-start['Rz']);count=math.ceil(abs(yaw_delta)/30)
    for i in range(1,count+1):
        path.append(dict(label=f'Home wrist segment {i}/{count}',**{**home,'Z':300.,'Rz':start['Rz']+yaw_delta*i/count}))
    path.append(dict(label='Saved Home',**home))
    q2,q3,q4=(r['joints'][k] for k in ('J2','J3','J4'));sampled=[];runtime=[]
    for index,(left,right) in enumerate(zip(path,path[1:])):
        joint_start={**r['joints'],'J2':q2,'J3':q3,'J4':q4}
        try:check_path(left,right,joint_start,cfg,envelope);runtime.append(dict(leg=index+1,passed=True))
        except Exception as error:runtime.append(dict(leg=index+1,passed=False,error=str(error)))
        n=max(1,math.ceil(max(abs(right[k]-left[k]) for k in ('X','Y','Z'))),math.ceil(abs(wrap(right['Rz']-left['Rz']))))
        origin=(q2,q3,q4)
        for i in range(n+1):
            f=i/n;pose={k:left[k]+(right[k]-left[k])*f for k in ('X','Y','Z')}
            pose['Rz']=left['Rz']+wrap(right['Rz']-left['Rz'])*f
            q2,q3=geometric_ik(pose['X'],pose['Y'],(q2,q3),cfg)
            q4=origin[2]+wrap(pose['Rz']-left['Rz'])-(q2+q3-origin[0]-origin[1])
            reach=math.hypot(pose['X']-cfg['base_x_mm'],pose['Y']-cfg['base_y_mm'])
            sampled.append(dict(leg=index+1,pose=pose,J2=q2,J3=q3,J4=q4,reach_mm=reach))
        right['diagnostic_joints']=dict(J2=q2,J3=q3,J4=q4)
    goal_ref=(r['joints']['J2'],r['joints']['J3'])
    summary=dict(schema='cephla.squid-ik-preview.v1',created_at=datetime.now(timezone.utc).isoformat(),
        screenshot_goal=screenshot,screenshot_path='C:/Users/Cephla/Pictures/Screenshots/Screenshot 2026-10-17 045016.png',
        live_robot=r,live_vs_screenshot={k:round(start[k]-screenshot[k],4) for k in start},
        geometric_goal_joints=geometric_ik(screenshot['X'],screenshot['Y'],goal_ref,cfg),
        goal_reach_mm=math.hypot(screenshot['X']-cfg['base_x_mm'],screenshot['Y']-cfg['base_y_mm']),
        runtime_reach_limit_mm=cfg['link1_mm']+cfg['link2_mm']-cfg['extension_margin_mm']-2,
        requested_translation_speed=137,wrist_speed_max=30,waypoints=path,runtime_leg_checks=runtime,
        diagnostic_peak_abs_J2=max(abs(s['J2']) for s in sampled),diagnostic_peak_abs_J4=max(abs(s['J4']) for s in sampled),
        runtime_config=cfg,workspace=envelope,executable=False,physical_clearance_verified=False,
        reasons=['Current pose and departure violate unchanged automatic reach, wrist and workspace limits.',
                 'Diagnostic geometric solutions are not runtime approval or collision checks.',
                 '137 has not been commissioned for this near-full-extension Squid departure.',
                 'Manual mode/program stopped; any loaded transition must avoid claw reset.'],
        no_motion_commands=True,no_limits_changed=True)
    folder=ROOT/'operator_ui/reports/squid';folder.mkdir(exist_ok=True,parents=True)
    target=folder/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_return_preview.json')
    target.write_text(json.dumps(summary,indent=2,allow_nan=False),encoding='utf-8')
    (SESSION/'screenshot_goal.json').write_text(json.dumps(dict(goal=screenshot,source=summary['screenshot_path'],live_at_review=r,preview=str(target)),indent=2),encoding='utf-8')
    print(json.dumps(dict(file=str(target),reach=summary['goal_reach_mm'],peak_J2=summary['diagnostic_peak_abs_J2'],peak_J4=summary['diagnostic_peak_abs_J4'],waypoints=path,runtime=runtime),indent=2))
