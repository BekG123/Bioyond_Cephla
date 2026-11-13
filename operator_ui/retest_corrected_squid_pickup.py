"""Reuse monitored pickup/Home sequence at the corrected taught Squid pose."""
import run_accepted_squid_roundtrip as trial

trial.SOURCE = trial.SOURCE.with_name('destination_leveled_20261101T103159Z.json')
trial.SHA = '255f431bf8eef3c100f9f163603d656fe666d9e825683f8d0f9e54850710047e'

if __name__ == '__main__':
    trial.main()
