"""Fresh operator-requested attempt of the unchanged accepted full pipeline."""
import full_calibration_retry03_20261109 as previous

previous.workflow.OUT = previous.workflow.FOLDER / 'full_calibration_retry04_20261109'

if __name__ == '__main__':
    previous.workflow.main(calibration_only=True)
