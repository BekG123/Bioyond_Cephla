"""Fresh E2 gate before calibration motion; never substitutes cached telemetry."""
import math
import time

TARGET_DEGREES = 1.77
PRECAL_TOLERANCE_DEGREES = 0.05


def accepted(value):
    # Operator accepted the displayed 1.769-degree reading (three decimals).
    return math.isfinite(value) and round(value, 3) >= 1.769 and value <= 1.82


def verify(service, run, read=None, sleep=time.sleep, correct=False):
    from draggo import DragGoRPC
    if read is None:
        if not service.robot.connected:
            raise RuntimeError('Connect the robot before checking E2.')
        read = DragGoRPC(service._endpoint_addr()[0]).info
    values = []
    corrected = False
    while len(values) < 3:
        if run.stopped():
            raise RuntimeError('E2 verification cancelled.')
        info = read()
        if any(info.get(key, True) for key in ('error', 'emergency', 'moving', 'drag')):
            raise RuntimeError('E2 check requires a stationary, healthy controller.')
        value = info.get('external_axes', {}).get('E2')
        if (info.get('external_units', {}).get('E2') != 'degrees'
                or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise RuntimeError('Fresh E2 angular feedback unavailable; calibration blocked.')
        run.audit('calibration_e2_readback', target_degrees=TARGET_DEGREES,
                  actual_degrees=value, tolerance_degrees=PRECAL_TOLERANCE_DEGREES)
        if not accepted(value):
            if not correct or corrected:
                raise RuntimeError(f'E2 is {value:.6f} degrees; calibration requires a displayed minimum of 1.769 and maximum of 1.82 degrees.')
            run.say('Positioning E2 at 1.77 degrees before calibration.')
            result = service.position_calibration_e2()
            run.audit('calibration_e2_correction', result=result)
            if not result.get('ok'):
                raise RuntimeError(result.get('error', 'E2 correction failed; calibration blocked.'))
            corrected = True
            values.clear()
            continue
        values.append(value)
        if len(values) < 3:
            sleep(0.1)
    run.say(f'E2 verified at {values[-1]:.3f} degrees (target 1.77).')
    return values
