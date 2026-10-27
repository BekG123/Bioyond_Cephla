"""External acquisition lifecycle: scan-area entry and verified cleanup.

No shipped Squid files are changed. No retries, resets, or limit overrides.
"""
from copy import deepcopy
import hashlib
import math
import threading

import yaml

AXES=('x_mm','y_mm','z_mm')


def imaging_target(text, limits):
    """Use an actual field in the confirmed acquisition, never loading XY."""
    data=yaml.safe_load(text)
    if not isinstance(data,dict):raise ValueError('Invalid saved acquisition settings.')
    kind=data.get('acquisition',{}).get('widget_type')
    section={'wellplate':'wellplate_scan','flexible':'flexible_scan'}.get(kind)
    regions=data.get(section,{}).get('regions' if kind=='wellplate' else 'positions',[]) if section else []
    fields=[]
    for region in regions:
        for field in region.get('fovs',[]):
            if not isinstance(field,list) or len(field) not in (2,3):
                raise ValueError('Invalid saved imaging field.')
            z=field[2] if len(field)==3 else (data.get('z_stack',{}).get('z_range_mm') or [None])[0]
            point=dict(zip(AXES,[field[0],field[1],z]))
            for axis,value in point.items():
                if (type(value) not in (int,float) or not math.isfinite(value)
                        or not limits[axis][0]<=value<=limits[axis][1]):
                    raise ValueError('Saved imaging site is outside Squid scanning limits: '+axis)
            fields.append(point)
    if not fields:raise ValueError('The saved acquisition has no imaging fields.')
    return fields[0]


def install(server):
    if getattr(server,'_lacry_lifecycle',None) is not None:return
    controller=server.multipoint_controller
    if controller is None:raise RuntimeError('Acquisition controller is required.')
    stage=server.microscope.stage
    lock=threading.RLock()
    gate={'version':1,'status':'idle','experiment_id':None,'error':''}
    server._lacry_lifecycle=gate
    original_run=controller.run_acquisition
    original_finish=controller._on_acquisition_completed
    original_status=server._cmd_get_acquisition_status
    original_reference=server._commands['get_stage_reference']

    def pos():
        p=stage.get_pos()
        return {axis:getattr(p,axis) for axis in AXES}

    def within(actual,target):
        return all(abs(actual[k]-target[k])<=.02 for k in AXES)

    def run(*args,**kwargs):
        with lock:
            if gate['status'] in ('pending','running','failed'):
                raise RuntimeError('Squid acquisition cleanup is unfinished or failed; operator review is required.')
            gate.update(status='pending',experiment_id=controller.experiment_ID,
                        return_position=pos(),error='')
        try:
            result=original_run(*args,**kwargs)
            if result is not True:raise RuntimeError('Squid did not start acquisition.')
            return result
        except Exception as error:
            with lock:gate.update(status='failed',error=str(error))
            raise

    def finish(*args,**kwargs):
        with lock:gate['status']='running'
        try:
            result=original_finish(*args,**kwargs)
            actual=pos()
            if not within(actual,gate['return_position']):
                raise RuntimeError('Squid cleanup did not reach its acquisition starting position.')
            with lock:gate.update(status='completed',position=actual)
            return result
        except Exception as error:
            with lock:gate.update(status='failed',error=str(error))
            raise

    def status():
        result=original_status()
        with lock:cleanup=deepcopy(gate)
        result['cleanup']=cleanup
        if cleanup['status'] in ('pending','running'):result['in_progress']=True
        return result

    def reference():
        return dict(original_reference(),imaging_lifecycle_version=1)

    def prepare(settings_yaml,settings_sha256,reference_hash):
        from control import _def as config
        from squid.stage.utils import move_to_scanning_position
        if hashlib.sha256(settings_yaml.encode()).hexdigest()!=settings_sha256:
            raise ValueError('Confirmed imaging settings checksum changed.')
        info=reference()
        if info['reference_hash']!=reference_hash:raise ValueError('Loading reference changed.')
        if status()['in_progress'] or gate['status']=='failed':
            raise RuntimeError('Squid is busy or its acquisition cleanup failed. No scan-entry move started.')
        if not within(pos(),info['dropoff']):raise ValueError('Squid must be at its verified loading position before scan entry.')
        target=imaging_target(settings_yaml,info['scan_limits'])
        # Native transition engages the holder using the configured scan entry;
        # validate that entry too, rather than changing its limits or geometry.
        for axis,value in (('x_mm',config.SLIDE_POSITION.SCANNING_X_MM),
                           ('y_mm',config.SLIDE_POSITION.SCANNING_Y_MM)):
            if not info['scan_limits'][axis][0]<=value<=info['scan_limits'][axis][1]:
                raise ValueError('Configured Squid scanning entry is outside scanning limits.')
        move_to_scanning_position(stage,blocking=True,is_wellplate=True)
        stage.move_x_to(target['x_mm'],blocking=True)
        stage.move_y_to(target['y_mm'],blocking=True)
        stage.move_z_to(target['z_mm'],blocking=True)
        actual=pos()
        if not within(actual,target):raise RuntimeError('Squid scan-entry feedback does not match the saved imaging site.')
        return dict(ok=True,position=actual,target=target,settings_sha256=settings_sha256)

    controller.run_acquisition=run
    controller._on_acquisition_completed=finish
    server._cmd_get_acquisition_status=status
    server._commands['get_acquisition_status']=status
    server._commands['get_stage_reference']=reference
    server._commands['prepare_confirmed_imaging']=prepare
