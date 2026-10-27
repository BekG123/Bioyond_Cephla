"""Explicit hand-guiding for the S4 BRC 1.8 controller (no Lua program start).

Protocol provenance and firmware limits: DRAGGO.md. Every RPC uses a fresh
socket: this firmware returns sequence zero, so there is exactly one request
per connection and no ambiguous late replies or automatic command retries.
"""
import json
import logging
import math
from pathlib import Path
import socket
import struct
import threading
import time

from researcher_teaching import TeachingError


class DragGoRPC:
    PORT = 20202
    FIRMWARE = '1.8.2504101654'

    def __init__(self, host):
        self.host = host

    def call(self, command, payload=b''):
        with socket.create_connection((self.host, self.PORT), timeout=2) as sock:
            sock.settimeout(2)
            sock.sendall(struct.pack('<iii4B', 16 + len(payload), 1, command, 0, 0, 0, 0) + payload)

            def read(size):
                data = bytearray()
                while len(data) < size:
                    part = sock.recv(size - len(data))
                    if not part:
                        raise ConnectionError('DragGo connection closed before reply')
                    data.extend(part)
                return bytes(data)

            size, seq, cmd, response, r1, r2, r3 = struct.unpack('<iii4B', read(16))
            if not 16 <= size <= 33808 or seq not in (0, 1) or cmd != command or response != 1 or any((r1, r2, r3)):
                raise ValueError(f'Unsupported DragGo reply: command={command}, size={size}, sequence={seq}, reply_command={cmd}, response={response}, reserved={(r1, r2, r3)}')
            return read(size - 16)

    def info(self):
        data = self.call(10, struct.pack('<i', 1))
        # Native Pack=4 structure. autoStop at 728, padding 729..731,
        # errorCount at 732, isDragGoEn at 736. Do not use packed offsets.
        if len(data) != 740:
            raise ValueError('Unsupported motion status layout')
        device, version, model = [data[i:i+32].split(b'\0')[0].decode('ascii') for i in (0, 32, 64)]
        mode, emergency, state, dof, ext_dof, moving = data[98:104]
        drag = struct.unpack_from('<i', data, 736)[0]
        if (device != 'BRC-full' or version != self.FIRMWARE or not model.startswith('S4-') or
                # Vendor RobMotionState: Error=0, Disable=1, Paused=2,
                # Ready=3, Move=4, Stop=5, DragGo=6, PlayRd=7, StopRd=8.
                mode not in (0, 1) or emergency not in (0, 1) or state not in range(9) or
                dof != 4 or ext_dof > 8 or moving not in (0, 1) or drag not in (0, 1)):
            raise ValueError('Unsupported controller firmware or status')
        # Vendor MotionGetInfo_resp (Pack=4): extJoint float[8] at 336,
        # extJointType byte[8] at 368. SDK converts linear metres to mm
        # and rotary radians to degrees; type 1 is linear.
        external, units = {}, {}
        for i in range(ext_dof):
            value = struct.unpack_from('<f', data, 336 + 4*i)[0]
            kind = data[368+i]
            if not math.isfinite(value) or kind not in (0, 1):
                raise ValueError('Invalid external joint feedback')
            key = f'E{i+1}'
            external[key] = value * 1000 if kind == 1 else math.degrees(value)
            units[key] = 'mm' if kind == 1 else 'degrees'
        return dict(manual=mode == 0, enabled=state > 1, disabled=state == 1,
                    moving=bool(moving), emergency=bool(emergency), drag=bool(drag),
                    error=state == 0 or bool(struct.unpack_from('<I', data, 592)[0]),
                    firmware=version, external_axes=external, external_units=units)

    def write_di(self, pin, value):
        answer = self.call(58, struct.pack('<ii', pin, value))
        if not answer or answer[0] != value:
            raise ValueError('Controller did not acknowledge mode/enable change')

    def set_drag(self, enabled):
        answer = self.call(137, struct.pack('<ii', 1, int(enabled)))
        if not answer or answer[0] != 1:
            raise ValueError('Controller did not acknowledge DragGo change')

    def disable(self, info):
        if info['disabled']:
            return  # Matches vendor Control_SetEnable's already-disabled case.
        if info['manual']:
            self.write_di(2, 0)
            time.sleep(.8)  # Vendor manual-enable falling-edge delay.
        else:
            # This firmware rejects native command 136 (response=0). Auto
            # disable must use the console's shared remoteDisable connection.
            raise RuntimeError('Auto disable requires the shared robot service')


class DragGo:
    def __init__(self, get_service, latch_path, rpc_factory=DragGoRPC):
        self.get_service = get_service
        self.path = Path(latch_path)
        self.rpc_factory = rpc_factory
        self.lock = threading.RLock()
        self.command_lock = threading.Lock()
        self.cancelled = threading.Event()
        # A crashed/interrupted transition must not unlock developer motion.
        self.latched = self.path.exists()
        self.message = ''

    @property
    def blocks_motion(self):
        return self.latched

    def cancel(self):
        """Fence an in-flight transition before an external disable/stop."""
        self.cancelled.set()
        with self.command_lock:
            pass

    def _command(self, enable, function, *args):
        with self.command_lock:
            if enable and self.cancelled.is_set():
                raise RuntimeError('Hand-guiding start cancelled by stop/disable')
            return function(*args)

    def _latch(self, value):
        if value:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({'hand_guiding_requires_exit': True}), encoding='utf-8')
            self.latched = True
        else:
            self.path.unlink(missing_ok=True)
            self.latched = False

    def _rpc(self):
        service = self.get_service()
        if not service.robot.connected:
            raise TeachingError('Robot disconnected. Connect the robot before using hand-guiding.')
        host, _port = service._endpoint_addr()
        return self.rpc_factory(host)

    def _disable(self, rpc, info):
        if info['disabled'] or info['manual']:
            return rpc.disable(info)
        service = self.get_service()
        # remoteDisable is Auto-only; never send it in Manual/DragGo.
        if service.robot.get_ctrl_mode().get('mode') != 'auto':
            raise RuntimeError('Controller mode changed before Auto disable; no command sent')
        result = service.set_enable(False, confirmed=True)
        if not result.get('ok'):
            raise RuntimeError('Auto disable failed: ' + str(result.get('error', 'no acknowledgement')))

    def public(self, robot):
        base = dict(active=False, can_start=False, can_end=False, blocked=self.latched)
        if not robot.get('connected'):
            return dict(base, state='unknown' if self.latched else 'disconnected',
                        message='Robot disconnected. Reconnect to check hand-guiding.' if self.latched else 'Connect the robot to use hand-guiding.')
        # Status polling owns this same lock. Contention alone does not prove
        # a mode transition: wait for a bounded read and obtain fresh feedback.
        if not self.lock.acquire(timeout=2.5):
            return dict(base, state='checking',
                        message='Hand-guiding status is busy. Wait for the check to finish.')
        try:
            info = self._rpc().info()
            if info['drag'] and not self.latched:
                self._latch(True)
            active = info['drag'] and info['manual'] and info['enabled'] and not info['emergency'] and not info['error']
            ready = (robot.get('ok') and not robot.get('errors') and
                     robot.get('program_state', {}).get('state') in ('stopped', 'running', 'paused') and
                     not info['moving'] and not info['error'] and not info['emergency'])
            message = ('Hand-guiding is active. Guide gently; hold still for each capture.' if active else
                       'Hand-guiding needs to be ended before other arm controls can be used.' if self.latched else
                       'Ready. Start will stop the idle controller program, then enable hand-guiding. Keep the arm supported.' if ready and robot.get('program_state', {}).get('state') != 'stopped' else
                       'Ready to start hand-guiding.' if ready else
                       'Wait for the arm to stop and resolve any controller alert before hand-guiding.')
            return dict(active=active, can_start=bool(ready and not self.latched),
                        can_end=self.latched or info['drag'], blocked=self.latched,
                        state='active' if active else 'needs_exit' if self.latched else 'off',
                        message=self.message or message)
        except Exception:
            logging.exception('DragGo status unavailable')
            return dict(base, can_end=self.latched, state='unknown',
                        message='Hand-guiding status unavailable. Keep the arm supported; check the connection. Do not force a resisting joint.')
        finally:
            self.lock.release()

    @staticmethod
    def _wait(rpc, predicate):
        deadline = time.monotonic() + 4
        while True:
            info = rpc.info()
            if predicate(info):
                return info
            if time.monotonic() >= deadline:
                raise TimeoutError('Controller did not reach the requested hand-guiding state')
            time.sleep(.15)

    def change(self, enable, ready=False):
        if enable and ready is not True:
            raise TeachingError('Confirm the arm is supported, the gripper is empty, the area is clear, and the E-stop is supervised.', 400)
        service = self.get_service()
        # A read-only status poll briefly holds this lock too. Wait for that
        # bounded read instead of misreporting a concurrent mode change.
        if not self.lock.acquire(timeout=4.5):
            raise TeachingError('A hand-guiding status check or mode change is still in progress. Wait for confirmation.')
        motion_locked = False
        mutated = False
        try:
            self.cancelled.clear()
            motion_locked = service._motion.acquire(timeout=.5)
            if not motion_locked:
                raise TeachingError('The arm controls are busy. Wait for the current action to finish.')
            rpc = self._rpc()
            robot = service.status()
            if enable:
                if self.latched:
                    raise TeachingError('End the existing hand-guiding session before starting another.')
                if (not robot.get('connected') or not robot.get('ok') or robot.get('errors') or
                        robot.get('program_state', {}).get('state') not in ('stopped', 'running', 'paused')):
                    raise TeachingError('Resolve controller alerts or unavailable program status before hand-guiding.')
            info = rpc.info()
            if enable and (info['moving'] or info['error'] or info['emergency']):
                raise TeachingError('The robot must be stopped and free of controller alerts before hand-guiding.')
            self._latch(True)
            mutated = True
            self.message = ''
            if enable and robot['program_state']['state'] != 'stopped':
                # Explicit supported-arm Start owns dispatch + motion locks.
                # Stop only; never resume/restart Lua or reset the gripper.
                result = self._command(enable, service.program, 'stop')
                if not result.get('ok'):
                    raise RuntimeError('Controller program stop failed: ' + str(result.get('error')))
                deadline = time.monotonic() + 4
                while True:
                    if self.cancelled.is_set():
                        raise RuntimeError('Hand-guiding start cancelled while stopping the program')
                    robot = service.status()
                    info = rpc.info()
                    if (not robot.get('connected') or not robot.get('ok') or robot.get('errors') or
                            info['error'] or info['emergency'] or info['moving']):
                        raise RuntimeError('Controller became unavailable, moving, or faulted during program stop')
                    if robot.get('program_state', {}).get('state') == 'stopped':
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Controller did not confirm program stopped; no Manual/DragGo enable sent')
                    time.sleep(.1)
            self._command(enable, self._disable, rpc, info)
            info = self._wait(rpc, lambda s: s['disabled'])
            if enable and not info['manual']:
                self._command(enable, rpc.write_di, 1, 0)
                self._wait(rpc, lambda s: s['manual'] and s['disabled'])
            # Re-read after mode changes; an already-off exit needs no toggle.
            if rpc.info()['drag'] != enable:
                self._command(enable, rpc.set_drag, enable)
            self._wait(rpc, lambda s: s['drag'] == enable and s['disabled'])
            if enable:
                # Exactly the vendor Manual-enable sequence; no program start,
                # gripper command, brake release, reset, or automatic replay.
                self._command(enable, rpc.write_di, 2, 0)
                time.sleep(.8)
                self._command(enable, rpc.write_di, 2, 1)
                self._wait(rpc, lambda s: s['manual'] and s['drag'] and s['enabled'] and not s['error'] and not s['emergency'])
                return dict(ok=True, message='Hand-guiding is active. Guide gently and hold still before capturing.')
            self._latch(False)
            return dict(ok=True, message='Hand-guiding ended. Servos are disabled; support the arm. No automatic movement was started.')
        except TeachingError:
            raise
        except Exception:
            logging.exception('DragGo transition failed')
            if mutated:
                # A disable is a separate fail-safe action, never a retry of an
                # uncertain enable command. The latch remains until explicit exit.
                try:
                    self._disable(rpc, rpc.info())
                except Exception:
                    logging.exception('DragGo failure disable could not be confirmed')
                self.message = 'Hand-guiding change was not confirmed. Keep the arm supported and choose End hand-guiding. Use the physical E-stop if movement is unsafe.'
            raise TeachingError(self.message or 'Hand-guiding is unavailable. Check the robot connection or ask your developer to check controller compatibility.', 503)
        finally:
            if motion_locked:
                service._motion.release()
            self.lock.release()
