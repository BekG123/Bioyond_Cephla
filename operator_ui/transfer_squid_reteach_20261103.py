"""Pinned new taught Squid approach; no descent, release or startup."""
import sys
import test_squid_destination_empty as transfer

if __name__ == '__main__':
    transfer.SOURCE = transfer.SOURCE.with_name('destination_final_z266p81_20261103.json')
    transfer.SHA = 'ac004fd846bf2333a29f29374b7091b7c042cb6cf31d53ca09c45432412a84b8'
    sys.argv.extend(['--loaded-forward-only', '--approach-only'])
    transfer.main()
