"""Calibration and pickup to Home for the operator's next teaching."""
import full_calibration_handling_20261103 as workflow

workflow.OUT = workflow.FOLDER / 'calibration_for_reteaching_20261108'
workflow.AUTH = ('Operator returned plate to arm pickup holder, moved empty arm '
                 'within workspace, prepared Running Auto and requested full '
                 'calibration before manually reteaching the ideal Squid position. '
                 'End at loaded Home; no Squid movement, release or automatic retry.')

if __name__ == '__main__':
    workflow.main(calibration_only=True)
