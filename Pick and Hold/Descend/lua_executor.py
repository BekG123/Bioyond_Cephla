"""Candidate controller-local descent. No hardware on import; no automatic grip.

Invoked explicitly by the Developer Lua Descend button. Existing descent and
researcher reference gates stay intact until this candidate is commissioned.
"""
import math
import secrets
import threading
import time

from autonomy import TransferError, check_path, ensure_arrival, wrap, GuardedService
from trajectory_queue import LuaTrajectory

VERSION = 230101
APPROACH_SPEED = 137
PROBE_SPEED = 5
SLOW_ZONE = 20
KEYS = ('X', 'Y', 'Z', 'Rz')
REASONS = {1: 'invalid or already consumed descent request',
           2: 'start pose or joints changed', 3: 'missing or unstable torque feedback',
           4: 'claw opening is insufficient or changed', 5: 'motion arrival mismatch',
           **{10+i: f'J{i} torque band breached; inspect before any retry' for i in range(1, 5)}}


def make_plan(start, joints, target, cfg, envelope, band):
    def finite(v):
        return type(v) in (int, float) and math.isfinite(v)
    if not all(finite(start.get(k)) for k in KEYS):
        raise TransferError('Live pose is unavailable.')
    if not all(finite(target.get(k)) for k in ('x', 'y', 'rz', 'z_calibrated')):
        raise TransferError('Finite calibrated XYZ and yaw are required.')
    if math.hypot(start['X']-target['x'], start['Y']-target['y']) > 1 or abs(wrap(start['Rz']-target['rz'])) > .5:
        raise TransferError('Align to the target before Lua descent.')
    end = {**start, 'Z': target['z_calibrated']}
    if not .5 <= start['Z']-end['Z'] <= 350:
        raise TransferError('Lua descent requires a downward drop of 0.5–350 mm; it never lifts.')
    if not finite(band) or not 25 <= band <= 1000:
        raise TransferError('Invalid configured torque band.')
    span = target.get('span_mm', cfg['claw_gap_max_mm']-.5)
    if not finite(span):
        raise TransferError('Invalid plate span.')
    required = span-cfg['claw_gap_min_mm']+.5
    maximum = cfg['claw_gap_max_mm']-cfg['claw_gap_min_mm']
    if not 0 <= required <= maximum <= 28:
        raise TransferError('Plate does not fit the configured open claw.')
    expected = check_path(start, end, joints, cfg, envelope)
    header = ([start[k] for k in KEYS] + [joints[k] for k in ('J1','J2','J3','J4')]
              + [end['Z'], APPROACH_SPEED, PROBE_SPEED, band, required,
                 *envelope['Z'], SLOW_ZONE, maximum])
    return dict(start=start, end=end, expected_joints=expected, header=header,
                required_e1=required, approach_z=min(start['Z'], end['Z']+SLOW_ZONE))


class LuaDescent:
    def __init__(self, service):
        self.service = service

    def execute(self, run, target, cfg, band):
        svc = self.service
        def locked():
            def healthy():
                if run.stopped():
                    raise TransferError('Lua descent stopped by operator.')
                if not svc.envelope_enabled:
                    raise TransferError('Lua descent requires the enabled workspace envelope.')
                refusal = svc._preflight()
                if refusal:
                    raise TransferError(refusal)
            healthy()
            start, joints = svc.pose_mm(), svc.joints() or {}
            plan = make_plan(start, joints, target, cfg, svc.envelope, band)
            robot = svc.robot
            # A live handshake is required; cached registers cannot grant capability.
            answer = robot.set_sys_var_i({0:23,1:1,2:0,3:0,4:6,5:0,6:0}, reply_timeout=10)
            if answer != {'index':1, 'value':VERSION}:
                raise TransferError('Publish controller/main_hostpoint_descent_137.bin before Lua descent; no motion sent.')
            token = secrets.randbelow(1073741823)+1
            robot.set_sys_para_f(dict(enumerate(plan['header'])))
            answer = robot.set_sys_var_i({0:23,1:1,2:token,3:0,4:1,5:0,6:0}, reply_timeout=10)
            if answer != {'index':1,'value':1} or robot.get_sys_var_i([7,8,9]) != {7:token,8:1,9:0}:
                raise TransferError('Lua descent preparation was not confirmed; no motion sent.')
            healthy()
            ensure_arrival(svc.pose_mm(), start)
            # Recheck the exact path against the current envelope before dispatch.
            make_plan(svc.pose_mm(), svc.joints() or {}, target, cfg, svc.envelope, band)
            run.say(f'Lua descent: approach at {APPROACH_SPEED} to Z {plan["approach_z"]:.2f}; '
                    f'last {SLOW_ZONE} mm at {PROBE_SPEED}, torque checked after each 1/0.5 mm step.')
            run.audit('lua_descent_plan', protocol=VERSION, token=token, plan=plan)
            done, outcome = threading.Event(), {}
            def dispatch():
                try:
                    outcome['reply'] = robot.set_sys_var_i(
                        {0:23,1:1,2:token,3:0,4:2,5:0,6:0}, reply_timeout=120)
                except Exception as error:
                    outcome['error'] = error
                finally:
                    done.set()
            thread = threading.Thread(target=dispatch, daemon=True, name='lua-descent-reply')
            began = False
            try:
                healthy()
                began = True
                thread.start()
                deadline, phase = time.monotonic()+120, None
                while not done.wait(.1):
                    healthy()
                    pose = svc.pose_mm()
                    if math.hypot(pose['X']-start['X'],pose['Y']-start['Y']) > 1 or abs(wrap(pose['Rz']-start['Rz'])) > .5 or not plan['end']['Z']-.2 <= pose['Z'] <= start['Z']+.2:
                        raise TransferError('Measured pose left the vertical descent corridor.')
                    check_path(pose, pose, svc.joints() or {}, cfg, svc.envelope)
                    values = robot.get_sys_var_i([7,8,9,13,14,15,16])
                    if values[7] != token:
                        raise TransferError('Descent transaction changed unexpectedly.')
                    run.audit('lua_descent_feedback', pose=pose, registers=values)
                    if values[8] != phase:
                        phase = values[8]
                        run.say('Lua descent: '+{2:'fast approach',3:'torque baseline',4:'slow probing',5:'target reached',-1:'stopped by guard'}.get(phase,'prepared'))
                    if values[8] == -1:
                        raise TransferError(REASONS.get(values[9], 'Lua descent refused.'))
                    if time.monotonic() > deadline:
                        raise TransferError('Lua descent timed out; no retry.')
                if 'error' in outcome:
                    raise outcome['error']
                values = robot.get_sys_var_i([7,8,9,13,14,15,16])
                run.audit('lua_descent_completion', registers=values, reply=outcome.get('reply'))
                if outcome.get('reply') != {'index':1,'value':1} or any(values[k] != v for k,v in {7:token,8:5,9:0}.items()):
                    raise TransferError(REASONS.get(values[9], 'Descent completion was not confirmed.'))
                healthy()
                ensure_arrival(svc.pose_mm(), plan['end'])
                current = svc.joints() or {}
                if any(abs(current[k]-plan['expected_joints'][k])>.5 for k in ('J2','J3','J4')):
                    raise TransferError('Final descent joint configuration mismatch.')
                run.say('Lua descent complete; claw remains open. No grip performed.', 'good')
                return dict(ok=True, breach=False, at_z=plan['end']['Z'], executor='lua_descent',
                            approach_speed=APPROACH_SPEED, probe_speed=PROBE_SPEED)
            except Exception:
                if began:
                    LuaTrajectory(svc).stop_controller()
                    thread.join(3)
                    if thread.is_alive():
                        svc.trajectory_fault = True
                        raise TransferError('Controller stopped but descent acknowledgement remains unresolved; inspect before resetting.')
                raise
        return svc._locked(locked)


def seq_descend_lua(run, service, target):
    from sequences import get_robot_params, band_floor, _abort
    if isinstance(service, GuardedService):
        if service.holding:
            return _abort(run, 'Lua plate descent requires an empty open claw.')
        service = service.service
    try:
        return LuaDescent(service).execute(run, target, get_robot_params(), band_floor())
    except Exception as error:
        return _abort(run, str(error))
