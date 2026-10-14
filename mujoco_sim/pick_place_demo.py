"""Scripted offline contact test, NOT an RL policy or hardware controller.

Run headless first; --viewer replays the same physics and stays open at the end.
R restarts the simulation, P pauses/resumes. Nothing connects to the real arm.
"""
import argparse
import json
import math
from pathlib import Path
import time

import mujoco
import numpy as np
from contact_sim import build_model, default_scene, contact_names


def setup():
    scene=default_scene()
    scene['rack'].update(x=580,y=-120,z=0,rz=-90,shelf=2)
    model,xml=build_model(scene)
    data=mujoco.MjData(model)
    addresses=[model.joint(n).qposadr[0] for n in ['J1','J2','J3','J4','finger_-1','finger_1']]
    # Cartesian points are claw center, not TCP, in mm; yaw remains zero.
    # Release 9 mm above shelf to clear the estimated jaws' lower edges.
    points=[('ready', [350,-180,75,28],1.5),
            ('approach', [350,-180,41,28],4),
            ('grasp', [350,-180,41,18],2),
            ('lift', [350,-180,145,18],8),
            ('approach rack', [475,-120,145,18],9),
            ('align shelf 2', [475,-120,145,18],2),
            ('insert', [580,-120,145,18],9),
            ('lower to release', [580,-120,140,18],2),
            ('release', [580,-120,140,28],2),
            ('settle', [580,-120,140,28],2),
            ('withdraw', [460,-120,140,28],9),
            ('finished', [460,-120,160,28],3)]
    data.qpos[addresses]=ik(points[0][1],scene)
    data.ctrl[:]=data.qpos[addresses]
    mujoco.mj_forward(model,data)
    if any(c.dist < -.001 for c in data.contact):raise ValueError('Initial penetration')
    return scene,model,data,xml,points


def ik(point,scene):
    x,y,z,e1=point;p=scene['robot']
    dx=x-p['claw_arm_x_mm']-p['base_x_mm'];dy=y-p['claw_arm_y_mm']-p['base_y_mm']
    l1,l2=p['link1_mm'],p['link2_mm']
    c=(dx*dx+dy*dy-l1*l1-l2*l2)/(2*l1*l2)
    if abs(c)>1:raise ValueError('Claw target out of reach')
    beta=-math.acos(c)
    j2=math.atan2(dy,dx)-math.atan2(l2*math.sin(beta),l1+l2*math.cos(beta))
    j3=beta+math.pi;j4=-j2-j3
    if abs(j2)>math.radians(93) or abs(j4)>math.radians(150):raise ValueError('Joint target exceeds guard')
    return np.array([z/1000,j2,j3,j4,e1/2000,e1/2000])


def command(t,points,scene):
    start=np.array(points[0][1],dtype=float)
    for phase,end,duration in points:
        if t<=duration:
            u=max(0,t/duration);s=10*u**3-15*u**4+6*u**5
            return ik(start+(np.array(end)-start)*s,scene),phase
        t-=duration;start=np.array(end,dtype=float)
    return ik(points[-1][1],scene),'finished'


def run(output,visible=False):
    scene,model,data,xml,points=setup()
    duration=sum(p[2] for p in points)+3
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    (output/'scene.xml').write_text(xml,encoding='utf-8')
    events=[];last=None;max_lift=0;max_pen=0;unwanted=set();frames=[]
    handle=None;state={'paused':False,'restart':False}
    if visible:
        from mujoco import viewer
        def key(k):
            if k in (ord('P'),ord('p')):state['paused']=not state['paused']
            if k in (ord('R'),ord('r')):state['restart']=True
        handle=viewer.launch_passive(model,data,key_callback=key)
        handle.cam.lookat[:]=[.35,-.1,.17];handle.cam.distance=1.15;handle.cam.azimuth=135;handle.cam.elevation=-23
    try:
        while data.time<duration or (handle and handle.is_running()):
            if handle and not handle.is_running():break
            before=time.monotonic()
            if state['restart']:
                _,_,initial,_,_=setup();data.qpos[:]=initial.qpos;data.qvel[:]=0;data.time=0
                mujoco.mj_forward(model,data);state['restart']=False;last=None
            if not state['paused'] and data.time<duration:
                data.ctrl[:],phase=command(data.time,points,scene)
                mujoco.mj_step(model,data)
                if any(w.number for w in data.warning):raise RuntimeError('Simulation warning')
                platepos=data.xpos[model.body('plate').id].copy()
                max_lift=max(max_lift,float(platepos[2]))
                pairs=contact_names(model,data)
                for c,pair in zip(data.contact,pairs):
                    max_pen=max(max_pen,-c.dist)
                    if 'plate_geom' not in pair:unwanted.add(tuple(sorted(pair)))
                if phase!=last:
                    events.append(dict(phase=phase,time=round(data.time,3),plate_m=platepos.tolist(),contacts=pairs));last=phase
                    print(phase,platepos,flush=True)
                if round(data.time/model.opt.timestep)%25==0:frames.append(np.r_[data.time,data.qpos.copy()])
            if handle:
                handle.sync();time.sleep(max(0,(model.opt.timestep if data.time<duration and not state['paused'] else .02)-(time.monotonic()-before)))
    finally:
        if handle:handle.close()
    pairs=contact_names(model,data);pos=data.xpos[model.body('plate').id].copy()
    platevel=data.qvel[model.joint('plate_free').dofadr[0]:model.joint('plate_free').dofadr[0]+6]
    supported=any('plate_geom' in p and 'shelf_2' in p for p in pairs)
    released=not any('plate_geom' in p and any('jaw' in n for n in p) for p in pairs)
    rotation=data.xmat[model.body('plate').id].reshape(3,3)
    half=np.array([scene['plate']['length_mm'],scene['plate']['width_mm'],scene['plate']['height_mm']])/2000
    projected=np.abs(rotation)@half
    footprint_inside=bool(abs(pos[0]-.58)+projected[0]<.070 and abs(pos[1]+.12)+projected[1]<.045)
    upright=bool(rotation[2,2]>.999)
    success=bool(supported and released and footprint_inside and upright and abs(pos[2]-.1172)<.001 and np.linalg.norm(platevel)<.001 and max_lift>.1 and not unwanted)
    report=dict(success=success,scripted_not_rl=True,plate_final_m=pos.tolist(),max_plate_height_m=max_lift,
                shelf_contact=supported,released=released,footprint_inside=footprint_inside,upright=upright,unwanted_contact_pairs=sorted(unwanted),
                max_penetration_mm=max_pen*1000,events=events,warning='Approximate offline model; not a hardware validation.')
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    np.savez_compressed(output/'rollout.npz',frames=np.array(frames))
    renderer=mujoco.Renderer(model,height=600,width=800)
    cam=mujoco.MjvCamera();cam.lookat[:]=[.35,-.1,.17];cam.distance=1.15;cam.azimuth=135;cam.elevation=-23
    renderer.update_scene(data,cam)
    from PIL import Image
    Image.fromarray(renderer.render()).save(output/'final.png');renderer.close()
    print(json.dumps({k:v for k,v in report.items() if k!='events'},indent=2),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--viewer',action='store_true')
    parser.add_argument('--output',default='mujoco_sim/runs/pick_place')
    args=parser.parse_args();run(args.output,args.viewer)
