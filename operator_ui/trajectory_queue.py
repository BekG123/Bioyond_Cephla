"""Transactional, one-shot Lua trajectory executor. No raw path execution API.

Used only after RecordedReturn has checked its recording and permission. All
upload and execution share RobotService's motion lock with other Lua commands.
"""
import math
import secrets
import threading
import time

from autonomy import TransferError, check_path, ensure_arrival, wrap

VERSION = 220108
LEGACY_VERSION = 220101
PROTOCOL_SPEED_LIMITS = {LEGACY_VERSION:40,220102:47,220103:55,220104:70,220105:80,220106:100,220107:130,VERSION:137}
KEYS = ('X','Y','Z','Rz')
MOD = 2147483629


def travel_program_blocker(capability, speed=137, *, allow_initialization=False):
    """Separate a stopped runtime from absent/older published queue code."""
    if capability.get('needs_initialization'):
        if allow_initialization:
            return ''  # Planning only; execution must recheck after confirmed startup.
        return ('The controller motion program is not initialized after the reset. '
                'Startup must be confirmed with an empty gripper because it closes the jaws. '
                'Clearing a servo fault alone does not start the motion program.')
    if not capability.get('available'):
        return str(capability.get('message') or 'Could not verify the controller travel program.')
    if capability.get('max_speed_mm_s', 0) < speed:
        return (f'The published travel program supports {capability.get("max_speed_mm_s", 0):g}, '
                f'but this route requires {speed:g}. Publish the matching tested travel program.')
    return ''


def checksum(points):
    value = 0
    for point in points:
        for key in KEYS:
            value = (value*31 + math.floor(point[key]*100+.5)) % MOD
    return value


def prepare_points(start, joints, points, cfg, *, reviewed=False, vertical_runs=False, straight_transfer=False, level_return=False, forward_entry=False, reverse_entry=False, home_transit=False, scope_compact=False, hamilton_home=False, scope_phase=None, hamilton_trial=False, scope_trial=False):
    """Quantize to 0.01 mm/degree, then recheck the exact transmitted path."""
    if not 1 <= len(points) <= 1024:
        raise TransferError('Lua queue requires 1–1024 points.')
    if sum(bool(v) for v in (vertical_runs,straight_transfer,level_return,forward_entry,reverse_entry,home_transit,scope_compact,hamilton_home,hamilton_trial,scope_trial))>1:
        raise TransferError('Choose one reviewed route profile.')
    if scope_phase is not None and not (scope_compact or scope_trial):
        raise TransferError('Scope phases require the reviewed microscope route.')
    if scope_trial:
        if not reviewed:raise TransferError('Squid endpoint trial requires explicit review.')
        from squid_48well_endpoint_trial import validate_route as validate_scope_trial
        validate_scope_trial(start,points,scope_phase)
    if hamilton_home:
        if not reviewed:raise TransferError('Direct Hamilton/Home requires explicit route review.')
        from hamilton_true_home import validate_route as validate_hamilton_home
        validate_hamilton_home(start,points)
    if hamilton_trial:
        if not reviewed:raise TransferError('Hamilton endpoint trial requires explicit review.')
        from hamilton_reteach_trial import validate_route as validate_hamilton_trial
        validate_hamilton_trial(start,points)
    if scope_compact:
        if not reviewed:raise TransferError('Compact scope route requires explicit review.')
        from scope_compact137 import validate_route
        validate_route(start,points,scope_phase)
    if home_transit:
        if not reviewed:raise TransferError('Home transit requires a reviewed route.')
        from straight_transfer import validate_home_transit
        validate_home_transit(start,points)
    if forward_entry:
        if not reviewed:raise TransferError('Forward entry requires an explicitly reviewed route.')
        from straight_transfer import validate_forward_entry
        validate_forward_entry(start,points)
    if reverse_entry:
        if not reviewed:raise TransferError('Reverse entry requires an explicitly reviewed route.')
        from straight_transfer import validate_forward_entry
        reversed_path=list(reversed([start]+list(points)))
        validate_forward_entry(reversed_path[0],reversed_path[1:])
    if level_return:
        if not reviewed:raise TransferError('Level return requires its own reviewed route.')
        from straight_transfer import validate_level_return
        validate_level_return(start,points)
    if straight_transfer:
        if not reviewed or vertical_runs:
            raise TransferError('Straight transfer requires its own reviewed route profile.')
        from straight_transfer import validate_straight_shape
        validate_straight_shape(start,points)
    out, previous, q = [], start, joints
    for point in points:
        if any(type(point.get(k)) not in (int,float) or not math.isfinite(point[k]) for k in KEYS):
            raise TransferError('Non-finite trajectory point.')
        point = {k:math.floor(point[k]*100+.5)/100 for k in KEYS}
        distance=math.dist([previous[k] for k in KEYS[:3]],[point[k] for k in KEYS[:3]])
        long_vertical=(reviewed and vertical_runs and distance<=200.02
                       and math.dist([previous[k] for k in ('X','Y')],[point[k] for k in ('X','Y')])<=.25
                       and abs(wrap(point['Rz']-previous['Rz']))<=.1)
        if not (straight_transfer or level_return or forward_entry or reverse_entry or home_transit or scope_compact or hamilton_home or hamilton_trial or scope_trial) and ((distance > (50.02 if reviewed else 5.02) and not long_vertical) or abs(wrap(point['Rz']-previous['Rz'])) > (10.02 if reviewed else 1.02)):
            raise TransferError('Queued path segment exceeds the reviewed step size.')
        q = check_path(previous,point,q,cfg,None)
        out.append(point)
        previous = point
    if scope_compact:
        validate_route(start,out,scope_phase)
    if hamilton_home:
        validate_hamilton_home(start,out)
    if hamilton_trial:
        validate_hamilton_trial(start,out)
    if scope_trial:
        validate_scope_trial(start,out,scope_phase)
    if home_transit:
        validate_home_transit(start,out)
    if straight_transfer:
        validate_straight_shape(start,out)
    if level_return:
        validate_level_return(start,out)
    if forward_entry:
        validate_forward_entry(start,out)
    if reverse_entry:
        reversed_path=list(reversed([start]+out))
        validate_forward_entry(reversed_path[0],reversed_path[1:])
    return out, q


def locate(pose, path):
    """Match XYZ and yaw together so retraced positions cannot select the wrong yaw.

    One millimetre and one degree carry equal matching weight. The caller still
    enforces its independent 2 mm/2 degree limits; neither limit is widened.
    """
    if any(type(pose.get(k)) not in (int,float) or not math.isfinite(pose[k]) for k in KEYS):
        raise TransferError('Pose feedback is unavailable.')
    best, along, total = None, 0., 0.
    for a,b in zip(path,path[1:]):
        delta = [b[k]-a[k] for k in KEYS[:3]]
        length2 = sum(v*v for v in delta)
        yaw_delta = wrap(b['Rz']-a['Rz'])
        yaw_offset = wrap(pose['Rz']-a['Rz'])
        norm2 = length2+yaw_delta*yaw_delta
        dot = sum((pose[k]-a[k])*v for k,v in zip(KEYS,delta))+yaw_offset*yaw_delta
        t = max(0.,min(1.,dot/norm2)) if norm2 else 0.
        d = math.sqrt(sum((pose[k]-a[k]-t*v)**2 for k,v in zip(KEYS,delta)))
        yaw = abs(wrap(pose['Rz']-(a['Rz']+t*wrap(b['Rz']-a['Rz']))))
        length = math.sqrt(length2)
        score = d*d+yaw*yaw
        if best is None or score<best[3]: best = (d,yaw,along+t*length,score)
        along += length
        total += length
    return best[0], best[1], (100*best[2]/total if total else 0)


class LuaTrajectory:
    def __init__(self, service):
        self.service = service

    def capability(self):
        try:
            if not self.service.robot.connected:
                return dict(available=False,message='Connect the robot to check queued replay.')
            # Publishing installs code; initialization registers are only valid
            # after that program starts. Do not diagnose stale/zero registers as
            # a missing publication while the Lua app is not initialized.
            if not self.service.robot.get_lua_app_status():
                return dict(available=False,needs_initialization=True,
                            message='The controller program is not initialized. Start the published program before verifying the queue.')
            values = self.service.robot.get_sys_var_i([17,18,19])
            if values.get(17) not in PROTOCOL_SPEED_LIMITS:
                return dict(available=False,message='Queued replay needs the new Lua program published to the controller.')
            return dict(available=True,version=values[17],max_speed_mm_s=PROTOCOL_SPEED_LIMITS[values[17]],state=values.get(18),submitted=values.get(19),
                        message='Controller queue available. Groups nearby taught points into longer movements.')
        except Exception:
            return dict(available=False,message='Could not verify the controller trajectory executor.')

    def _job(self, op, token, floats=None, offset=0, count=0, timeout=10):
        robot = self.service.robot
        if floats is not None: robot.set_sys_para_f(floats)
        reply = robot.set_sys_var_i({0:22,1:1,2:token,3:offset,4:op,5:count,6:0},reply_timeout=timeout)
        if not isinstance(reply,dict) or reply.get('index') != 1 or reply.get('value') != 1:
            raise TransferError(f'Lua trajectory command {op} rejected or unconfirmed; no retry.')

    def stop_controller(self):
        """Stop the program independently of the motion mutex. Never resume it."""
        result = self.service.program('stop')
        if not result.get('ok'):
            self.service.trajectory_fault = True
            raise TransferError('Controller Stop was not confirmed. Use the E-stop; inspect Developer view.')
        deadline = time.monotonic()+3
        while time.monotonic()<deadline:
            if self.service.robot.get_prog_state().get('state') == 'stopped':
                return
            time.sleep(.05)
        self.service.trajectory_fault = True
        raise TransferError('Controller has not reported stopped. Use the E-stop; inspect Developer view.')

    def execute(self, run, start, joints, points, cfg, speed, progress, *, grouped=False, reviewed=False, vertical_runs=False, straight_transfer=False, level_return=False, forward_entry=False, reverse_entry=False, research_speed47=False, research_speed55=False, research_speed70=False, research_speed80=False, research_speed100=False, research_speed130=False, research_speed137=False, home_transit=False, home_speed137=False, scope_compact=False, scope_speed137=False, hamilton_home=False, scope_phase=None, hamilton_trial=False, scope_trial=False):
        if sum(bool(v) for v in (research_speed47,research_speed55,research_speed70,research_speed80,research_speed100,research_speed130,research_speed137,home_speed137,scope_speed137))>1:raise TransferError('Choose one research speed profile.')
        speed_limit=(137 if research_speed137 else 130 if research_speed130 else 100 if research_speed100 else 80 if research_speed80 else 70 if research_speed70 else 55 if research_speed55 else 47) if (research_speed47 or research_speed55 or research_speed70 or research_speed80 or research_speed100 or research_speed130 or research_speed137) and reviewed and (forward_entry or reverse_entry) else 40
        if home_speed137:
            if not reviewed or not (home_transit or straight_transfer or hamilton_home or hamilton_trial):
                raise TransferError('Home speed requires the checked Home transit profile.')
            if straight_transfer and (len(points)!=3 or min(points[0]['Z'],points[1]['Z'])<299.99):
                raise TransferError('Home transfer must use at least Z300 clearance height.')
            speed_limit=137
        if scope_speed137:
            if not reviewed or not (scope_compact or scope_trial):raise TransferError('Scope speed requires the exact reviewed compact route.')
            speed_limit=137
        if scope_phase in ('descent','raised_descent'):
            from scope_compact137 import DESCENT_SPEED
            speed_limit=min(speed_limit,DESCENT_SPEED)
        if scope_trial and scope_phase in ('departure','raised_departure'):
            speed_limit=min(speed_limit,5)
        if scope_trial and scope_phase == 'raised_descent':
            speed_limit=min(speed_limit,5)
        if type(speed) not in (int,float) or not math.isfinite(speed) or not 0<speed<=speed_limit:
            raise TransferError(f'Queued replay speed must be greater than zero and at most {speed_limit} mm/s for this route.')
        if reviewed and grouped:
            raise TransferError('An explicitly reviewed route must execute its exact points without regrouping.')
        if vertical_runs and not reviewed:
            raise TransferError('Long vertical segments require a separately reviewed route.')
        points, expected = prepare_points(start,joints,points,cfg,reviewed=reviewed,vertical_runs=vertical_runs,straight_transfer=straight_transfer,level_return=level_return,forward_entry=forward_entry,reverse_entry=reverse_entry,home_transit=home_transit,scope_compact=scope_compact,hamilton_home=hamilton_home,scope_phase=scope_phase,hamilton_trial=hamilton_trial,scope_trial=scope_trial)
        if hamilton_home:
            from hamilton_true_home import check_route
            check_route(start,points,joints,cfg,self.service.envelope)
        if hamilton_trial:
            from hamilton_reteach_trial import check_route
            check_route(start,points,joints,cfg,self.service.envelope)
        if scope_trial:
            from squid_48well_endpoint_trial import check_route
            check_route(start,points,joints,cfg,self.service.envelope,scope_phase)
        reference_points = points
        grouping = None
        if reviewed:
            run.say(f'Executing {len(points)} explicitly approved points; 2 mm / 2 degree monitoring is relative to this reviewed route.')
        if grouped:
            from trajectory_smoothing import group_points
            points,expected,grouping = group_points(start,joints,points,cfg)
            run.say(f"Grouped {grouping['input_points']} taught points into {grouping['output_points']} MoveL commands; "
                    f"maximum planned change {grouping['max_position_error_mm']:.3f} mm / {grouping['max_yaw_error_deg']:.3f} deg. "
                    'Controller zone stays -1; monitoring uses the original recorded path.')
        def locked():
            capability=self.capability()
            blocker=travel_program_blocker(capability, speed=0)
            if blocker:
                raise TransferError(blocker)
            protocol=capability['version']
            if speed>capability['max_speed_mm_s']:
                required=220108 if speed>130 else 220107 if speed>100 else 220106 if speed>80 else 220105 if speed>70 else 220104 if speed>55 else 220103 if speed>47 else 220102
                raise TransferError(f'Publish Lua queue version {required} before running speed {speed}; no motion sent.')
            token = secrets.randbelow(1073741823)+1
            def healthy():
                if run.stopped(): raise TransferError('Queued replay stopped by operator.')
                refusal = self.service._preflight()
                if refusal: raise TransferError(refusal)
                q = self.service.joints() or {}
                values = [q.get(k) for k in ('J1','J2','J3','J4')]
                if any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
                    raise TransferError('Joint feedback is unavailable.')
                if abs(q['J2'])>abs(cfg['j2_min_deg'])-cfg['j2_margin_deg'] or abs(q['J4'])>min(cfg['j4_pref_abs_deg'],cfg['j4_hard_abs_deg']-5):
                    raise TransferError('Measured joints exceed automatic limits.')
            def at_start():
                ensure_arrival(self.service.pose_mm(),start)
                current = self.service.joints() or {}
                if any(abs(current[k]-joints[k])>.5 for k in joints if k in ('J1','J2','J3','J4')):
                    raise TransferError('Joint configuration changed during upload.')
            healthy()
            at_start()
            begun = False
            try:
                begun = True # a timeout after writing BEGIN is uncertain; stop, never resend
                reply = self.service.robot.set_sys_var_i({0:22,1:1,2:0,3:0,4:6,5:0,6:0},reply_timeout=10)
                if reply != {'index':1,'value':protocol}:
                    raise TransferError('Lua queue handshake failed; no trajectory uploaded or executed.')
                header = [len(points),speed,-1]+[start[k] for k in KEYS]+[joints[k] for k in ('J1','J2','J3','J4')]
                self._job(1,token,dict(enumerate(header)))
                for offset in range(0,len(points),3):
                    healthy()
                    batch = points[offset:offset+3]
                    self._job(2,token,dict(enumerate(v for p in batch for v in (p[k] for k in KEYS))),offset,len(batch))
                    progress('upload',offset+len(batch),len(points))
                self._job(3,token,offset=checksum(points))
                values = self.service.robot.get_sys_var_i([7,17,18,19])
                if values != {7:token,17:protocol,18:2,19:len(points)}:
                    raise TransferError('Controller did not confirm the complete committed trajectory.')
                healthy()
                at_start()
                done, outcome = threading.Event(), {}
                path = [start]+reference_points
                length = sum(math.dist([a[k] for k in KEYS[:3]],[b[k] for k in KEYS[:3]]) for a,b in zip(path,path[1:]))
                timeout = 300+2*len(points)+4*length/speed
                def execute_job():
                    try: self._job(4,token,timeout=timeout)
                    except Exception as error: outcome['error'] = error
                    finally: done.set()
                # Start dispatch and Stop are serialized by the service motion lock;
                # the API Stop only sets run's event. This loop sends remoteStop.
                thread = threading.Thread(target=execute_job,daemon=True,name='lua-trajectory-reply')
                healthy()
                thread.start()
                deadline = time.monotonic()+timeout
                while not done.wait(.1):
                    healthy()
                    measured = self.service.pose_mm()
                    d,yaw,percent = locate(measured,path)
                    if d>2 or yaw>2:
                        raise TransferError(f'Measured arm pose left the taught trajectory corridor: position error {d:.4f} mm, yaw error {yaw:.4f} deg, pose {measured}.')
                    progress('motion',min(percent,99),100)
                    if time.monotonic()>deadline:
                        raise TransferError('Trajectory timed out; physical state requires review.')
                if 'error' in outcome: raise outcome['error']
                healthy()
                values = self.service.robot.get_sys_var_i([7,17,18,19])
                if values != {7:token,17:protocol,18:4,19:len(points)}:
                    raise TransferError('Lua trajectory completion was not confirmed.')
                ensure_arrival(self.service.pose_mm(),points[-1])
                q = self.service.joints() or {}
                if any(abs(q[k]-expected[k])>.5 for k in ('J2','J3','J4')):
                    raise TransferError('Final queued trajectory joint configuration mismatch.')
                progress('motion',100,100)
                return dict(ok=True,executor='lua_queue',points=len(points),zone=-1,endpoint=points[-1],grouping=grouping)
            except Exception as error:
                if begun:
                    try: self.stop_controller()
                    except Exception as stop_error:
                        self.service.trajectory_fault = True
                        raise TransferError(f'{error}; {stop_error}') from error
                raise
        return self.service._locked(locked)
