"""Capture the correction taught after the leveled-Squid delivery trial."""
import capture_leveled_squid as capture

capture.SOURCE = capture.SOURCE.with_name('destination_leveled_20261101T101804Z.json')
capture.SHA = 'dcfeb4d036a665eab0c99d4fb762194b5b153e85a906c6a63f6e031f72cb3f88'

if __name__ == '__main__':
    capture.main()
