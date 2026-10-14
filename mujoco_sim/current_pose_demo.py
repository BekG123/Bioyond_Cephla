"""Simulate a plate already between the jaws at a saved, measured arm pose.

Reads a snapshot file only. No controller connection or hardware commands.
The virtual jaw aperture/held plate and rack geometry remain assumptions.
"""
import argparse
import json
import math
from pathlib import Path
import time
import xml.etree.ElementTree as ET

import mujoco
import numpy as np
from PIL import Image
from contact_sim import build_model, default_scene, contact_names, ROOT

NAMES = ['J1','J2','J3','J4','finger_-1','finger_1']


def planar_ik(x,y,reference,p):
    """Offline analytic IK; preserve the measured elbow branch and winding."""
    dx=x-p['base_x_mm'];dy=y-p['base_y_mm'];a=p['link1_mm'];b=p['link2_mm']
    radius=math.hypot(dx,dy)
    if not 20<=radius<=a+b-p['extension_margin_mm']-2:
        raise ValueError('Reference enters folded/extended singularity margin')
    cosine=(dx*dx+dy*dy-a*a-b*b)/(2*a*b)
    def near(value,ref):return ref+(value-ref+180)%360-180
    candidates=[]
    for sign in (-1,1):
        beta=sign*math.acos(cosine)
        q2=math.degrees(math.atan2(dy,dx)-math.atan2(b*math.sin(beta),a+b*math.cos(beta)))-p['j2_offset_deg']
        q3=math.degrees(beta)-p['j3_offset_deg']+p['j2_offset_deg']
        candidates.append((near(q2,reference[0]),near(q3,reference[1])))
    return min(candidates,key=lambda pair:sum((pair[i]-reference[i])**2 for i in (0,1)))


def targets(point,scene,reference):
    x,y,z,rz,e1=point
    p=scene['robot']; ref=scene['reference']
    j2,j3=planar_ik(x,y,(reference['J2'],reference['J3']),p)
    j4=rz-ref['wristOffset']-j2-j3
    j1=z-ref['zOffset']
    if not p['j1_min_mm']<=j1<=p['j1_max_mm'] or abs(j2)>93 or abs(j4)>150:
        raise ValueError('Reference exceeds joint limits')
    return np.array([j1/1000,*np.deg2rad([j2,j3,j4]),e1/2000,e1/2000])


def setup(snapshot,entry_retreat_mm=0.):
    if not math.isfinite(entry_retreat_mm) or entry_retreat_mm < 0:
        raise ValueError('Entry retreat must be finite and nonnegative')
    pose=snapshot['robot']['pose_mm']; q=snapshot['robot']['joints']
    scene=default_scene()
    scene['reference']=dict(zOffset=pose['Z']-q['J1'],
        wristOffset=pose['Rz']-sum(q[k] for k in ['J2','J3','J4']))
    scene['rack'].update(x=580,y=-120,z=0,rz=-90,shelf=2)
    p=scene['robot']; angle=math.radians(pose['Rz'])
    cx=pose['X']+math.cos(angle)*p['claw_arm_x_mm']-math.sin(angle)*p['claw_arm_y_mm']
    cy=pose['Y']+math.sin(angle)*p['claw_arm_x_mm']+math.cos(angle)*p['claw_arm_y_mm']
    scene['plate'].update(x=cx,y=cy,yaw_deg=pose['Rz'])
    # Upper-sidewall grasp matches the previous contact demonstration.
    plate_z=(pose['Z']-14)/1000
    _,xml=build_model(scene)
    root=ET.fromstring(xml); world=root.find('worldbody')
    world.remove(world.find("body[@name='support']"))
    world.find("body[@name='plate']").set('pos',f'{cx/1000} {cy/1000} {plate_z}')
    xml=ET.tostring(root,encoding='unicode')
    model=mujoco.MjModel.from_xml_string(xml); data=mujoco.MjData(model)
    addresses=[model.joint(n).qposadr[0] for n in NAMES]
    # A virtual held plate requires touching jaws, independent of physical E1.
    initial_e1=scene['plate']['width_mm']-p['claw_gap_min_mm']-.05
    data.qpos[addresses]=[q['J1']/1000,*np.deg2rad([q['J2'],q['J3'],q['J4']]),initial_e1/2000,initial_e1/2000]
    data.ctrl[:]=data.qpos[addresses]
    mujoco.mj_forward(model,data)
    measured=np.array([pose[k] for k in ['X','Y','Z']])/1000
    error=float(np.linalg.norm(data.site_xpos[model.site('tcp').id]-measured)*1000)
    if error>.1:raise ValueError(f'Measured/simulated starting TCP mismatch: {error} mm')
    if any(c.dist<-.001 for c in data.contact):raise ValueError('Initial penetration greater than 1 mm')
    # Keep the entire plate outside the rack while changing shelf height.
    # Rack entry is +X in this scene. Retreat is -X, using coordinated IK;
    # it is not a direct J3 command and never changes the release target.
    entry_claw_x=430.-entry_retreat_mm; entry_x=entry_claw_x-p['claw_arm_x_mm']; yy=-120-p['claw_arm_y_mm']
    destination_x=580-p['claw_arm_x_mm']
    travel=max(330.,pose['Z'])
    points=[('hold at measured pose',[pose['X'],pose['Y'],pose['Z'],pose['Rz'],18],1.5),
        ('lift clear',[pose['X'],pose['Y'],travel,pose['Rz'],18],0),
        ('orient for rack',[pose['X'],pose['Y'],travel,0,18],0),
        ('approach outside rack',[entry_x,yy,travel,0,18],0),
        ('lower outside rack',[entry_x,yy,145,0,18],0),
        ('insert shelf 2',[destination_x,yy,145,0,18],0),
        ('lower to release',[destination_x,yy,140,0,18],2),
        ('release',[destination_x,yy,140,0,28],2),
        ('settle',[destination_x,yy,140,0,28],2),
        ('withdraw',[entry_x,yy,140,0,28],0),
        ('finished',[entry_x,yy,170,0,28],0)]
    if entry_retreat_mm:
        points.insert(3,('retreat away from rack',
            [pose['X']-entry_retreat_mm,pose['Y'],travel,0,18],0))
    envelope={k:(v['min'],v['max']) for k,v in snapshot['envelope'].items() if k in ('X','Y','Z')}
    previous=[pose[k] for k in ('X','Y','Z','Rz')]+[18]
    joints=dict(q)
    for i,(phase,end,duration) in enumerate(points):
        count=max(1,math.ceil(max(abs(end[j]-previous[j]) for j in range(3))/2),math.ceil(abs(end[3]-previous[3])))
        old=targets(previous,scene,joints)
        for fraction in np.linspace(0,1,count+1):
            point=np.array(previous)+(np.array(end)-previous)*fraction
            for axis,value in zip(('X','Y','Z'),point[:3]):
                if not envelope[axis][0]<=value<=envelope[axis][1]:raise ValueError('Reference outside '+axis+' envelope')
            new=targets(point,scene,joints)
            if max(abs(new[1:4]-old[1:4]))>math.radians(10):raise ValueError('Reference changes IK branch')
            joints.update(dict(zip(('J2','J3','J4'),np.degrees(new[1:4]))));old=new
        delta=np.abs(np.array(end)-previous)
        duration=max(duration,1.875*float(np.max(delta/np.array([20,20,30,10,5]))),.5)
        points[i]=(phase,end,duration)
        previous=end
    scene['initialization']=dict(source='measured arm snapshot; synthetic held plate',
        initial_tcp_error_mm=error,virtual_e1_mm=initial_e1,
        plate_center_mm=[cx,cy,plate_z*1000],physical_gripper_aperture_measured=False,
        shelf_registration_verified=False,entry_retreat_mm=entry_retreat_mm,
        retreat_direction_robot=[-1,0,0],hardware_collision_reproduced=False)
    return scene,model,data,xml,points


def command(t,points,scene,reference):
    previous=np.array(points[0][1],dtype=float)
    for phase,end,duration in points:
        if t<=duration:
            u=max(0,t/duration); blend=10*u**3-15*u**4+6*u**5
            return targets(previous+(np.array(end)-previous)*blend,scene,reference),phase
        t-=duration;previous=np.array(end,dtype=float)
    return targets(previous,scene,reference),'finished'


def run(snapshot_path,output,visible=False,entry_retreat_mm=0.):
    snapshot=json.loads(Path(snapshot_path).read_text(encoding='utf-8'))
    scene,model,data,xml,points=setup(snapshot,entry_retreat_mm)
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    (output/'scene.xml').write_text(xml,encoding='utf-8')
    (output/'scene_config.json').write_text(json.dumps(scene,indent=2),encoding='utf-8')
    (output/'source_snapshot.json').write_text(json.dumps(snapshot,indent=2),encoding='utf-8')
    (output/'waypoints.json').write_text(json.dumps(dict(units='TCP mm / yaw deg / E1 mm / seconds',points=points),indent=2),encoding='utf-8')
    initial=data.qpos.copy();initial_ctrl=data.ctrl.copy();duration=sum(p[2] for p in points)+3
    pid=model.body('plate').id; tcp=model.site('tcp').id
    frames=[]; phases=[]; events=[]; unwanted=set(); max_pen=0.;last=None;report=None;step=0
    state=dict(paused=False,restart=False);handle=None
    cam=mujoco.MjvCamera();cam.lookat[:]=[.36,-.03,.25];cam.distance=1.2;cam.azimuth=135;cam.elevation=-27
    def render(name):
        renderer=mujoco.Renderer(model,height=600,width=800)
        renderer.update_scene(data,cam);Image.fromarray(renderer.render()).save(output/name);renderer.close()
    render('initial.png')
    if visible:
        from mujoco import viewer
        def key(k):
            if k in (ord('P'),ord('p')):state['paused']=not state['paused']
            if k in (ord('R'),ord('r')):state['restart']=True
        handle=viewer.launch_passive(model,data,key_callback=key)
        handle.cam.lookat[:]=cam.lookat;handle.cam.distance=cam.distance
        handle.cam.azimuth=cam.azimuth;handle.cam.elevation=cam.elevation
    def finish(completed):
        pairs=contact_names(model,data);pos=data.xpos[pid].copy();rotation=data.xmat[pid].reshape(3,3)
        half=np.array([scene['plate'][k] for k in ('length_mm','width_mm','height_mm')])/2000
        projected=np.abs(rotation)@half
        shelf=any('plate_geom' in p and 'shelf_2' in p for p in pairs)
        released=not any('plate_geom' in p and any('jaw' in n for n in p) for p in pairs)
        inside=bool(abs(pos[0]-.58)+projected[0]<.070 and abs(pos[1]+.12)+projected[1]<.045)
        upright=bool(rotation[2,2]>.999)
        adr=model.joint('plate_free').dofadr[0];stable=bool(np.linalg.norm(data.qvel[adr:adr+6])<.001)
        success=bool(completed and shelf and released and inside and upright and stable and abs(pos[2]-.1172)<.001 and not unwanted)
        result=dict(success=success,completed=completed,duration_s=float(data.time),shelf_contact=shelf,
            released=released,footprint_inside=inside,upright=upright,stable=stable,
            plate_final_mm=(pos*1000).tolist(),initialization=scene['initialization'],
            reference=scene['reference'],unwanted_contact_pairs=sorted(unwanted),max_penetration_mm=max_pen*1000,
            events=events,hardware_motion=False,warning='Measured starting arm pose; held plate and rack registration remain simulation assumptions.')
        (output/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        np.savez_compressed(output/'rollout.npz',frames=np.array(frames),phases=np.array(phases),
            columns=np.array(['time',*[f'qpos_{i}' for i in range(model.nq)],*[f'qvel_{i}' for i in range(model.nv)],
                *[n+'_target' for n in NAMES],'tcp_x','tcp_y','tcp_z','plate_x','plate_y','plate_z']))
        render('final.png')
        print(json.dumps({k:v for k,v in result.items() if k!='events'},indent=2),flush=True)
        return result
    print('Simulation only. Starting TCP/joints match saved snapshot. R restart; P pause.',flush=True)
    try:
        while data.time<duration or (handle and handle.is_running()):
            if handle and not handle.is_running():break
            before=time.monotonic()
            if state['restart']:
                mujoco.mj_resetData(model,data);data.qpos[:]=initial;data.ctrl[:]=initial_ctrl;mujoco.mj_forward(model,data)
                frames=[];phases=[];events=[];unwanted=set();max_pen=0.;last=None;report=None;step=0;state['restart']=False
            if not state['paused'] and data.time<duration:
                data.ctrl[:],phase=command(data.time,points,scene,snapshot['robot']['joints'])
                mujoco.mj_step(model,data);mujoco.mj_forward(model,data);step+=1
                if any(w.number for w in data.warning):raise RuntimeError('Simulation warning')
                pairs=contact_names(model,data)
                for contact,pair in zip(data.contact,pairs):
                    max_pen=max(max_pen,-contact.dist)
                    allowed='plate_geom' in pair and any(n.startswith('jaw_geom_') or n=='shelf_2' for n in pair)
                    if not allowed:unwanted.add(tuple(sorted(pair)))
                if phase!=last:
                    events.append(dict(phase=phase,time=float(data.time),plate_mm=(data.xpos[pid]*1000).tolist(),contacts=pairs))
                    print(phase,flush=True);last=phase
                if step%25==0:
                    frames.append(np.r_[data.time,data.qpos.copy(),data.qvel.copy(),data.ctrl.copy(),data.site_xpos[tcp].copy(),data.xpos[pid].copy()]);phases.append(phase)
            if data.time>=duration and report is None:report=finish(True)
            if handle:
                handle.sync();time.sleep(max(0,(model.opt.timestep if data.time<duration and not state['paused'] else .02)-(time.monotonic()-before)))
    finally:
        if handle:handle.close()
    return report if report is not None else finish(False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--viewer',action='store_true')
    parser.add_argument('--entry-retreat-mm',type=float,default=0.,
        help='Simulation only: shift approach away from rack along -X; keep release fixed')
    args=parser.parse_args();run(args.snapshot,args.output,args.viewer,args.entry_retreat_mm)
