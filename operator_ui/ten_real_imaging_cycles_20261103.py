"""Ten drop-off/five-real-frame/pickup/Home cycles, without retries."""
import argparse
import json
import time
from PIL import Image
import real_camera_five_20261103 as imaging
from full_calibration_ten_handling_20261103 import home, stage_ready
from capture_squid_approach_20261103 import FOLDER, sha
from proof_lift_plate import api, write

OUT = FOLDER/'ten_real_imaging_cycles_20261103'
AUTH = ('Operator confirmed ten full drop-off, five real-camera passes, verified '
        'stage return, pickup and loaded Home cycles (50 images total). Start '
        'from existing loaded Home after accepted calibration/handling batch; '
        'unchanged plate, fixture, clearance and supervision. No recalibration, '
        'autofocus, silent retries or controller restart.')


def verify_images(folder):
    ticket_path = folder/'imaging_ticket.json'
    ticket = json.loads(ticket_path.read_bytes())
    completion = ticket['completion']
    stats = completion['job']['stats']
    if (ticket['status'] != 'completed' or not completion.get('completion_confirmed')
            or not completion.get('real_imaging_complete')
            or completion.get('camera_simulated') is not False
            or completion.get('stage_simulated') is not False
            or stats['total_images'] != 5 or stats['total_timepoints'] != 5
            or stats['errors_encountered'] != 0):
        raise RuntimeError('Five real images not verified; stop batch')
    files = sorted((folder/'images').rglob('*.bmp'))
    if len(files) != 5 or {p.parent.name for p in files} != {'0','1','2','3','4'}:
        raise RuntimeError('Expected five saved timepoint frames')
    frames = []
    for path in files:
        with Image.open(path) as frame:
            if frame.size != (2700,2700):
                raise RuntimeError('Unexpected image dimensions')
            frame.verify()
        frames.append(dict(path=str(path.relative_to(OUT)), sha256=sha(path)))
    return dict(run_id=ticket['run_id'], ticket_sha256=sha(ticket_path), frames=frames)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if OUT.exists():
        raise RuntimeError('Batch already attempted; no replay')
    imaging.arm_home()
    initial = home(3.9)
    squid = stage_ready()
    if squid['state'].get('simulation') or squid['state'].get('camera_simulated') is not False:
        raise RuntimeError('Actual microscope camera required')
    print(json.dumps(dict(validated=True, cycles=10, frames_per_cycle=5,
                          total_images=50, execute=args.execute)), flush=True)
    if not args.execute:
        return
    OUT.mkdir()
    output = OUT/'batch.json'
    record = dict(status='running', started_at=time.time(), authorization=AUTH,
                  requested_cycles=10, completed_cycles=0, verified_images=0,
                  initial_robot=initial, initial_squid=squid, cycles=[], automatic_retries=False)
    write(output, record)
    try:
        for number in range(1,11):
            imaging.arm_home()
            home(3.9)
            stage_ready()
            imaging.OUT = OUT/f'cycle_{number:02d}'
            imaging.AUTH = AUTH
            cycle = dict(number=number, status='preparing', started_at=time.time())
            record['cycles'].append(cycle)
            record['current_cycle'] = number
            write(output, record)
            imaging.prepare()
            cycle['status'] = 'running'
            write(output, record)
            print(json.dumps(dict(cycle=number, phase='full_imaging_cycle_started')), flush=True)
            imaging.execute()
            receipt = imaging.OUT/'run.json'
            if json.loads(receipt.read_bytes())['status'] != 'completed_pending_operator_assessment':
                raise RuntimeError('Cycle completion unverified')
            evidence = verify_images(imaging.OUT)
            if any(c.get('imaging',{}).get('run_id') == evidence['run_id'] for c in record['cycles']):
                raise RuntimeError('Imaging run ID reused')
            final = home(3.9)
            stage_ready()
            cycle.update(status='completed_pending_operator_assessment', finished_at=time.time(),
                         imaging=evidence, run_sha256=sha(receipt), final_robot=final['robot'])
            record.update(completed_cycles=number, verified_images=number*5)
            write(output, record)
            print(json.dumps(dict(completed_cycles=number, verified_images=number*5)), flush=True)
        record.update(status='ten_real_imaging_cycles_completed_pending_operator_assessment',
                      final_robot=home(3.9))
    except Exception as error:
        record.update(status='stopped_or_failed', error=str(error))
        # Existing phase controllers own any active acquisition and safe stop.
        # Never dispatch another handling cycle or reset/restart hardware here.
        raise
    finally:
        record['finished_at'] = time.time()
        write(output, record)
        print(json.dumps(dict(status=record['status'], completed_cycles=record['completed_cycles'],
                              verified_images=record['verified_images'], report=str(output))), flush=True)


if __name__ == '__main__':
    main()
