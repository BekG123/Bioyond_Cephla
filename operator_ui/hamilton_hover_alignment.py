"""Plan a high-clearance camera alignment trial. No instrument I/O here.

This commissioning trial does not register the frames for contact/pickup. It
checks a known fixed post and retains at least 50 mm above the observed rim.
"""
import math


def validate_target(target, bounds):
    if set(target) != {1, 2} or set(bounds) != {1, 2}:
        raise ValueError('Both independent channels and their limits are required.')
    for channel, xyz in target.items():
        if len(xyz) != 3 or not all(math.isfinite(v) for v in xyz):
            raise ValueError('Nonfinite or invalid target.')
        for axis, value in zip('xyz', xyz):
            if not bounds[channel][axis+'_min'] <= value <= bounds[channel][axis+'_max']:
                raise ValueError(f'Channel {channel} {axis} target outside reported limits.')
        if xyz[2] < 130:
            raise ValueError('Hover trial cannot descend below Z=130 mm.')
    if abs(target[1][0]-target[2][0]) > .001:
        raise ValueError('Both channels share X.')
    if target[2][1]-target[1][1] < 15:
        raise ValueError('Hover trial requires at least 15 mm channel spacing.')


def plan_hover(start, bounds, camera_openings, reference_error_mm):
    if not math.isfinite(reference_error_mm) or reference_error_mm > 1.0:
        raise ValueError('Fixed-post camera/controller check failed.')
    if len(camera_openings) != 2:
        raise ValueError('Exactly two observed openings required.')
    front, rear = sorted(camera_openings, key=lambda xyz: xyz[1])
    if not all(math.isfinite(v) for xyz in (front,rear) for v in xyz):
        raise ValueError('Nonfinite camera estimate.')
    if any(not (40 <= xyz[0] <= 75 and 15 <= xyz[1] <= 75 and 55 <= xyz[2] <= 80) for xyz in (front,rear)):
        raise ValueError('Camera candidates are outside the reviewed site-4 trial region.')
    if abs(front[0]-rear[0]) > .5:
        raise ValueError('Rack rotation requires separate X positioning; no shared hover trial.')
    if set(start) != {1,2} or set(bounds) != {1,2}:
        raise ValueError('Missing channels or limits.')
    # Start is the known parked area. A small downward normalization resolves
    # differing home readbacks without ever sending an above-limit destination.
    if any(not (280 <= p[0] <= 300 and 330 <= p[1] <= 385 and 165 <= p[2] <= 168) for p in start.values()):
        raise ValueError('Trial must start from the verified high parked area.')
    if abs(start[1][0]-start[2][0]) > .05:
        raise ValueError('Shared X readback disagrees.')
    ceiling = min(b['z_max'] for b in bounds.values())-.1
    if not 165 <= ceiling <= 167.5:
        raise ValueError('Unexpected high travel limit.')
    x = round((front[0]+rear[0])/2,2)
    hover_z = max(130., math.ceil(max(front[2],rear[2])+50))
    current = {c:[start[1][0],p[1],ceiling] for c,p in start.items()}
    validate_target(current,bounds)
    path = [{'phase':'normalize_high_z','positions':current}]
    high = {1:[x,front[1],ceiling],2:[x,rear[1],ceiling]}
    # Separate XY travel and descent; each commanded change is <=10 mm per axis.
    for phase, end in [('xy_at_clearance',high),('hover', {c:[p[0],p[1],hover_z] for c,p in high.items()})]:
        n=max(1,math.ceil(max(abs(end[c][i]-current[c][i]) for c in (1,2) for i in range(3))/10))
        origin=current
        for step in range(1,n+1):
            target={c:[origin[c][i]+(end[c][i]-origin[c][i])*step/n for i in range(3)] for c in (1,2)}
            validate_target(target,bounds)
            path.append({'phase':phase,'positions':target})
        current=end
    return {'kind':'high_clearance_alignment_trial','path':path,
            'camera_openings':camera_openings,'fixed_post_error_mm':reference_error_mm,
            'shared_x_hover_error_mm':abs(front[0]-rear[0])/2,
            'minimum_z_mm':130,'pickup':False,'frames_registered_for_contact':False}
