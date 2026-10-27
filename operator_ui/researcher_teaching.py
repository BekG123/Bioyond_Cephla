"""Durable measured waypoints, not continuous trajectories. No motion commands.

The Flask dispatch lock excludes manual moves and sequences during captures.
Draft revisions prevent duplicate/stale updates; atomic writes preserve data.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
from uuid import uuid4

PLATE_WORKFLOW = ['Home', 'Calibrate', 'Align', 'Descend', 'Grip', 'Hamilton']
PLATE_LIMITATIONS = ['Discrete positions and stage results; continuous travel is not recorded.',
                    'Manual Descend/Grip are operator-reported observations, not executable commands or verified grasp success.',
                    'No images are captured by manual record buttons. Playback is not implemented.']


def next_station(draft):
    completed = [p['station'] for p in draft['waypoints'] if p['station'] != 'Waypoint']
    workflow = draft.get('workflow', ['Home', 'Hamilton'])
    return workflow[len(completed)] if len(completed) < len(workflow) else None


class TeachingError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def numbers(values, keys):
    if not isinstance(values, dict):
        raise TeachingError('Position could not be read. Check the robot connection and try again.')
    result = {}
    for key in keys:
        value = values.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise TeachingError('Position could not be read. Check the robot connection and try again.')
        result[key] = float(value)
    return result


class StationTeaching:
    @staticmethod
    def _gripper(service):
        try:
            return numbers(service.external_axes(), ('E1',))
        except Exception as ex:
            raise TeachingError('Gripper position could not be read. Nothing was saved. Check the controller connection in Developer view, then retry.') from ex

    def __init__(self, path, get_service, settle_seconds=.25):
        self.path = Path(path)
        self.get_service = get_service
        self.settle_seconds = settle_seconds
        self.lock = threading.RLock()

    def _load(self):
        if not self.path.exists():
            return dict(schema='cephla.teaching-store.v1', draft=None, routines=[])
        with self.path.open(encoding='utf-8') as handle:
            data = json.load(handle)
        if data.get('schema') != 'cephla.teaching-store.v1' or not isinstance(data.get('routines'), list):
            raise TeachingError('Saved teaching data needs developer attention. It has not been overwritten.', 503)
        return data

    def _store(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix='.teaching-', suffix='.tmp', delete=False) as handle:
                temporary = handle.name
                json.dump(data, handle, indent=2, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _summary(routine):
        if routine is None:
            return None
        return dict(id=routine['id'], revision=routine['revision'], name=routine['name'],
                    workflow=routine.get('workflow', ['Home', 'Hamilton']), next_station=next_station(routine),
                    created_at=routine['created_at'], saved_at=routine.get('saved_at'),
                    capture_kind=routine['capture_kind'], reviewed=routine.get('reviewed', False),
                    complete=bool(routine['waypoints'] and routine['waypoints'][-1]['station'] == 'Hamilton'),
                    waypoints=[dict(station=p['station'], label=p['label'], captured_at=p['captured_at'], kind=p.get('kind', 'position'))
                               for p in routine['waypoints']], executable=False)

    def public(self):
        with self.lock:
            data = self._load()
            return dict(draft=self._summary(data['draft']),
                        routines=[self._summary(r) for r in reversed(data['routines'])])

    def _draft(self, data, body):
        draft = data['draft']
        if (not draft or body.get('draft_id') != draft['id'] or
                type(body.get('revision')) is not int or body['revision'] != draft['revision']):
            raise TeachingError('This draft changed in another window. Refresh before continuing.')
        return draft

    def start(self, body):
        name = body.get('name')
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise TeachingError('Give your routine a name of 1–80 characters.', 400)
        with self.lock:
            data = self._load()
            if data['draft']:
                raise TeachingError('A teaching draft is already open. Continue it or discard it first.')
            data['draft'] = dict(id=uuid4().hex, revision=0, name=name.strip(), created_at=utc_now(),
                schema='cephla.station-demo.v1', capture_kind='measured_station_waypoints',
                workflow=['Home', 'Hamilton'], frame=dict(tool='T0', user='U0'),
                units=dict(position='mm', orientation='degrees', joints=dict(J1='mm', J2='degrees', J3='degrees', J4='degrees')),
                limitations=['Discrete samples only; travel between points is not recorded.',
                             'No camera frames, gripper actions, or continuous trajectory.',
                             'Review is not motion validation; physical playback is not implemented.'],
                waypoints=[], reviewed=False, execution=dict(ready=False, reason='playback_not_implemented'))
            if body.get('workflow') == 'plate_pick_hamilton':
                data['draft']['workflow'] = PLATE_WORKFLOW.copy()
                data['draft']['capture_kind'] = 'positions_and_observed_actions'
                data['draft']['limitations'] = PLATE_LIMITATIONS.copy()
            self._store(data)
            return self.public()

    def capture(self, body):
        with self.lock:
            data = self._load()
            draft = self._draft(data, body)
            points = draft['waypoints']
            station = body.get('station')
            plate_flow = draft.get('workflow') == PLATE_WORKFLOW
            if plate_flow:
                expected = next_station(draft)
                if station in ('Calibrate', 'Align') or (station != 'Waypoint' and station != expected):
                    raise TeachingError('Complete the highlighted workflow step first.')
                if station == 'Waypoint' and expected != 'Hamilton':
                    raise TeachingError('Intermediate route points are recorded after Grip and before Hamilton.')
                if station in ('Descend', 'Grip') and body.get('performed') is not True:
                    raise TeachingError('Confirm you performed this action manually before recording it.', 400)
            if not points and station != 'Home':
                raise TeachingError('Capture Home first.')
            if not plate_flow and points and (points[-1]['station'] == 'Hamilton' or station not in {'Waypoint', 'Hamilton'}):
                raise TeachingError('Capture an intermediate point or Hamilton next, or undo the last capture.')
            if len(points) >= 100:
                raise TeachingError('This draft has too many intermediate points. Review it with your developer.')
            service = self.get_service()
            state = service.status()
            if not state.get('connected'):
                raise TeachingError('Robot disconnected. Connect the robot before capturing a position.')
            if not state.get('ok') or state.get('errors'):
                raise TeachingError('Robot needs attention. Ask your developer to check its status before capturing.')
            began = time.monotonic()
            first_external = None
            if plate_flow and station in ('Descend', 'Grip'):
                first_external = self._gripper(service)
            first_pose = numbers(service.pose_mm(), ('X', 'Y', 'Z', 'Rz'))
            first_joints = numbers(service.joints(), ('J1', 'J2', 'J3', 'J4'))
            time.sleep(self.settle_seconds)
            pose = numbers(service.pose_mm(), ('X', 'Y', 'Z', 'Rz'))
            joints = numbers(service.joints(), ('J1', 'J2', 'J3', 'J4'))
            duration = time.monotonic() - began
            yaw_delta = abs((pose['Rz'] - first_pose['Rz'] + 180) % 360 - 180)
            if (duration > 3 or yaw_delta > .2 or any(abs(pose[k] - first_pose[k]) > .3 for k in ('X', 'Y', 'Z')) or
                    any(abs(joints[k] - first_joints[k]) > (.3 if k == 'J1' else .2) for k in joints)):
                raise TeachingError('The arm moved or the position read was too slow. Let it settle, then capture again.')
            final_state = service.status()
            if not final_state.get('connected') or not final_state.get('ok') or final_state.get('errors'):
                raise TeachingError('Robot status changed during capture. Nothing was saved; check the connection and try again.')
            label = station if station != 'Waypoint' else f'Intermediate point {sum(p["station"] == "Waypoint" for p in points) + 1}'
            external = None
            if plate_flow and station in ('Descend', 'Grip'):
                external = self._gripper(service)
                if abs(external['E1'] - first_external['E1']) > .001:
                    raise TeachingError('The gripper is still moving. Let it settle before recording this action.')
            duration = time.monotonic() - began
            if duration > 3:
                raise TeachingError('Position reads were too slow. Nothing was saved; let the arm settle and retry.')
            points.append(dict(station=station, label=label, captured_at=utc_now(), pose_mm=pose,
                               joints=joints, source='robot_controller', endpoint=state.get('endpoint'),
                               read_window_seconds=round(duration, 4), gripper=external, images=[],
                               gripper_units={'E1': 'mm'} if external is not None else None,
                               gripper_source='native_motion_status' if external is not None else None,
                               kind='manual_action' if station in ('Descend', 'Grip') else 'position',
                               operator_reported=station in ('Descend', 'Grip'),
                               command=None, grip_verified=False))
            draft['revision'] += 1
            self._store(data)
            return self.public()

    def edit(self, action, body):
        with self.lock:
            data = self._load()
            draft = self._draft(data, body)
            if action == 'undo':
                if not draft['waypoints']:
                    raise TeachingError('There is no captured position to undo.')
                draft['waypoints'].pop()
                draft['revision'] += 1
            elif action == 'discard':
                data['draft'] = None
            elif action == 'save':
                if not draft['waypoints'] or draft['waypoints'][-1]['station'] != 'Hamilton':
                    raise TeachingError('Capture Home and Hamilton before saving the routine.')
                if body.get('reviewed') is not True:
                    raise TeachingError('Review the captured stations and check the review box before saving.', 400)
                draft['saved_at'] = utc_now()
                draft['reviewed'] = True
                draft['revision'] += 1
                data['routines'].append(draft)
                data['draft'] = None
            else:
                raise TeachingError('This action is not available.', 404)
            self._store(data)
            return self.public()

    def export(self, ident):
        with self.lock:
            for routine in self._load()['routines']:
                if routine['id'] == ident:
                    return deepcopy(routine)
            raise TeachingError('That saved routine could not be found.', 404)
