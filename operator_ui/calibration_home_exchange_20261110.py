"""Authorized unchanged pickup for the first HOME-holder exchange trial.

Uses the existing accepted-repeat receipt binding. No holder return, release,
rotation, or retry is implicit in this entry point.
"""
import full_calibration_handling_20261103 as workflow
from squid_handling_route import CURRENT_SOURCE, CURRENT_SHA

workflow.OUT = workflow.FOLDER / 'calibration_home_exchange_20261110'
workflow.AUTH = (
    'Operator requested full calibration then an IK-checked HOME-holder return, '
    'and confirmed empty jaws, plate flat in HOME holder, clear pickup/return '
    'route, arm released, hands clear and supervised E-stop. Prepare Auto and '
    'run the accepted calibration/alignment/3.9 mm grip/5 mm proof lift and '
    'loaded IDLE return. This wrapper stops at IDLE. HOME seating/release is '
    'a separate fresh checked trial; no new visual acceptance is claimed.'
)

if __name__ == '__main__':
    workflow.main(calibration_only=True, route_source=CURRENT_SOURCE,
                  route_sha=CURRENT_SHA)
