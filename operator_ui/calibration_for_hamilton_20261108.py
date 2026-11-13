"""Requested 48-well calibration and pickup; finish loaded at Home."""
import full_calibration_handling_20261103 as workflow

workflow.OUT = workflow.FOLDER / 'calibration_for_hamilton_20261108'
workflow.AUTH = ('Operator requested full calibration followed by the saved Hamilton '
                 'route, with plate returned to the arm pickup holder. Reuse the '
                 'unchanged accepted 48-well calibration, alignment, descent, grip, '
                 'proof lift and loaded Home. This phase stops Home; Hamilton '
                 'access readiness is checked separately. No retry or restart.')

if __name__ == '__main__':
    workflow.main(calibration_only=True)
