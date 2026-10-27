"""Offline straight-transfer proposal; never grants replay or collision clearance."""
import math
from autonomy import TransferError,check_path,wrap

KEYS=('X','Y','Z','Rz')


def validate_home_transit(start, points):
    """Home translation batches: lift, level travel at >=300 mm, descent.

    Wrist-only rotation is handled separately by the existing guarded executor.
    This shape check does not establish physical clearance.
    """
    if not 1 <= len(points) <= 3 or any(type(p.get(k)) not in (int,float) or not math.isfinite(p[k])
                                       for p in [start]+list(points) for k in KEYS):
        raise TransferError('Home transit requires one to three finite points.')
    previous, phase = start, -1
    for point in points:
        xy=math.hypot(point['X']-previous['X'],point['Y']-previous['Y'])
        dz=point['Z']-previous['Z']
        if abs(wrap(point['Rz']-previous['Rz']))>.02:
            raise TransferError('Home transit must keep wrist angle fixed; rotate separately.')
        if xy<=.02 and .001<abs(dz)<=300:
            next_phase=0 if dz>0 else 2
        elif .001<xy<=500 and abs(dz)<=.02 and min(point['Z'],previous['Z'])>=299.99:
            next_phase=1
        else:
            raise TransferError('Home transit must lift vertically, cross at clearance height, then descend vertically.')
        if next_phase<=phase:
            raise TransferError('Home transit has a repeated stage or reversal.')
        phase,previous=next_phase,point


def validate_forward_entry(start,points):
    """Three-command forward route with a 3 mm advance during arrival descent."""
    if len(points)!=3 or any(type(p.get(k)) not in (int,float) or not math.isfinite(p[k])
                            for p in [start]+list(points) for k in KEYS):
        raise TransferError('Forward entry requires exactly three finite points.')
    lift,hover,end=points
    # Validate the underlying lift/transfer/descent before allowing a small tilt.
    validate_straight_shape(start,[lift,{**end,'Z':hover['Z']},end])
    dx,dy=end['X']-start['X'],end['Y']-start['Y']
    length=math.hypot(dx,dy)
    if length<10:raise TransferError('Forward entry has no reliable horizontal approach direction.')
    ux,uy=dx/length,dy/length
    ex,ey=end['X']-hover['X'],end['Y']-hover['Y']
    along=ex*ux+ey*uy;side=ex*uy-ey*ux
    if abs(along-3)>.02 or abs(side)>.02 or abs(wrap(hover['Rz']-end['Rz']))>.01:
        raise TransferError('Entrance must advance 3 mm along the approach, without lateral or yaw changes.')


def plan_forward_entry(start,end,joints,cfg,height=212):
    route=plan_straight_transfer(start,end,joints,cfg,height)
    origin,target=route['start'],route['points'][-1]
    length=math.hypot(target['X']-origin['X'],target['Y']-origin['Y'])
    hover=dict(route['points'][1])
    for k in ('X','Y'):hover[k]=round(target[k]-3*(target[k]-origin[k])/length,2)
    route['points'][1]=hover
    validate_forward_entry(origin,route['points'])
    previous=origin;q=dict(joints);segments=[]
    for label,point in zip(('vertical_departure','straight_transfer','forward_arrival'),route['points']):
        q=check_path(previous,point,q,cfg,None)
        segments.append(dict(kind=label,start=previous,end=point,
                             length_mm=math.dist([previous[k] for k in KEYS[:3]],[point[k] for k in KEYS[:3]]),
                             expected_end_joints={k:q[k] for k in ('J2','J3','J4')}))
        previous=point
    route.update(segments=segments,length_mm=sum(s['length_mm'] for s in segments),forward_entry_mm=3)
    return route


def validate_level_return(start,points):
    """Reviewed recovery: level translation, then vertical descent only."""
    if len(points)!=2 or any(type(p.get(k)) not in (int,float) or not math.isfinite(p[k])
                            for p in [start]+list(points) for k in KEYS):
        raise TransferError('Level return requires exactly two finite points.')
    across,end=points
    if (abs(across['Z']-start['Z'])>.02
            or math.dist([start[k] for k in ('X','Y')],[across[k] for k in ('X','Y')])>500
            or abs(wrap(across['Rz']-start['Rz']))>10
            or any(abs(end[k]-across[k])>.01 for k in ('X','Y'))
            or abs(wrap(end['Rz']-across['Rz']))>.01 or not 0<across['Z']-end['Z']<=300):
        raise TransferError('Level return must translate at the current height, then descend vertically.')


def validate_straight_shape(start,points):
    """Limit the separately approved executor to lift/level-transfer/descent."""
    if len(points)!=3 or any(type(p.get(k)) not in (int,float) or not math.isfinite(p[k])
                            for p in [start]+list(points) for k in KEYS):
        raise TransferError('Straight transfer requires exactly three finite points.')
    lift,across,end=points
    if (any(abs(lift[k]-start[k])>.02 for k in ('X','Y')) or abs(wrap(lift['Rz']-start['Rz']))>.02
            or not 0<lift['Z']-start['Z']<=300
            or abs(lift['Z']-across['Z'])>.01
            or math.dist([lift[k] for k in ('X','Y')],[across[k] for k in ('X','Y')])>500
            or abs(wrap(across['Rz']-lift['Rz']))>10
            or any(abs(end[k]-across[k])>.01 for k in ('X','Y'))
            or abs(wrap(end['Rz']-across['Rz']))>.01 or not 0<across['Z']-end['Z']<=300):
        raise TransferError('Reviewed straight route must be a bounded vertical lift, level transfer and vertical descent.')


def plan_straight_transfer(start,end,joints,cfg,height):
    if any(type(p.get(k)) not in (int,float) or not math.isfinite(p[k]) for p in (start,end) for k in KEYS):
        raise TransferError('Straight-transfer endpoints must be finite.')
    if type(height) not in (int,float) or not math.isfinite(height) or height<=max(start['Z'],end['Z']):
        raise TransferError('Transfer height must exceed both endpoint heights.')
    quantize=lambda p:{k:math.floor(p[k]*100+.5)/100 for k in KEYS}
    origin,target=quantize(start),quantize(end)
    z=math.floor(height*100+.5)/100
    points=[{**origin,'Z':z},{**target,'Z':z},target]
    previous=origin;q=dict(joints);segments=[]
    for label,point in zip(('vertical_departure','straight_transfer','vertical_arrival'),points):
        q=check_path(previous,point,q,cfg,None)
        segments.append(dict(kind=label,start=previous,end=point,
                             length_mm=math.dist([previous[k] for k in KEYS[:3]],[point[k] for k in KEYS[:3]]),
                             yaw_change_deg=wrap(point['Rz']-previous['Rz']),
                             expected_end_joints={k:q[k] for k in ('J2','J3','J4')}))
        previous=point
    return dict(start=origin,points=points,segments=segments,length_mm=sum(s['length_mm'] for s in segments),
                ik_passed=True,execution_authorized=False,physical_clearance_verified=False,
                note='New transit and vertical columns need physical clearance review; IK is not collision checking.')
