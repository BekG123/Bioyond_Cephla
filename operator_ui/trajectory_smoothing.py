"""Coalesce adjacent taught MoveL segments with bounded, ordered pose deviation.

No spline overshoot, joint-space shortcuts, timing replay, or vendor zone guesses.
Each output point is an existing transmitted point; start/end are unchanged.
"""
import math

from autonomy import TransferError, check_path, wrap

XYZ = ('X','Y','Z')
POSITION_TOLERANCE_MM = .25
YAW_TOLERANCE_DEG = .1
MAX_ARC_MM = 50.
MAX_YAW_DEG = 10.


def vertical_span(vertices,first,last):
    """Strict near-vertical, monotonic run; no horizontal corners or Z reversals."""
    a,b=vertices[first],vertices[last]
    dz=b['Z']-a['Z']
    if abs(dz)<1 or abs(dz)>200:
        return None
    if math.dist([a[k] for k in ('X','Y')],[b[k] for k in ('X','Y')])>.25:
        return None
    if abs(wrap(b['Rz']-a['Rz']))>.1:
        return None
    for p,q in zip(vertices[first:last],vertices[first+1:last+1]):
        if (q['Z']-p['Z'])*dz < -1e-9:
            return None
    error=span_error(vertices,first,last)
    # A stricter bound than ordinary grouping; hold wrist drift to <=0.05 deg.
    if error is None or error[0]>.1 or error[1]>.05:
        return None
    return error


def coalesce_vertical_runs(start,joints,points,cfg):
    """Remove artificial Z stops without changing endpoints or corner geometry.

    Applies only to an already reviewed polyline. The first/last 10 mm retain
    their original points. Every merged segment is checked along its full IK
    path; at most 200 mm vertical travel and 0.25 mm lateral endpoint drift.
    """
    if not points:raise TransferError('Cannot smooth an empty trajectory.')
    vertices=[dict(start)]+[dict(p) for p in points]
    if any(type(p.get(k)) not in (int,float) or not math.isfinite(p[k]) for p in vertices for k in (*XYZ,'Rz')):
        raise TransferError('Non-finite vertical trajectory point.')
    arc=[0.]
    for a,b in zip(vertices,vertices[1:]):
        arc.append(arc[-1]+math.dist([a[k] for k in XYZ],[b[k] for k in XYZ]))
    protected={i for i in range(len(vertices)) if arc[i]<=10 or arc[-1]-arc[i]<=10}
    first=0;q=dict(joints);out=[];merges=[]
    while first<len(vertices)-1:
        best=first+1;best_q=check_path(vertices[first],vertices[best],q,cfg,None);best_error=None
        for last in range(first+2,len(vertices)):
            if last-1 in protected:break
            error=vertical_span(vertices,first,last)
            if error is None:continue
            try:candidate_q=check_path(vertices[first],vertices[last],q,cfg,None)
            except TransferError:continue
            best,best_q,best_error=last,candidate_q,error
        out.append(dict(vertices[best]))
        if best>first+1:
            merges.append(dict(first=first,last=best,start=vertices[first],end=vertices[best],
                               commands_before=best-first,commands_after=1,z_travel_mm=vertices[best]['Z']-vertices[first]['Z'],
                               max_position_change_mm=best_error[0],max_yaw_change_deg=best_error[1]))
        first,q=best,best_q
    return out,q,dict(method='monotonic_vertical_coalescing_v1',input_points=len(points),output_points=len(out),
                     position_tolerance_mm=.1,yaw_tolerance_deg=.05,max_vertical_mm=200,
                     endpoint_guard_mm=10,merges=merges)


def span_error(vertices, first, last):
    """One monotonic correspondence bounds both complete piecewise-linear paths.

    Between vertices the error vector is linear, so its norm cannot exceed the
    maximum at the vertices. Monotone parameters also cover the new chord in
    order, preventing shortcuts across loops or overshooting/retracing a chord.
    """
    a,b = vertices[first],vertices[last]
    delta = [b[k]-a[k] for k in XYZ]+[wrap(b['Rz']-a['Rz'])]
    scales = [POSITION_TOLERANCE_MM]*3+[YAW_TOLERANCE_DEG]
    norm2 = sum((v/s)**2 for v,s in zip(delta,scales))
    previous_t, max_position, max_yaw = 0.,0.,0.
    for index in range(first,last+1):
        p=vertices[index]
        offset=[p[k]-a[k] for k in XYZ]+[wrap(p['Rz']-a['Rz'])]
        t=max(0.,min(1.,sum(o*v/(s*s) for o,v,s in zip(offset,delta,scales))/norm2)) if norm2 else 0.
        if t < previous_t-1e-9:
            return None
        previous_t=t
        position=math.sqrt(sum((offset[i]-t*delta[i])**2 for i in range(3)))
        yaw=abs(offset[3]-t*delta[3])
        if position>POSITION_TOLERANCE_MM+1e-9 or yaw>YAW_TOLERANCE_DEG+1e-9:
            return None
        max_position,max_yaw=max(max_position,position),max(max_yaw,yaw)
    return max_position,max_yaw


def group_points(start,joints,points,cfg):
    """Input must already be quantized and validated by prepare_points()."""
    vertices=[start]+points
    if not points:
        raise TransferError('Cannot group an empty trajectory.')
    arc=[0.]
    for a,b in zip(vertices,vertices[1:]):
        arc.append(arc[-1]+math.dist([a[k] for k in XYZ],[b[k] for k in XYZ]))
    protected={0,len(vertices)-1}
    for i in range(1,len(vertices)-1):
        # Preserve the first 5 mm and last 10 mm of the approach verbatim.
        if arc[i]<=5 or arc[-1]-arc[i]<=10:
            protected.add(i)
        before,at,after=vertices[i-1:i+2]
        u=[at[k]-before[k] for k in XYZ]
        v=[after[k]-at[k] for k in XYZ]
        nu,nv=math.sqrt(sum(x*x for x in u)),math.sqrt(sum(x*x for x in v))
        if min(nu,nv)>.1 and sum(x*y for x,y in zip(u,v)) < .5*nu*nv:
            protected.add(i) # substantial corner or translation reversal
        yaw1,yaw2=wrap(at['Rz']-before['Rz']),wrap(after['Rz']-at['Rz'])
        if yaw1*yaw2<0 and min(abs(yaw1),abs(yaw2))>.05:
            protected.add(i)
    grouped,groups=[],[]
    first,q=0,dict(joints)
    while first<len(vertices)-1:
        best=first+1
        best_q=check_path(vertices[first],vertices[best],q,cfg,None)
        best_error=(0.,0.)
        for last in range(first+2,len(vertices)):
            if last-1 in protected or arc[last]-arc[first]>MAX_ARC_MM:
                break
            if abs(wrap(vertices[last]['Rz']-vertices[first]['Rz']))>MAX_YAW_DEG:
                continue
            error=span_error(vertices,first,last)
            if error is None:
                continue
            try:
                candidate_q=check_path(vertices[first],vertices[last],q,cfg,None)
            except TransferError:
                continue # keep a shorter valid segment; never loosen kinematic limits
            best,best_q,best_error=last,candidate_q,error
        grouped.append(dict(vertices[best]))
        groups.append(dict(first=first,last=best,max_position_error_mm=best_error[0],max_yaw_error_deg=best_error[1]))
        first,q=best,best_q
    return grouped,q,dict(method='ordered_pose_coalescing_v1',input_points=len(points),output_points=len(grouped),
        reduction_percent=round(100*(1-len(grouped)/len(points)),1),
        position_tolerance_mm=POSITION_TOLERANCE_MM,yaw_tolerance_deg=YAW_TOLERANCE_DEG,
        max_group_arc_mm=MAX_ARC_MM,max_group_yaw_deg=MAX_YAW_DEG,
        max_position_error_mm=max(g['max_position_error_mm'] for g in groups),
        max_yaw_error_deg=max(g['max_yaw_error_deg'] for g in groups),
        protected_vertices=sorted(protected),groups=groups)
