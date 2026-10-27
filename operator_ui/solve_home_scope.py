"""Read-only Home -> taught scope solver. No hardware mutation or queue upload."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from uuid import uuid4

from autonomy import check_path, wrap
from review_squid_return import get
from trajectory_queue import prepare_points, checksum
from smooth_squid_workspace import diagnose

ROOT=Path(__file__).resolve().parents[1]
PARENT=ROOT/'operator_ui/reports/squid/smoothed_20261017T124803Z_4af9ea/candidate.json'
KEYS=('X','Y','Z','Rz')


def subdivide(start,points):
    result=[];previous=dict(start)
    for point in points:
        distance=math.dist([point[k] for k in KEYS[:3]],[previous[k] for k in KEYS[:3]])
        yaw=wrap(point['Rz']-previous['Rz'])
        n=max(1,math.ceil(distance/39),math.ceil(abs(yaw)/7.5))
        for i in range(1,n+1):
            f=i/n
            result.append({**{k:previous[k]+f*(point[k]-previous[k]) for k in KEYS[:3]},'Rz':previous['Rz']+f*yaw})
        previous=dict(point)
    return result


if __name__=='__main__':
    state,cfg=get('state'),get('robot_params')
    robot=state['robot']
    if state['sequence']['active'] or not robot.get('ok') or robot.get('errors'):raise RuntimeError('Need healthy idle snapshot')
    start={k:robot['pose_mm'][k] for k in KEYS};q=dict(robot['joints'])
    points_file=ROOT/'operator_ui/points.json'
    saved=json.loads(points_file.read_text(encoding='utf-8-sig'));h=saved['points'][saved['roles']['home']]
    home=dict(X=h['x'],Y=h['y'],Z=h['z_grip'],Rz=h['rz'])
    if any(abs(start[k]-home[k])>.05 for k in KEYS):raise RuntimeError('Current arm no longer at saved Home')
    env={k:[state['envelope'][k]['min'],state['envelope'][k]['max']] for k in KEYS[:3]}
    parent=json.loads(PARENT.read_text());reverse=parent['taught_endpoint_to_scope']
    endpoint=reverse[0];goal=reverse[-1]
    # Offline policy: manual p15 specifies +/-220. Retain 5 degrees of margin.
    # This does not change deployed params or measured joint winding.
    review_cfg={**cfg,'j4_pref_abs_deg':220.,'j4_hard_abs_deg':220.}
    connector=[{**start,'Z':300.},{**endpoint,'Z':300.},dict(endpoint)]
    raw=subdivide(start,connector+reverse[1:])
    quantized,last_q=prepare_points(start,q,raw,review_cfg,reviewed=True)
    full=[start]+quantized
    samples,validation=diagnose(full,q,review_cfg,env)
    if not validation['runtime_passed']:raise RuntimeError(validation['failures'][0])
    # Check return to exact Home from the predicted scope joint winding too.
    _,return_validation=diagnose(list(reversed(full)),last_q,review_cfg,env)
    if not return_validation['runtime_passed']:raise RuntimeError(return_validation['failures'][0])
    j1_offset=q['J1']-start['Z']
    j1s=[s['Z']+j1_offset for s in samples]
    assert all(0<=v<=400 for v in j1s)
    assert all(abs(s['J3'])<=180 for s in samples)
    assert all(abs(s['J4'])<=215 for s in samples)
    # FK round-trip of all diagnostic samples, independent of pose interpolation.
    residuals=[]
    for s in samples:
        a=math.radians(s['J2']+cfg['j2_offset_deg']);b=math.radians(s['J2']+s['J3']+cfg['j3_offset_deg'])
        x=cfg['base_x_mm']+cfg['link1_mm']*math.cos(a)+cfg['link2_mm']*math.cos(b)
        y=cfg['base_y_mm']+cfg['link1_mm']*math.sin(a)+cfg['link2_mm']*math.sin(b)
        residuals.append(math.hypot(x-s['X'],y-s['Y']))
    try:prepare_points(start,q,raw,cfg,reviewed=True);deployed=dict(passed=True)
    except Exception as error:deployed=dict(passed=False,error=str(error))
    folder=ROOT/'operator_ui/reports/squid'/('home_scope_solved_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:6])
    folder.mkdir()
    result=dict(created_at=datetime.now(timezone.utc).isoformat(),parent=str(PARENT),parent_sha256=hashlib.sha256(PARENT.read_bytes()).hexdigest(),
        home_source_sha256=hashlib.sha256(points_file.read_bytes()).hexdigest(),live_robot=robot,live_params=cfg,review_params=review_cfg,envelope=env,
        requested_j4_abs_deg=220,effective_review_limit_deg=215,requested_speed_mm_s=137,
        start=start,goal=goal,connector=connector,commanded_points=quantized,queue_checksum=checksum(quantized),
        predicted_scope_joints={**last_q,'J1':goal['Z']+j1_offset},validation=validation,reverse_validation=return_validation,
        J1_range_mm=[min(j1s),max(j1s)],max_fk_xy_residual_mm=max(residuals),deployed_policy_validation=deployed,
        geometric_path_length_mm=sum(math.dist([a[k] for k in KEYS[:3]],[b[k] for k in KEYS[:3]]) for a,b in zip(full,full[1:])),
        speed_validated=False,physical_clearance_verified=False,replay_approved=False,motion_commands_sent=False,
        notes=['Preserves the previously smoothed taught geometry after the new exact-Home connector.',
               'Joint winding propagates continuously from live negative Home J4; no numerical 360-degree reset.',
               'New connector clearance needs review. Live +/-150 automatic preference was not changed.',
               '137 mm/s retained as requested; this solve does not commission speed or authorize Lua dispatch.'])
    (folder/'plan.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig=plt.figure(figsize=(12,5),layout='constrained')
    ax=fig.add_subplot(121,projection='3d')
    ax.plot(*[[p[k] for p in reverse] for k in KEYS[:3]],color='#007f9f',label='Smoothed taught route')
    ax.plot(*[[p[k] for p in [start]+connector] for k in KEYS[:3]],color='#d08400',label='New Home connection')
    for p,label in [(start,'Home'),(goal,'Scope')]:ax.scatter(p['X'],p['Y'],p['Z'],s=40);ax.text(p['X'],p['Y'],p['Z'],label)
    ax.set(xlabel='X (mm)',ylabel='Y (mm)',zlabel='Z (mm)');ax.legend(fontsize=8)
    ax=fig.add_subplot(122)
    ax.plot([s['J4'] for s in samples],label='J4, continuous from current Home')
    ax.axhline(-220,color='#c13737',ls='--',label='Requested -220 degree bound')
    ax.axhline(-215,color='#d08400',ls=':',label='Review bound with 5 degree margin')
    ax.set(xlabel='Spatial sample (not time)',ylabel='J4 (degrees)',title='Joint winding stays inside the requested range');ax.legend(fontsize=8)
    fig.suptitle('Home to scope — offline IK solution | requested speed 137 mm/s\nNo movement; connector clearance and execution policy pending',fontsize=13)
    fig.savefig(folder/'preview.png',dpi=140);plt.close(fig)
    print(json.dumps(dict(folder=str(folder),points=len(quantized),start=start,goal=goal,scope_joints=result['predicted_scope_joints'],ranges=validation['ranges'],J1=result['J1_range_mm'],FK_error=result['max_fk_xy_residual_mm'],deployed_policy=deployed,connector=connector),indent=2))
