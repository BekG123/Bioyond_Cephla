"""Offline four-waypoint candidate retaining the successful final insertion."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from uuid import uuid4
import numpy as np
from autonomy import check_path, wrap
from smooth_squid_workspace import diagnose

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'operator_ui/reports/squid/home_scope_solved_20261017T125835Z_f3c36d'


if __name__=='__main__':
    source=BASE/'stepwise40_trial.json';raw=source.read_bytes();trial=json.loads(raw)
    if trial['status']!='completed' or not all(s['status']=='arrived' for s in trial['steps']):raise RuntimeError('Completed accepted trial required')
    original=json.loads((BASE/'plan.json').read_text())
    cfg=trial['plan']['cfg'];env=trial['plan']['envelope'];home=trial['plan']['start'];q=original['live_robot']['joints']
    entry=dict(trial['steps'][-2]['target']);end=dict(trial['steps'][-1]['target'])
    height=entry['Z']
    start_xy=np.array([home['X'],home['Y']]);end_xy=np.array([entry['X'],entry['Y']])
    base=np.array([cfg['base_x_mm'],cfg['base_y_mm']]);a,b=cfg['link1_mm'],cfg['link2_mm']
    def assessment(via):
        d1=float(np.linalg.norm(via-start_xy));d2=float(np.linalg.norm(end_xy-via))
        xyz=[];yaws=[]
        for left,right,offset,length in [(start_xy,via,0,d1),(via,end_xy,d1,d2)]:
            f=np.linspace(0,1,max(2,math.ceil(length)+1))
            xyz.append(left+(right-left)*f[:,None])
            yaws.append(home['Rz']+wrap(entry['Rz']-home['Rz'])*(offset+length*f)/(d1+d2))
        xy=np.concatenate(xyz);yaw=np.concatenate(yaws);delta=xy-base
        radius=np.linalg.norm(delta,axis=1)
        if min(radius)<20 or max(radius)>390:return None
        c=(radius**2-a*a-b*b)/(2*a*b)
        if np.any(abs(c)>=1):return None
        beta=-np.arccos(c)
        j2=np.rad2deg(np.arctan2(delta[:,1],delta[:,0])-np.arctan2(b*np.sin(beta),a+b*np.cos(beta)))-cfg['j2_offset_deg']
        j3=np.rad2deg(beta)-cfg['j3_offset_deg']+cfg['j2_offset_deg']+360
        j4=q['J4']+yaw-home['Rz']-(j2+j3-q['J2']-q['J3'])
        # Keep 2 degrees inside the current J2 bound, and existing J4 margin.
        if max(abs(j2))>91 or max(abs(j3))>180 or max(abs(j4))>215:return None
        return d1+d2,float(max(abs(j2))),float(max(abs(j4))),home['Rz']+wrap(entry['Rz']-home['Rz'])*d1/(d1+d2)
    candidates=[]
    for x in range(300,411,2):
        for y in range(140,341,2):
            result=assessment(np.array([x,y]))
            if result:candidates.append((result[0],x,y,result))
    if not candidates:raise RuntimeError('No four-point solution within the searched corridor')
    _,x,y,best=min(candidates)
    via=dict(X=float(x),Y=float(y),Z=height,Rz=round(best[3],2))
    points=[{**home,'Z':height},via,entry,end]
    full=[home]+points
    samples,validation=diagnose(full,q,cfg,env)
    if not validation['runtime_passed'] or not validation['workspace_passed'] or not validation['reach_passed']:raise RuntimeError(validation)
    last_q=dict(q);previous=home
    for p in points:last_q=check_path(previous,p,last_q,cfg,env);previous=p
    _,reverse=diagnose(list(reversed(full)),last_q,cfg,env)
    if not reverse['runtime_passed']:raise RuntimeError(reverse)
    try:check_path(points[0],entry,q,cfg,env);direct=dict(passed=True)
    except Exception as error:direct=dict(passed=False,error=str(error))
    length=sum(math.dist([p[k] for k in ('X','Y','Z')],[s[k] for k in ('X','Y','Z')]) for p,s in zip(full,full[1:]))
    old=[home]+original['commanded_points']
    old_length=sum(math.dist([p[k] for k in ('X','Y','Z')],[s[k] for k in ('X','Y','Z')]) for p,s in zip(old,old[1:]))
    folder=ROOT/'operator_ui/reports/squid'/('compact4_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:6]);folder.mkdir()
    ending=dict(source=str(source),source_sha256=hashlib.sha256(raw).hexdigest(),
        operator_feedback='I really like the end of how the plate was nicely put into the microscope. Save that ending. A lot of intermediate steps we do not need.',
        accepted_broad_ending_steps=trial['steps'][-10:],broad_ending_start=trial['steps'][-11]['pose_after'],
        retained_final_insertion=dict(start=entry,target=end,successful_step=trial['steps'][-1],speed_mm_s=40),
        gripper_release_commanded=False,note='Operator accepted the placement approach; no gripper release or new force/hold claim.')
    (folder/'accepted_ending.json').write_text(json.dumps(ending,indent=2,allow_nan=False))
    result=dict(source_trial=str(source),source_sha256=ending['source_sha256'],created_at=datetime.now(timezone.utc).isoformat(),
        start=home,points=points,point_count=4,validation=validation,reverse_validation=reverse,
        direct_three_point_check=direct,params=cfg,envelope=env,
        baseline_point_count=len(original['commanded_points']),baseline_length_mm=old_length,candidate_length_mm=length,
        distance_reduction_percent=100*(1-length/old_length),search='2 mm corridor grid; shortest sampled passing candidate with |J2| <=91; not a global optimality claim',
        candidate_speed_for_next_comparison_mm_s=40,eventual_requested_speed_mm_s=137,
        accepted_final_segment_exactly_preserved=points[-2:]==[entry,end],
        transit_height_mm=height,prior_upper_transit_height_mm=326.13,
        physical_clearance_verified=False,execution_authorized=False,motion_commands_sent=False,
        notes=['This is four commanded points after Home, not four macros hiding the old points.',
               'Removes approximate-Home connector and middle loops. Prior recording and trial remain untouched.',
               'Retains the exact successful final insertion; the broader earlier entry is archived, not claimed identical.',
               'New corridor at Z286.24 needs clearance review; it is 39.89 mm below prior upper transit.',
               'Current queue route profiles do not accept this four-point shape; executor integration and tests required before any queue run.',
               'Distance reduced; energy and execution time are not measured or inferred.'])
    (folder/'candidate.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig=plt.figure(figsize=(12,5),layout='constrained')
    ax=fig.add_subplot(121,projection='3d')
    ax.plot(*[[p[k] for p in old] for k in ('X','Y','Z')],color='#a9aeb6',alpha=.7,label='Successful 121-point baseline')
    ax.plot(*[[p[k] for p in full] for k in ('X','Y','Z')],'-o',color='#007f9f',label='Four-point proposal')
    ax.plot(*[[p[k] for p in [entry,end]] for k in ('X','Y','Z')],color='#da8000',lw=4,label='Exact accepted final descent')
    for i,p in enumerate(points,1):ax.text(p['X'],p['Y'],p['Z'],str(i))
    ax.set(xlabel='X (mm)',ylabel='Y (mm)',zlabel='Z (mm)');ax.legend(fontsize=8)
    ax=fig.add_subplot(122)
    ax.plot([s['J2'] for s in samples],label='J2')
    ax.plot([s['J4'] for s in samples],label='J4')
    ax.axhline(93,ls=':',color='#c13737',label='J2 automatic +93°')
    ax.axhline(-215,ls='--',color='#c13737',label='J4 buffered -215°')
    ax.set(xlabel='Spatial sample (not time)',ylabel='Degrees');ax.legend(fontsize=8)
    fig.suptitle(f'Four-point Home → scope proposal | {length:.1f} mm vs {old_length:.1f} mm\nExact final insertion retained; new transit clearance not yet reviewed',fontsize=13)
    fig.savefig(folder/'comparison.png',dpi=140);plt.close(fig)
    print(json.dumps(dict(folder=str(folder),points=points,length_mm=length,old_length_mm=old_length,reduction_percent=result['distance_reduction_percent'],ranges=validation['ranges'],direct=direct),indent=2))
