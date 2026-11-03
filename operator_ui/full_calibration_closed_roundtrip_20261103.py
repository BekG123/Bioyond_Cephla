"""Full accepted calibration then Home/Squid/Home with no release."""
import full_calibration_handling_20261103 as workflow


if __name__ == '__main__':
    workflow.OUT = workflow.FOLDER / 'full_calibration_closed_roundtrip_20261103'
    workflow.AUTH = 'Operator confirmed previous full handling test succeeded, returned plate to arm holder, and requested full calibration followed by complete Home-Squid-Home closed-claw skill. No Squid release or regrip.'
    workflow.main(closed_claw=True)
