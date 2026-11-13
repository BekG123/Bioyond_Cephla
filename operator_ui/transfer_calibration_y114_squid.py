"""Supervised candidate transfer for +Y11.4 pickup and newly taught destination."""
import test_squid_destination_empty as transfer

if __name__ == '__main__':
    transfer.SOURCE=transfer.SOURCE.with_name('destination_calibration_y114_20261101.json')
    transfer.SHA='47a7990738aef771c09052d69a62faabf901d5b625a12ec5b17cb1f343ced6dd'
    transfer.main()
