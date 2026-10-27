"""Narrow named loading extension; retain Squid's native clamp-clearance path."""
import hashlib
import json
from pathlib import Path
import threading

REFERENCE = Path(__file__).resolve().parents[1]/'squid_stage_reference.json'


def reference():
    data = json.loads(REFERENCE.read_text(encoding='utf-8-sig'))
    if data.get('operator_confirmed') is not True:
        raise ValueError('Squid loading reference needs operator review.')
    fingerprint = hashlib.sha256(json.dumps(data,sort_keys=True,allow_nan=False).encode()).hexdigest()
    return data, fingerprint


def install(server):
    import control._def as config
    from squid.stage.utils import move_to_loading_position
    lock = threading.Lock()

    def info():
        ref, fingerprint = reference()
        stage_config = server.microscope.stage.get_config()
        return dict(controller_serial=str(config.CONTROLLER_SN),
                    stage_simulated=bool(config.SIMULATE_MICROCONTROLLER),
                    reference_hash=fingerprint,dropoff=ref['dropoff'],
                    loading_route='Squid native loading path: retract objective, Y15, X35, loading Y, loading X, restore scanning limits, taught Z',
                    scan_limits={axis.lower()+'_mm':[getattr(stage_config,axis+'_AXIS').MIN_POSITION,
                         getattr(stage_config,axis+'_AXIS').MAX_POSITION] for axis in ('X','Y','Z')})

    def loading(reference_hash):
        if not lock.acquire(blocking=False):
            raise RuntimeError('A Squid loading move is already running.')
        try:
            ref, fingerprint = reference()
            if ref.get('motion_hold'):
                raise RuntimeError(ref['motion_hold'])
            if fingerprint != reference_hash:
                raise ValueError('Squid loading reference changed.')
            if config.SIMULATE_MICROCONTROLLER or str(config.CONTROLLER_SN) != ref['controller_serial']:
                raise ValueError('Physical Squid controller does not match the loading reference.')
            acquisition=server._cmd_get_acquisition_status()
            if acquisition.get('cleanup',{}).get('status')=='failed':
                raise RuntimeError('Squid acquisition cleanup failed. Operator review is required before loading movement.')
            if acquisition.get('in_progress') is not False:
                raise RuntimeError('Squid is scanning; loading movement refused.')
            stage = server.microscope.stage
            target = ref['dropoff']
            if ref['controller_serial'] == '12769210' and min(target['x_mm'],target['y_mm']) < 0:
                raise ValueError('Negative loading XY is not a repeatable target after this controller homes. Review an inward target; no motion sent.')
            stage_config = stage.get_config()
            if not stage_config.Z_AXIS.MIN_POSITION <= target['z_mm'] <= stage_config.Z_AXIS.MAX_POSITION:
                raise ValueError('Taught loading Z exceeds the configured focus travel.')
            # Native loading positions may intentionally lie outside scanning bounds.
            # Only this reviewed on-disk target is accepted, never caller XYZ.
            original = (config.SLIDE_POSITION.LOADING_X_MM,config.SLIDE_POSITION.LOADING_Y_MM)
            try:
                config.SLIDE_POSITION.LOADING_X_MM = target['x_mm']
                config.SLIDE_POSITION.LOADING_Y_MM = target['y_mm']
                move_to_loading_position(stage,blocking=True,is_wellplate=True)
            finally:
                config.SLIDE_POSITION.LOADING_X_MM,config.SLIDE_POSITION.LOADING_Y_MM = original
                # Native success path restores these; also restore on any failure.
                stage.set_limits(x_pos_mm=stage_config.X_AXIS.MAX_POSITION,x_neg_mm=stage_config.X_AXIS.MIN_POSITION,
                                 y_pos_mm=stage_config.Y_AXIS.MAX_POSITION,y_neg_mm=stage_config.Y_AXIS.MIN_POSITION)
            stage.move_z_to(target['z_mm'],blocking=True)
            actual = server._cmd_get_position()
            if any(abs(actual[k]-target[k])>.02 for k in ('x_mm','y_mm','z_mm')):
                raise RuntimeError(f'Squid loading feedback does not match the taught target. Target: {target}; measured: {actual}.')
            return dict(at_dropoff=True,position=actual)
        finally:
            lock.release()

    server._commands['get_stage_reference'] = info
    server._commands['return_to_recorded_dropoff'] = loading
