"""Fresh calibration followed by ten full real-camera cycles after relocation."""
import argparse
import json
import time
import full_calibration_handling_20261103 as calibration
import ten_real_imaging_cycles_20261103 as batch
from proof_lift_plate import write
from squid_handling_route import CURRENT_SOURCE, CURRENT_SHA, load_route

OUT = batch.FOLDER/'full_calibration_ten_imaging_20261108'
AUTH = ('One calibration, then ten Squid drop-off/five-real-frame/pickup/Home '
        'cycles using the November 8 taught route. Integration requested; execute '
        'only with current operator authorization and loading-position readiness. '
        'Stop on failures; no automatic retry or restart.')


def main():
    route = dict(route_source=CURRENT_SOURCE, route_sha=CURRENT_SHA)
    load_route(CURRENT_SOURCE, CURRENT_SHA)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if OUT.exists():
        raise RuntimeError('Attempt already exists; no replay')
    calibration.OUT, calibration.AUTH = OUT/'calibration', AUTH
    batch.OUT, batch.AUTH = OUT/'imaging', AUTH
    # Check the microscope before any calibration motion.
    squid = batch.stage_ready()
    if squid['state'].get('simulation') or squid['state'].get('camera_simulated') is not False:
        raise RuntimeError('Real camera and stage required')
    if not args.execute:
        calibration.main(calibration_only=True, **route)
        print('Validated calibration and microscope readiness; no motion.', flush=True)
        return
    OUT.mkdir()
    record = dict(status='running', phase='calibration', started_at=time.time(), authorization=AUTH,
                  route_source=str(CURRENT_SOURCE), route_source_sha256=CURRENT_SHA)
    output = OUT/'run.json'
    write(output, record)
    try:
        calibration.main(calibration_only=True, **route)
        result = json.loads((calibration.OUT/'run.json').read_bytes())
        if result['status'] != 'full_calibration_loaded_home_completed_pending_operator_assessment':
            raise RuntimeError('Fresh calibration completion unverified')
        record['phase'] = 'ten_imaging_cycles'
        write(output, record)
        batch.main(**route)
        result = json.loads((batch.OUT/'batch.json').read_bytes())
        if result['completed_cycles'] != 10 or result['verified_images'] != 50:
            raise RuntimeError('Batch count mismatch')
        record.update(status=result['status'], completed_cycles=10, verified_images=50)
    except Exception as error:
        record.update(status='stopped_or_failed', error=str(error))
        raise
    finally:
        record['finished_at'] = time.time()
        write(output, record)
        print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
