"""Offline S4 contact prototype. Never imports robot services or opens controller sockets.

Replay an exported bioyond-demo-v1 JSON. SI units internally. Primitive collision
geometry and estimated dynamics: NOT a commissioned hardware model.
"""
import argparse
import json
import math
from pathlib import Path
import time
import xml.etree.ElementTree as ET

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PHASES = {'approach', 'grasp', 'lift', 'insert', 'release', 'withdraw'}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def default_scene():
    p = read_json(ROOT / 'operator_ui/robot_params.json')
    p.update(read_json(ROOT / 'operator_ui/static/preview_config.json'))
    rack = read_json(ROOT / 'operator_ui/static/models/plate_rack_config.json')
    rack.update(x=350, y=180, z=0, rz=0, shelf=2)
    return dict(robot=p, reference=dict(zOffset=0, wristOffset=0), rack=rack,
        plate=dict(x=350, y=-180, support_top_mm=20, yaw_deg=0,
                           length_mm=127.76, width_mm=85.48, height_mm=14.4, mass_kg=0.12))


def finite(value, name, low=-10000, high=10000):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'Invalid {name}: {value!r}')
    return value


def validate(doc):
    if doc.get('schema') != 'bioyond-demo-v1':
        raise ValueError('Expected bioyond-demo-v1')
    if doc.get('units') != dict(distance='mm', angle='deg', time='s'):
        raise ValueError('Expected explicit mm/deg/s units')
    sc = doc['scene']; p = sc['robot']; ref = sc['reference']; rack = sc['rack']; plate = sc['plate']
    defaults=default_scene()['robot']
    for k in defaults:
        if isinstance(defaults[k], (int, float)):
            finite(p[k], k)
    for k in ['zOffset', 'wristOffset']: finite(ref[k], k)
    for k in ['x', 'y', 'z', 'rz']: finite(rack[k], 'rack.'+k)
    for k in ['height_mm','shelf_width_mm','shelf_depth_mm','shelf_pitch_mm','shelf_thickness_mm','first_shelf_top_mm','post_width_mm','base_thickness_mm','lip_height_mm','lip_thickness_mm']:
        finite(rack[k], k, 0.1, 2000)
    if rack['shelf_count'] != 5 or rack['shelf'] not in range(1, 6): raise ValueError('Expected five-shelf rack and target 1..5')
    for k in ['x','y','yaw_deg']: finite(plate[k], 'plate.'+k)
    for k in ['length_mm','width_mm','height_mm','support_top_mm']: finite(plate[k], k, 1, 1000)
    finite(plate['mass_kg'], 'mass_kg', 0.001, 2)
    rows = doc['samples']
    if not 2 <= len(rows) <= 100000: raise ValueError('Need 2..100000 keyframes')
    previous = -1
    for row in rows:
        t = finite(row['t'], 't', 0, 3600)
        if t <= previous: raise ValueError('Timestamps must strictly increase')
        previous = t
        for k,lo,hi in [('J1',p['j1_min_mm'],p['j1_max_mm']),('J2',-93,93),('J3',-180,180),('J4',-150,150),('e1_mm',0,28)]: finite(row[k], k, lo, hi)
        if row['phase'] not in PHASES: raise ValueError('Unknown phase')
        # Prevent discontinuous elbow-branch changes through the folded singularity.
        radius = math.sqrt(p['link1_mm']**2+p['link2_mm']**2+2*p['link1_mm']*p['link2_mm']*math.cos(math.radians(row['J3']+p['j3_offset_deg']-p['j2_offset_deg'])))
        if not 20 <= radius <= p['link1_mm']+p['link2_mm']-p['extension_margin_mm']-2+1e-6: raise ValueError('Reference exceeds preview reach guard')
    for a,b in zip(rows, rows[1:]):
        if a['J3']*b['J3'] < 0: raise ValueError('Reference crosses folded elbow branch')
    return doc


def vec(*xs): return ' '.join(f'{x:.10g}' for x in xs)


def build_model(sc):
    p, r, plate, ref = (sc[k] for k in ['robot','rack','plate','reference'])
    root = ET.Element('mujoco', model='S4 offline contact prototype')
    ET.SubElement(root,'compiler',angle='degree',autolimits='true')
    ET.SubElement(ET.SubElement(root,'visual'),'global',offwidth='800',offheight='600')
    ET.SubElement(root,'option',timestep='0.002',integrator='implicitfast',gravity='0 0 -9.81',iterations='80',cone='elliptic',noslip_iterations='10')
    default=ET.SubElement(root,'default')
    ET.SubElement(default,'geom',friction='0.8 0.01 0.001',condim='4',solref='0.008 1',solimp='0.95 0.99 0.001')
    ET.SubElement(default,'joint',damping='2',armature='0.02')
    world=ET.SubElement(root,'worldbody')
    ET.SubElement(world,'light',pos='0 -1 2',dir='0 0 -1')
    ET.SubElement(world,'geom',name='floor',type='plane',size='1 1 0.01',rgba='.18 .2 .23 1')
    def box(parent,name,pos,size,color='.65 .7 .75 1',mass=None):
        attrs=dict(name=name,type='box',pos=vec(*pos),size=vec(*size),rgba=color)
        if mass is not None: attrs['mass']=str(mass)
        return ET.SubElement(parent,'geom',**attrs)
    rack=ET.SubElement(world,'body',name='rack',pos=vec(r['x']/1000,r['y']/1000,r['z']/1000),euler=vec(0,0,r['rz']))
    w,d,h,t,post,bt=[r[k]/1000 for k in ['shelf_width_mm','shelf_depth_mm','height_mm','shelf_thickness_mm','post_width_mm','base_thickness_mm']]
    if 'outer_width_mm' in r and 'outer_depth_mm' in r:
        # Measured exterior envelope includes the base and posts. Do not add
        # their thickness outside dimensions supplied as overall dimensions.
        ow, od = r['outer_width_mm']/1000, r['outer_depth_mm']/1000
        if w > ow-2*post+1e-9 or d > od+1e-9:
            raise ValueError('Shelf does not fit inside the measured rack envelope')
        if r['first_shelf_top_mm']+(r['shelf_count']-1)*r['shelf_pitch_mm']+r['lip_height_mm'] > r['height_mm']:
            raise ValueError('Top shelf exceeds measured rack height')
        box(rack,'rack_base',(0,0,bt/2),(ow/2,od/2,bt/2))
        for sign in [-1,1]:
            box(rack,'post_'+str(sign),(sign*(ow/2-post/2),od/2-post/2,h/2),(post/2,post/2,h/2))
    else:
        # Retain the geometry of historical exported demonstrations.
        box(rack,'rack_base',(0,0,bt/2),(w/2+post,d/2+post,bt/2))
        for sign in [-1,1]: box(rack,'post_'+str(sign),(sign*(w/2+post/2),d/2,h/2),(post/2,post/2,h/2))
    for i in range(r['shelf_count']):
        z=(r['first_shelf_top_mm']+i*r['shelf_pitch_mm'])/1000
        # Conservative solid shelf: photo cutouts omitted instead of using a convex OBJ hull.
        box(rack,f'shelf_{i+1}',(0,0,z-t/2),(w/2,d/2,t/2),'.95 .6 .15 1' if i+1==r['shelf'] else '.65 .7 .75 1')
        lh,lt=r['lip_height_mm']/1000,r['lip_thickness_mm']/1000
        box(rack,f'back_lip_{i+1}',(0,d/2-lt/2,z+lh/2),(w/2,lt/2,lh/2))
    px,py,st=plate['x']/1000,plate['y']/1000,plate['support_top_mm']/1000
    support=ET.SubElement(world,'body',name='support',pos=vec(px,py,0),euler=vec(0,0,plate['yaw_deg']))
    box(support,'support_top',(0,0,st/2),(plate['length_mm']/2000,plate['width_mm']/2000,st/2),'.25 .35 .45 1')
    pb=ET.SubElement(world,'body',name='plate',pos=vec(px,py,st+plate['height_mm']/2000+0.001),euler=vec(0,0,plate['yaw_deg']))
    ET.SubElement(pb,'freejoint',name='plate_free')
    box(pb,'plate_geom',(0,0,0),tuple(plate[k]/2000 for k in ['length_mm','width_mm','height_mm']),'.2 .85 .85 1',plate['mass_kg'])
    base=ET.SubElement(world,'body',name='base',pos=vec(p['base_x_mm']/1000,p['base_y_mm']/1000,0))
    box(base,'column',(-.06,0,.25),(.025,.05,.25))
    carriage=ET.SubElement(base,'body',name='carriage',pos=vec(0,0,ref['zOffset']/1000))
    ET.SubElement(carriage,'joint',name='J1',type='slide',axis='0 0 1',range=vec(p['j1_min_mm']/1000,p['j1_max_mm']/1000),damping='80')
    box(carriage,'carriage_geom',(0,0,.07),(.03,.035,.04),'.25 .65 1 1',2)
    shoulder=ET.SubElement(carriage,'body',name='shoulder',euler=vec(0,0,p['j2_offset_deg']))
    ET.SubElement(shoulder,'joint',name='J2',axis='0 0 1',range='-93 93')
    l1,l2=p['link1_mm']/1000,p['link2_mm']/1000
    box(shoulder,'link1',(l1/2,0,.09),(l1/2,.025,.018),'1 .6 .15 1',1.2)
    elbow=ET.SubElement(shoulder,'body',name='elbow',pos=vec(l1,0,0),euler=vec(0,0,p['j3_offset_deg']-p['j2_offset_deg']))
    ET.SubElement(elbow,'joint',name='J3',axis='0 0 1',range='-180 180')
    box(elbow,'link2',(l2/2,0,.045),(l2/2,.022,.016),'.35 .8 .4 1',0.8)
    wrist=ET.SubElement(elbow,'body',name='wrist',pos=vec(l2,0,0),euler=vec(0,0,ref['wristOffset']-p['j3_offset_deg']))
    ET.SubElement(wrist,'joint',name='J4',axis='0 0 1',range='-150 150')
    ET.SubElement(wrist,'site',name='tcp',size='.005',rgba='1 0 0 1')
    cx,cy=p['claw_arm_x_mm']/1000,p['claw_arm_y_mm']/1000
    box(wrist,'tool_bracket',(cx/2,cy,.025),(cx/2,.007,.005),'.7 .35 .85 1',0.3)
    box(wrist,'gripper_crossbar',(cx,cy,.025),(.009,.053,.005),'.7 .35 .85 1',0.15)
    ET.SubElement(wrist,'site',name='grasp_center',pos=vec(cx,cy,0),size='.004')
    for sign in [-1,1]:
        jaw=ET.SubElement(wrist,'body',name=f'jaw_{sign}',pos=vec(cx,cy+sign*.033,0))
        ET.SubElement(jaw,'joint',name=f'finger_{sign}',type='slide',axis=vec(0,sign,0),range='0 .014',damping='10')
        box(jaw,f'jaw_geom_{sign}',(0,0,0),(.035,.003,.014),'.8 .4 1 1',0.08)
    actuators=ET.SubElement(root,'actuator')
    for name,kp,kv,force,limit in [('J1',10000,200,2000,vec(p['j1_min_mm']/1000,p['j1_max_mm']/1000)),('J2',300,30,80,vec(*np.deg2rad([-93,93]))),('J3',200,20,50,vec(*np.deg2rad([-180,180]))),('J4',100,10,20,vec(*np.deg2rad([-150,150]))),('finger_-1',1500,15,12,'0 .014'),('finger_1',1500,15,12,'0 .014')]:
        ET.SubElement(actuators,'position',name=name+'_servo',joint=name,kp=str(kp),kv=str(kv),ctrlrange=limit,forcerange=vec(-force,force))
    xml=ET.tostring(root,encoding='unicode')
    return mujoco.MjModel.from_xml_string(xml), xml


def trajectory(rows):
    """Quintic, stop-at-keyframe reference; ignore mouse timing except phase holds.

    Limits reference speed to 30 mm/s Z, 20 deg/s rotations, 10 mm/s E1;
    conservative acceleration bounds. Not a hardware trajectory certificate.
    """
    values=np.array([[s['J1']/1000,*np.deg2rad([s['J2'],s['J3'],s['J4']]),s['e1_mm']/2000,s['e1_mm']/2000] for s in rows])
    vmax=np.array([.03,*np.deg2rad([20]*3),.005,.005])
    amax=np.array([.06,*np.deg2rad([40]*3),.01,.01])
    durations=[max(.25,float(np.max(1.875*np.abs(b-a)/vmax)),float(np.max(np.sqrt(5.774*np.abs(b-a)/amax)))) for a,b in zip(values,values[1:])]
    return values,np.r_[0,np.cumsum(durations)]


def target_at(t,values,times):
    i=min(len(times)-2,max(0,np.searchsorted(times,t,side='right')-1))
    u=np.clip((t-times[i])/(times[i+1]-times[i]),0,1)
    return values[i]+(values[i+1]-values[i])*(10*u**3-15*u**4+6*u**5),i


def contact_names(model,data):
    return [(mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,c.geom1),mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,c.geom2)) for c in data.contact]


def run(doc, output, viewer=False):
    validate(doc)
    model,xml=build_model(doc['scene']); data=mujoco.MjData(model)
    values,times=trajectory(doc['samples'])
    joint_names=['J1','J2','J3','J4','finger_-1','finger_1']
    addresses=[model.joint(n).qposadr[0] for n in joint_names]
    data.qpos[addresses]=values[0];data.ctrl[:]=values[0];mujoco.mj_forward(model,data)
    if any(c.dist < -.001 for c in data.contact):
        raise ValueError('Initial scene has >1 mm penetration. Reposition the preview/rack/plate before recording. Contacts: '+str(contact_names(model,data)))
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    (output/'scene.xml').write_text(xml,encoding='utf-8')
    frames=[];contacts=set();penetration=0.;max_error=np.zeros(6)
    handle=None
    if viewer:
        from mujoco import viewer as mjviewer
        handle=mjviewer.launch_passive(model,data)
    try:
        for step in range(int((times[-1]+2)/model.opt.timestep)):
            before=time.monotonic();target,i=target_at(data.time,values,times);data.ctrl[:]=target
            mujoco.mj_step(model,data)
            if not np.isfinite(data.qpos).all() or any(w.number for w in data.warning): raise RuntimeError('Unstable simulation; reject this rollout')
            max_error=np.maximum(max_error,np.abs(data.qpos[addresses]-target))
            contacts.update(tuple(sorted(pair)) for pair in contact_names(model,data))
            penetration=max(penetration,max((-c.dist for c in data.contact),default=0))
            if step%25==0: frames.append(np.r_[data.time,data.qpos.copy(),data.qvel.copy(),data.ctrl.copy(),i])
            if handle:
                if not handle.is_running(): break
                handle.sync();time.sleep(max(0,model.opt.timestep-(time.monotonic()-before)))
    finally:
        if handle: handle.close()
    plate_id=model.body('plate').id;r=doc['scene']['rack'];pos=data.xpos[plate_id].copy()
    theta=math.radians(r['rz']);delta=pos-np.array([r['x'],r['y'],r['z']])/1000
    local=np.array([math.cos(theta)*delta[0]+math.sin(theta)*delta[1],-math.sin(theta)*delta[0]+math.cos(theta)*delta[1],delta[2]])
    surface=(r['first_shelf_top_mm']+(r['shelf']-1)*r['shelf_pitch_mm'])/1000
    supported=any('plate_geom' in pair and f"shelf_{r['shelf']}" in pair for pair in contact_names(model,data))
    report=dict(offline_only=True,completed=bool(data.time>=times[-1]),duration_s=float(data.time),reference_duration_s=float(times[-1]),
        plate_position_m=pos.tolist(),plate_rack_local_m=local.tolist(),target_surface_m=surface,
        target_shelf_contact=bool(supported),max_penetration_mm=penetration*1000,
        max_joint_tracking_error_si=max_error.tolist(),contact_pairs=sorted(contacts),
        warning='Approximate model. Shelf contact alone is not successful placement or hardware clearance. No grasp weld/teleport; plate held only by frictional jaw contacts.')
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    np.savez_compressed(output/'rollout.npz',frames=np.asarray(frames),reference=values,reference_times=times)
    renderer=mujoco.Renderer(model,height=600,width=800)
    cam=mujoco.MjvCamera();cam.lookat[:]=[.25,0,.2];cam.distance=1.2;cam.azimuth=125;cam.elevation=-25
    renderer.update_scene(data,cam)
    from PIL import Image
    Image.fromarray(renderer.render()).save(output/'final.png');renderer.close()
    print(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('demonstration',type=Path)
    parser.add_argument('--output',type=Path,default=Path('mujoco_sim/runs/latest'))
    parser.add_argument('--viewer',action='store_true')
    args=parser.parse_args()
    run(read_json(args.demonstration),args.output,args.viewer)
