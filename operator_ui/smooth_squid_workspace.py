"""Offline geometry proposal only. No network, controller, or execution calls."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from uuid import uuid4
import numpy as np

from autonomy import check_path, wrap
from review_squid_return import geometric_ik
from trajectory_queue import prepare_points

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'operator_ui/demonstrations/squid_to_home_20261017T124408Z_752cda'
KEYS = ('X','Y','Z','Rz')


def simplify(a, first, last):
    """Ordered chord approximation, <=0.35 mm and <=0.15 deg deviation."""
    if last <= first+1:return [first,last]
    delta=a[last]-a[first]
    scale=np.array([.35,.35,.35,.15])
    norm=float(np.sum((delta/scale)**2))
    t=np.clip(np.sum((a[first:last+1]-a[first])*delta/(scale*scale),axis=1)/norm,0,1) if norm else np.zeros(last-first+1)
    residual=a[first:last+1]-(a[first]+t[:,None]*delta)
    error=np.maximum(np.linalg.norm(residual[:,:3],axis=1)/.35,np.abs(residual[:,3])/.15)
    k=int(np.argmax(error))
    if np.any(np.diff(t)<-1e-8):k=1+int(np.argmin(np.diff(t)))
    elif error[k]<=1 and np.linalg.norm(delta[:3])<=40 and abs(delta[3])<=8:return [first,last]
    elif error[k]<=1:k=(last-first)//2
    k=max(1,min(last-first-1,k))+first
    return simplify(a,first,k)[:-1]+simplify(a,k,last)


def smooth(poses,envelope):
    raw=np.array([[p[k] for k in KEYS] for p in poses],dtype=float)
    raw[:,3]=np.rad2deg(np.unwrap(np.deg2rad(raw[:,3])))
    # Omit stationary sensor jitter, but retain the exact first and last poses.
    kept=[0]
    for i in range(1,len(raw)-1):
        if np.linalg.norm(raw[i,:3]-raw[kept[-1],:3])>=.1 or abs(raw[i,3]-raw[kept[-1],3])>=.05:kept.append(i)
    kept.append(len(raw)-1)
    taught=raw[kept]
    clipped=taught.copy()
    for i,k in enumerate(KEYS[:3]):
        lo,hi=envelope[k]
        if not lo<=raw[0,i]<=hi or not lo<=raw[-1,i]<=hi:raise ValueError('Endpoint outside box; cannot preserve it')
        clipped[:,i]=np.clip(clipped[:,i],lo+1,hi-1)
    clipped[0],clipped[-1]=raw[0],raw[-1]
    # Uniform combined translation/yaw arc length avoids smoothing by dwell time.
    metric=np.sqrt(np.sum(np.diff(taught[:,:3],axis=0)**2,axis=1)+(2*np.diff(taught[:,3]))**2)
    arc=np.r_[0,np.cumsum(metric)]
    good=np.r_[True,np.diff(arc)>1e-10]
    arc,taught,clipped=arc[good],taught[good],clipped[good]
    if len(arc)<2:raise ValueError('No demonstrated motion')
    grid=np.linspace(0,arc[-1],max(2,math.ceil(arc[-1]/2)+1))
    original=np.column_stack([np.interp(grid,arc,taught[:,i]) for i in range(4)])
    projected=np.column_stack([np.interp(grid,arc,clipped[:,i]) for i in range(4)])
    curve=projected.copy()
    for i in range(2,len(curve)-2):
        if grid[i]>10 and arc[-1]-grid[i]>10:
            curve[i]=np.array([1,2,2,2,1])@projected[i-2:i+3]/8
    # The convex filter cannot overshoot the box; protect both end approaches.
    indices=simplify(curve,0,len(curve)-1)
    candidate=np.round(curve[indices],2)
    candidate[0],candidate[-1]=raw[0],raw[-1]
    approximation=np.empty_like(curve)
    for left,right in zip(indices,indices[1:]):
        a,b=curve[left],curve[right]
        d=b-a;norm=float(d[:3]@d[:3]+4*d[3]*d[3])
        weights=np.array([1,1,1,4])
        t=np.clip(np.sum((curve[left:right+1]-a)*d*weights,axis=1)/norm,0,1) if norm else np.zeros(right-left+1)
        approximation[left:right+1]=candidate[indices.index(left)]+t[:,None]*(candidate[indices.index(right)]-candidate[indices.index(left)])
    error=np.linalg.norm(approximation[:,:3]-original[:,:3],axis=1)
    return raw,candidate,dict(raw_samples=len(raw),nonstationary_vertices=len(taught),output_points=len(candidate),
        box_inset_mm=1.,filter='Convex 5-tap average on 2 mm combined translation/yaw arc; first/last 10 mm protected',
        simplification_position_tolerance_mm=.35,simplification_yaw_tolerance_deg=.15,
        max_corresponding_sample_displacement_mm=float(max(error)),
        max_corresponding_sample_yaw_change_deg=float(max(abs(approximation[:,3]-original[:,3]))),
        position_deviation_note='Measured on the 2 mm resampled correspondence, not a continuous Hausdorff guarantee.')


def diagnose(path,joints,cfg,envelope):
    q=dict(joints); samples=[]; failures=[]
    for leg,(a,b) in enumerate(zip(path,path[1:]),1):
        try:check_path(a,b,q,cfg,envelope)
        except Exception as error:failures.append(dict(leg=leg,error=str(error)))
        origin=dict(q)
        n=max(1,math.ceil(math.dist([a[k] for k in KEYS[:3]],[b[k] for k in KEYS[:3]])),math.ceil(abs(b['Rz']-a['Rz'])))
        for i in range(n+1):
            f=i/n;p={k:a[k]+(b[k]-a[k])*f for k in KEYS}
            j2,j3=geometric_ik(p['X'],p['Y'],(q['J2'],q['J3']),cfg)
            j4=origin['J4']+f*wrap(b['Rz']-a['Rz'])-(j2+j3-origin['J2']-origin['J3'])
            q.update(J2=j2,J3=j3,J4=j4)
            samples.append(dict(**p,J2=j2,J3=j3,J4=j4,reach=math.hypot(p['X']-cfg['base_x_mm'],p['Y']-cfg['base_y_mm'])))
    return samples,dict(runtime_passed=not failures,failures=failures,
        ranges={k:[min(s[k] for s in samples),max(s[k] for s in samples)] for k in (*KEYS[:3],'J2','J3','J4','reach')},
        workspace_passed=all(envelope[k][0]<=s[k]<=envelope[k][1] for s in samples for k in KEYS[:3]),
        reach_passed=all(20<=s['reach']<=cfg['link1_mm']+cfg['link2_mm']-cfg['extension_margin_mm']-2 for s in samples))


def plot(folder,raw,candidate,samples):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig=plt.figure(figsize=(13,9),layout='constrained')
    fig.suptitle('Squid → taught Home-area endpoint | requested Lua speed 137 mm/s\nOffline geometry candidate — wrist validation still blocks replay',fontsize=15)
    ax=fig.add_subplot(221,projection='3d')
    ax.plot(*raw[:,:3].T,color='#a8adb6',label='Recorded')
    ax.plot(*candidate[:,:3].T,color='#007f9f',label='Smoothed')
    ax.scatter(*candidate[0,:3],color='#7b3fc6',s=45,label='Scope')
    ax.scatter(*candidate[-1,:3],color='#ed9c17',s=45,label='Taught endpoint')
    ax.set(xlabel='X (mm)',ylabel='Y (mm)',zlabel='Z (mm)');ax.legend(fontsize=8)
    ax=fig.add_subplot(222)
    ax.plot(raw[:,0],raw[:,1],color='#a8adb6',label='Recorded')
    ax.plot(candidate[:,0],candidate[:,1],color='#007f9f',label='Smoothed')
    ax.axvline(200,color='#c13737',ls='--',label='X minimum 200')
    ax.axhline(380,color='#c13737',ls=':',label='Y maximum 380')
    ax.set(xlabel='X (mm)',ylabel='Y (mm)',title='Top view');ax.axis('equal');ax.legend(fontsize=8)
    ax=fig.add_subplot(223)
    for data,label,color in [(raw,'Recorded','#a8adb6'),(candidate,'Smoothed','#007f9f')]:
        arc=np.r_[0,np.cumsum(np.linalg.norm(np.diff(data[:,:3],axis=0),axis=1))]
        ax.plot(arc,data[:,2],label=label,color=color)
    ax.set(xlabel='Distance along each path (mm)',ylabel='Z (mm)',title='Vertical movement');ax.legend()
    ax=fig.add_subplot(224)
    ax.plot([s['J2'] for s in samples],label='Predicted J2')
    ax.plot([s['J4'] for s in samples],label='Predicted J4 (actual winding)')
    ax.axhline(150,color='#c13737',ls='--',label='J4 automatic +150° limit')
    ax.set(xlabel='Spatial diagnostic sample (not time)',ylabel='Degrees',title='Joint checks remain active');ax.legend(fontsize=8)
    fig.savefig(folder/'comparison.png',dpi=150);plt.close(fig)


if __name__=='__main__':
    source=SOURCE/'taught_path.json';data=json.loads(source.read_text())['points']
    cfg=json.loads((ROOT/'operator_ui/robot_params.json').read_text())
    env=json.loads((ROOT/'operator_ui/envelope.json').read_text())['envelope']
    raw,candidate,info=smooth([p['pose_mm'] for p in data],env)
    path=[dict(zip(KEYS,map(float,p))) for p in candidate]
    forward_samples,forward=diagnose(path,data[0]['joints'],cfg,env)
    _,reverse=diagnose(list(reversed(path)),data[-1]['joints'],cfg,env)
    assert forward['workspace_passed'] and forward['reach_passed'] and reverse['workspace_passed'] and reverse['reach_passed']
    assert path[0]==data[0]['pose_mm'] and path[-1]==data[-1]['pose_mm']
    try:prepare_points(path[-1],data[-1]['joints'],list(reversed(path[:-1])),cfg,reviewed=True);queue=dict(passed=True)
    except Exception as error:queue=dict(passed=False,error=str(error))
    folder=ROOT/'operator_ui/reports/squid'/('smoothed_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:6])
    folder.mkdir()
    result=dict(created_at=datetime.now(timezone.utc).isoformat(),source=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        requested_lua_speed_mm_s=137,speed_validated=False,replay_approved=False,motion_commands_sent=False,
        physical_clearance_verified=False,method=info,params=cfg,envelope=env,
        scope_to_taught_endpoint=path,taught_endpoint_to_scope=list(reversed(path)),
        forward_validation=forward,reverse_validation=reverse,lua_queue_preparation=queue,
        notes=['Recorded endpoints and joint winding preserved; saved Home is a separate point and connection.',
               'No wrapping J4 or changing limits to pass checks. No queue upload.',
               'Geometric smoothing reduces sampled corners; no velocity/acceleration/jerk or speed137 claim.'])
    (folder/'candidate.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    plot(folder,raw,candidate,forward_samples)
    print(json.dumps(dict(folder=str(folder),method=info,ranges=forward['ranges'],workspace=forward['workspace_passed'],reach=forward['reach_passed'],queue=queue,requested_speed=137),indent=2))
