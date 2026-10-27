"""Deterministic synthetic proof. No device access; all geometry is illustrative."""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np
from vision import analyze, model_points


def fixtures(well_count=96):
    model = dict(id='falcon_96_provisional_synthetic', validated=False,
        catalog_number=None, candidate_catalog_number='353296', manufacturer='Falcon',
        candidate_basis='User example image URL names 353296; physical plate identity unconfirmed.',
        note='Illustrative feature plane and chamfer, NOT verified Falcon product dimensions. Virtual circles are illustrative, not the taught disk reference.',
        feature_width_mm=127.76, feature_height_mm=85.48,
        grid=dict(rows=8, columns=12, pitch_mm=9., first_center_mm=[14.38,11.24], well_diameter_mm=6.4),
        orientation=dict(kind='single_chamfer', synthetic_only=True),
        virtual_circles=[dict(label='large',center_mm=[43.,42.74],radius_mm=10.),
                         dict(label='small',center_mm=[84.,42.74],radius_mm=5.)])
    if well_count==48:
        model.update(id='48_well_synthetic_only',manufacturer=None,candidate_catalog_number=None,
            candidate_basis='User confirmed 48 wells; no physical dimensions or manufacturer confirmed.',
            note='Illustrative synthetic 48-well geometry only; not measurements of the physical plate.',
            grid=dict(rows=6,columns=8,pitch_mm=13.,first_center_mm=[18.38,10.24],well_diameter_mm=10.))
    elif well_count!=96:raise ValueError('Choose 48 or 96 wells.')
    camera = dict(model='opencv_pinhole',calibration_id='synthetic_camera_only',validated=False,
        synthetic=True,image_size_px=[1200,900],K=[[1800.,0,600.],[0,1800.,450.],[0,0,1]],distortion=[0.,0,0,0,0])
    return model,camera


def render(model,camera,rotation_deg=(14,-18,8),depth_mm=300,noise=0,chamfer=True,missing=0):
    """Render true planar geometry directly in camera space, not via fitted pose."""
    ax,ay,az=np.radians(rotation_deg)
    rx=np.array([[1,0,0],[0,np.cos(ax),-np.sin(ax)],[0,np.sin(ax),np.cos(ax)]])
    ry=np.array([[np.cos(ay),0,np.sin(ay)],[0,1,0],[-np.sin(ay),0,np.cos(ay)]])
    rz=np.array([[np.cos(az),-np.sin(az),0],[np.sin(az),np.cos(az),0],[0,0,1]])
    r=rz@ry@rx; w,h=model['feature_width_mm'],model['feature_height_mm']
    t=np.array([0.,0.,depth_mm])-r@np.array([w/2,h/2,0.])
    transform=np.eye(4);transform[:3,:3]=r;transform[:3,3]=t
    k=np.array(camera['K']); supersample=2
    def project(points):
        pc=np.asarray(points)@r.T+t
        uv=pc@k.T
        return np.rint(uv[:,:2]/uv[:,2,None]*supersample).astype(np.int32)
    width,height=camera['image_size_px']
    canvas=np.full((height*supersample,width*supersample),35,np.uint8)
    rim=[[8,0,0],[w,0,0],[w,h,0],[0,h,0],[0,8,0]] if chamfer else [[0,0,0],[w,0,0],[w,h,0],[0,h,0]]
    cv2.fillConvexPoly(canvas,project(rim),210)
    _,wells=model_points(model)
    angles=np.linspace(0,2*np.pi,100,endpoint=False)
    radius=model['grid']['well_diameter_mm']/2
    ring=np.column_stack([radius*np.cos(angles),radius*np.sin(angles),np.zeros(100)])
    for center in wells[:len(wells)-missing]:
        cv2.fillConvexPoly(canvas,project(center+ring),55)
    image=cv2.resize(canvas,(width,height),interpolation=cv2.INTER_AREA)
    if noise:
        image=cv2.GaussianBlur(image,(3,3),.65)
        image=np.clip(image.astype(float)+np.random.default_rng(42).normal(0,noise,image.shape),0,255).astype(np.uint8)
    return image,transform


def run(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    model,camera=fixtures()
    for name,data in [('model',model),('camera',camera)]:
        (output/(name+'.json')).write_text(json.dumps(data,indent=2),encoding='utf-8')
    records=[]
    for name,angles,depth,noise in [('oblique',(14,-18,8),300,0),('rotated',(19,12,155),310,2),('tilted',(-22,20,-24),320,3)]:
        image,truth=render(model,camera,angles,depth,noise)
        result,overlay=analyze(image,model,camera)
        estimated=np.array(result['pose']['T_camera_plate'])
        delta=estimated[:3,:3].T@truth[:3,:3]
        error=dict(translation_mm=float(np.linalg.norm(estimated[:3,3]-truth[:3,3])),
                   rotation_deg=float(np.degrees(np.arccos(np.clip((np.trace(delta)-1)/2,-1,1)))))
        result['synthetic_ground_truth']=truth.tolist();result['synthetic_errors']=error
        cv2.imwrite(str(output/(name+'_input.png')),image)
        cv2.imwrite(str(output/(name+'_overlay.png')),overlay)
        (output/(name+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
        if name=='oblique':
            # Known synthetic transforms place the rendered plate flat in robot base.
            # Never use these manufactured transforms for a real image.
            from alignment_preview import preview
            base_plate=np.eye(4);base_plate[:3,3]=[260.,-80.,75.]
            plate_tcp=np.eye(4);plate_tcp[:3,3]=[40.,40.,0.]
            repo=Path(__file__).resolve().parents[3]
            context=dict(synthetic=True,model_id=model['id'],calibration_id=camera['calibration_id'],
                reference_id='synthetic_grasp_only',T_base_camera=(base_plate@np.linalg.inv(truth)).tolist(),
                T_plate_tcp=plate_tcp.tolist(),start_pose=dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88),
                start_joints=dict(J2=84.87686,J3=52.05595,J4=-140.81283),
                robot_params=json.loads((repo/'operator_ui/robot_params.json').read_text()),
                envelope=dict(X=[200,450],Y=[-250,380],Z=[70,400]),hover_z=300.)
            (output/'alignment_context.json').write_text(json.dumps(context,indent=2),encoding='utf-8')
            (output/'alignment_preview.json').write_text(json.dumps(preview(result,context),indent=2),encoding='utf-8')
        records.append(dict(name=name,matched_wells=result['pose']['matched_wells'],reprojection_rmse_px=result['pose']['reprojection_rmse_px'],**error))
    (output/'summary.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    rows=''.join(f"<tr><td>{r['name']}</td><td>{r['matched_wells']}/96</td><td>{r['reprojection_rmse_px']:.3f} px</td><td>{r['translation_mm']:.3f} mm</td><td>{r['rotation_deg']:.3f}&deg;</td></tr>" for r in records)
    cards=''.join(f"<section><h2>{r['name'].capitalize()}</h2><div><img src='{r['name']}_input.png'><img src='{r['name']}_overlay.png'></div></section>" for r in records)
    (output/'index.html').write_text('''<!doctype html><meta charset="utf-8"><title>Offline plate pose</title>
<style>body{max-width:1150px;margin:40px auto;padding:0 20px;font:16px system-ui;color:#243247;background:#f4f6f9}h1{font-size:28px}section{background:white;border-radius:14px;padding:20px;margin:24px 0}div{display:flex;gap:12px}img{width:49%;object-fit:contain}table{width:100%;border-collapse:collapse;background:white}td,th{text-align:left;padding:12px;border-bottom:1px solid #ddd}.notice{padding:16px;background:#fff1ce;border-radius:10px}</style>
<h1>96-well plate &rarr; virtual two-circle alignment</h1>
<p class="notice">Synthetic proof only. No robot commands or camera capture. Falcon catalog, physical geometry, orientation feature, camera calibration and taught landmark mapping remain unverified.</p>
<p>Left: generated image. Right: detected rim and well centers (green), projected virtual landmarks (orange/blue). The virtual circles are outputs, never detection evidence.</p>
<table><tr><th>Fixture</th><th>Detected wells</th><th>Reprojection RMS</th><th>Origin error vs truth</th><th>Rotation error vs truth</th></tr>'''+rows+'</table>'+cards+
        '<p>These errors measure recovery of generated geometry only, not real camera accuracy. JSON files preserve inputs, detections, pose and known truth.</p>',encoding='utf-8')
    print(json.dumps(records,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default=str(Path(__file__).parent/'demo_output'))
    run(parser.parse_args().output)
