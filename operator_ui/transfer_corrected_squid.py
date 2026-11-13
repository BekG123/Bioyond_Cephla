"""Use the accepted corrected Squid route with the monitored transfer executor."""
import test_squid_destination_empty as transfer

if __name__ == '__main__':
    transfer.SOURCE = transfer.SOURCE.with_name('destination_leveled_20261101T103159Z.json')
    transfer.SHA = '255f431bf8eef3c100f9f163603d656fe666d9e825683f8d0f9e54850710047e'
    transfer.main()
