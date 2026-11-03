"""Pinned new taught Squid approach; no descent, release or startup."""
import sys
import test_squid_destination_empty as transfer

if __name__ == '__main__':
    transfer.SOURCE = transfer.SOURCE.with_name('destination_reteach_20261103T185217893840Z.json')
    transfer.SHA = '7846a622f2cd4ebdc2ea0d518b95a06d9c184cb156c001dacf5f49b5b78b2a02'
    sys.argv.extend(['--loaded-forward-only', '--approach-only'])
    transfer.main()
