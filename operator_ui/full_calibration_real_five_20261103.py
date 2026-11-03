"""Fresh full-calibration -> real imaging -> retrieval experiment; no retries."""
import argparse
import json
import sys
import time
import full_calibration_handling_20261103 as calibration
import real_camera_five_20261103 as imaging
from proof_lift_plate import write

OUT = imaging.ROOT/'reports/squid_48well_approach/full_calibration_real_five_20261103'
AUTH = ('Operator confirmed plate in calibration holder, claws empty, clear route and on-site '
        'E-stop supervision for full calibration, one Squid drop-off, five real images, '
        'pickup and loaded Home. Previous run needed manual correction of uneven drop-off; '
        'this is a fresh full-calibration attempt, not a repeatability claim.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if OUT.exists():
        raise RuntimeError('Attempt directory exists; no automatic retry.')
    calibration.OUT=OUT/'calibration'
    calibration.AUTH=AUTH
    imaging.OUT=OUT/'imaging'
    imaging.AUTH=AUTH
    if not args.execute:
        calibration.main(calibration_only=True)
        print('Calibration-to-imaging chain validated; no movement.',flush=True)
        return
    OUT.mkdir()
    record=dict(status='running',phase='imaging_preflight',authorization=AUTH,started_at=time.time())
    output=OUT/'run.json'
    write(output,record)
    try:
        # Verify microscope session and prepare plan before moving the arm.
        imaging.prepare()
        record['phase']='full_calibration'
        write(output,record)
        calibration.main(calibration_only=True)
        receipt=json.loads((calibration.OUT/'run.json').read_text())
        if receipt['status']!='full_calibration_loaded_home_completed_pending_operator_assessment':
            raise RuntimeError('Fresh calibration did not finish at loaded Home.')
        record['phase']='dropoff_imaging_pickup'
        write(output,record)
        imaging.execute()
        record['result']=json.loads((imaging.OUT/'run.json').read_text())
        record['status']=record['result']['status']
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        raise
    finally:
        record['finished_at']=time.time()
        write(output,record)
        print(json.dumps(dict(status=record['status'],phase=record['phase'],report=str(output))),flush=True)


if __name__=='__main__':
    main()
