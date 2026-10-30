"""Current console acceptance suite: fake hardware and checked recorded evidence.

From the repository root: python operator_ui/tests/test_offline.py
Install requirements-dev.txt first. No hardware, API key or camera SDK required.
The former monolithic test exercised removed automatic gripping/retreat code;
these maintained suites cover the current guarded implementations instead.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SUITES = (
    'test_portable_checkout', 'test_offline_transport', 'test_lua_startup',
    'test_fast_disk', 'test_alignment', 'test_trajectory_queue', 'test_lua_descent',
    'test_torque_grip', 'test_reference_grip', 'test_researcher_descent',
    'test_squid_48well_endpoint_trial', 'test_squid_48well_retrieval_trial',
    'test_scope_compact137', 'test_hamilton_true_home', 'test_hamilton_reteach',
)


def main():
    sys.path[:0] = [str(HERE), str(HERE.parent), str(ROOT/'bioyond-s4-mcp/tests')]
    try:
        import lupa.lua51  # noqa: F401
    except ImportError:
        print('Install offline-test dependencies: python -m pip install -r requirements-dev.txt', file=sys.stderr)
        return 2

    def offline_only(event, args):
        if event == 'socket.connect':
            address = args[1]
            if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', '::1') or address[1] in (5001, 5002, 5050, 5055, 5056, 8086):
                raise RuntimeError('Offline suite refused a non-test network connection')
        if event == 'subprocess.Popen':
            expected = [sys.executable, str(ROOT/'Pick and Hold/Calibration/fast_disk.py'), 'test']
            if args[1] == expected or args[1] == subprocess.list2cmdline(expected):
                return  # Pure vendor-math self-test; no device connection.
            raise RuntimeError('Offline suite refused an external process')
        if event == 'os.system':
            raise RuntimeError('Offline suite refused an external process')

    sys.addaudithook(offline_only)
    with tempfile.TemporaryDirectory(prefix='cephla-offline-') as temp:
        os.environ['LOCALAPPDATA'] = temp
        os.environ['BIOYOND_ENV_STORE'] = str(Path(temp)/'envelope.json')
        os.environ.pop('ANTHROPIC_API_KEY', None)
        suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
