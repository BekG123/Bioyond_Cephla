"""Fresh authorized 48-well pickup through loaded Home; no algorithm changes."""
import full_calibration_handling_20261103 as workflow
from squid_handling_route import CURRENT_SOURCE,CURRENT_SHA

workflow.OUT=workflow.FOLDER/'calibration_for_queue_squid_20261110'
workflow.AUTH=('Operator requested pickup of the plate in the arm calibration holder and transport to Squid. '
    'Standing empty-gripper, unchanged clear route, hands clear and supervised E-stop confirmations apply. '
    'Reuse accepted 48-well calibration, alignment, descent, 3.9 mm grip, proof lift and loaded Home. '
    'No new physical acceptance is claimed; no automatic retries. Squid travel is a separate checked queue.')

if __name__=='__main__':
    workflow.main(calibration_only=True,route_source=CURRENT_SOURCE,route_sha=CURRENT_SHA)
