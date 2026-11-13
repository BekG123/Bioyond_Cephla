"""Fresh explicitly requested retry after the operator restored holder E2."""
from calibration_home_exchange_20261110 import workflow, CURRENT_SOURCE, CURRENT_SHA

workflow.OUT = workflow.FOLDER / 'calibration_home_exchange_retry01_20261110'
workflow.AUTH += (
    ' The previous attempt stopped before arm travel because holder E2 was '
    'outside its correction bound. Operator restored E2 near +1.77 degrees, '
    'confirmed the plate flat, hands clear and E-stop supervised, and requested '
    'this fresh retry. Preserve the original failure record.'
)

if __name__ == '__main__':
    workflow.main(calibration_only=True, route_source=CURRENT_SOURCE,
                  route_sha=CURRENT_SHA)
