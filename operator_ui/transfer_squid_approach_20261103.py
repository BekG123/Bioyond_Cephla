"""Pinned Nov 3 Squid approach. Stops overhead; cannot descend or release."""
import sys
import test_squid_destination_empty as transfer

if __name__ == '__main__':
    transfer.SOURCE = transfer.SOURCE.with_name('approach_20261103T180838653466Z.json')
    transfer.SHA = 'a2fb701e3224515e4c4437332b24f4be360aa1c62e074cc19eb39ff6bd4ae613'
    sys.argv.extend(['--loaded-forward-only', '--approach-only'])
    transfer.main()
