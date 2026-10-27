"""Read-only diagnostics for saved pickup/Hamilton demonstrations.

Shares Home's branch-preserving IK route planner. A pass is geometric evidence,
not collision clearance, grasp verification, or permission to execute.
"""
import math

from autonomy import TransferError, wrap
from researcher_home import plan_station_route
from researcher_teaching import numbers


def check_routine(routine, params, envelope, envelope_enabled):
    issues, routes = [], []
    def issue(code, message):
        issues.append(dict(code=code, message=message))
    points = routine.get('waypoints', [])
    stages = ['Home', 'Calibrate', 'Align', 'Descend', 'Grip', 'Hamilton']
    records = {}
    if not routine.get('reviewed'):
        issue('review', 'Review and save the routine first.')
    if routine.get('frame') != dict(tool='T0', user='U0'):
        issue('frame', 'The routine must use the configured T0/U0 coordinate frames.')
    for name in stages:
        found = [p for p in points if p.get('station') == name]
        if len(found) != 1:
            issue('stage', 'Exactly one '+name+' capture is required.')
            continue
        p = found[0]
        try:
            records[name] = dict(pose=numbers(p.get('pose_mm'), ('X','Y','Z','Rz')),
                                 joints=numbers(p.get('joints'), ('J1','J2','J3','J4')), record=p)
        except Exception:
            issue('measurement', name+' has missing or invalid pose/joint measurements.')
        if p.get('source') != 'robot_controller':
            issue('source', name+' must be a measured controller capture.')
    if [p.get('station') for p in points if p.get('station') != 'Waypoint'] != stages:
        issue('order', 'Required order: Home, Calibrate, Align, Descend, Grip, Hamilton.')
    if any(p.get('station') == 'Waypoint' for p in points):
        issue('intermediate', 'This checker uses raised station-to-station routes. Intermediate taught points require a separate route review.')
    if not envelope_enabled:
        issue('workspace_disabled', 'The transfer workspace must be verified and enabled.')
    for name, data in records.items():
        p = data['pose']
        outside = [f'{axis} {p[axis]:.3f} outside {envelope[axis][0]:g} to {envelope[axis][1]:g}'
                   for axis in ('X','Y','Z') if not envelope[axis][0] <= p[axis] <= envelope[axis][1]]
        if outside:
            issue('workspace', name+': '+', '.join(outside)+' mm. Review the physical workspace; limits were not changed.')
    target_info = None
    if 'Hamilton' in records:
        target_info = records['Hamilton']['pose']
        extension = math.hypot(target_info['X']-params['base_x_mm'], target_info['Y']-params['base_y_mm'])
        allowed = params['link1_mm']+params['link2_mm']-params['extension_margin_mm']-2
        if extension > allowed:
            issue('reach', f'Hamilton extension is {extension:.3f} mm from the arm base; the automatic planner allows {allowed:.3f} mm. Teach a closer position or commission the reach limit; it was not relaxed.')
    if all(n in records for n in ('Align','Descend','Grip')):
        a, d, g = [records[n]['pose'] for n in ('Align','Descend','Grip')]
        if abs(d['Z']-g['Z']) > .5:
            issue('pickup_depth', f'Descend was captured at Z{d["Z"]:.3f}, but Grip at Z{g["Z"]:.3f}: {abs(d["Z"]-g["Z"]):.3f} mm of descent is missing between stages. Record Descend at the final pickup depth before closing the jaws.')
        if any(abs(a[k]-d[k]) > .5 or abs(d[k]-g[k]) > .5 for k in ('X','Y')) or abs(wrap(a['Rz']-d['Rz'])) > .5 or abs(wrap(d['Rz']-g['Rz'])) > .5:
            issue('pickup_alignment', 'The pickup captures include lateral or wrist changes. Record a vertical descent after Align, followed by a stationary grip.')
        if not .5 < a['Z']-d['Z'] <= 300:
            issue('descent', 'The taught vertical descent must lower the arm by 0.5 to 300 mm.')
        try:
            opened, closed = [numbers(records[n]['record'].get('gripper'), ('E1',))['E1'] for n in ('Descend','Grip')]
            maximum = params['claw_gap_max_mm']-params['claw_gap_min_mm']
            if not 0 <= closed < opened <= maximum or opened-closed < .01:
                issue('grip_direction', f'Taught E1 goes from {opened:.3f} to {closed:.3f} mm. Record Descend with the jaws open, then Grip after closing; an opening is not a pickup command.')
        except Exception:
            issue('gripper_feedback', 'Measured E1 is required in both Descend and Grip records.')
    for origin in ('Home','Grip'):
        if origin not in records or 'Hamilton' not in records:
            continue
        label = origin+' to Hamilton'
        try:
            legs = plan_station_route(records[origin]['pose'], records['Hamilton']['pose'],
                                      records[origin]['joints'], params, envelope)
            routes.append(dict(name=label, valid=True, segments=len(legs), waypoints=legs))
        except (TransferError, ValueError, KeyError) as error:
            routes.append(dict(name=label, valid=False, reason=str(error)))
            issue('route', label+': '+str(error)+'. No motion was sent.')
    return dict(ok=True, routine_id=routine.get('id'), revision=routine.get('revision'),
                checks_passed=not issues, execution_ready=False, hardware_commands_sent=0,
                issues=issues, hamilton=target_info, routes=routes,
                method='Home planner: raise to at least Z300, rotate, translate, then lower; checked IK branch and wrist limits.',
                next_step='Correct the listed teaching/workspace issues, then check again.' if issues else
                          'Geometry checks passed. Full pipeline playback still requires implementation and supervised path/grasp validation.',
                limitations=['Station captures do not record the path between them.',
                             'IK checks reach and joint continuity, not obstacles or plate clearance.',
                             'Saved calibration results are historical; a transfer must calibrate and align again.',
                             'A measured E1 endpoint alone does not verify a secure grasp.'])
