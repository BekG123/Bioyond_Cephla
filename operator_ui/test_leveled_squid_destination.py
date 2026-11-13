"""Use the existing monitored executor with the pinned leveled-Squid candidate."""
import test_squid_destination_empty as trial

trial.SOURCE = trial.ROOT/'operator_ui/reports/squid_48well_approach/destination_leveled_20261101T101804Z.json'
trial.SHA = 'dcfeb4d036a665eab0c99d4fb762194b5b153e85a906c6a63f6e031f72cb3f88'

if __name__ == '__main__':
    trial.main()
