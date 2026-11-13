"""Return only along the accepted Squid reverse route, with claws open."""
import sys
import run_accepted_squid_roundtrip as handling

if __name__ == '__main__':
    handling.SOURCE = handling.SOURCE.with_name('destination_leveled_20261101T103159Z.json')
    handling.SHA = '255f431bf8eef3c100f9f163603d656fe666d9e825683f8d0f9e54850710047e'
    sys.argv.append('--empty-return-only')
    handling.main()
