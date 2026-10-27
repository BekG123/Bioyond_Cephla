"""Launch Squid with the Lacry settings add-on; shipped files are unchanged.

Use Squid's Python environment:
python launch.py --software path/to/squid/software --simulation --start-server
All arguments after --software's value are passed to Squid unchanged.
"""
import argparse
import os
from pathlib import Path
import runpy
import sys


def configure_stage_only(config):
    """Explicit operator-selected XYZ test; no absent optical peripherals."""
    if config.SIMULATE_MICROCONTROLLER:
        raise SystemExit('Stage-only testing requires the physical controller.')
    config.SIMULATE_CAMERA = True
    for name in ('USE_EMISSION_FILTER_WHEEL', 'USE_SQUID_FILTERWHEEL',
                 'SUPPORT_LASER_AUTOFOCUS', 'ENABLE_SPINNING_DISK_CONFOCAL',
                 'USE_XERYON', 'USE_OBJECTIVE_TURRET', 'ENABLE_NL5', 'ENABLE_CELLX',
                 'USE_SQUID_LASER_ENGINE', 'USE_CELESTA_ETHERNET_CONTROL',
                 'USE_LDI_SERIAL_CONTROL', 'USE_ANDOR_LASER_CONTROL',
                 'SUPPORT_SCIMICROSCOPY_LED_ARRAY', 'RUN_FLUIDICS'):
        setattr(config, name, False)


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--software', required=True)
    parser.add_argument('--simulate-camera', action='store_true',
                        help='Use synthetic camera frames with the physical stage for integration tests.')
    parser.add_argument('--controller-serial',
                        help='Operator-identified physical controller serial for this session only.')
    parser.add_argument('--stage-only', action='store_true',
                        help='Physical XYZ stage test with synthetic images and no optical peripherals.')
    options, arguments = parser.parse_known_args()
    software = Path(options.software).resolve()
    main_file = software/'main_hcs.py'
    if not main_file.is_file():
        raise SystemExit('Choose the Squid software folder containing main_hcs.py.')
    os.chdir(software)
    os.environ['QT_API'] = 'pyqt5'  # Match shipped main_hcs.py before importing Qt.
    sys.path.insert(0, str(software))
    from state_io import install as install_state_io
    install_state_io()
    # Apply flags before modules such as squid.config cache device configuration.
    import control._def as config
    if options.stage_only:
        if '--simulation' in arguments:
            raise SystemExit('Stage-only testing cannot use full simulation.')
        configure_stage_only(config)
    if options.controller_serial:
        import control._def as config
        from serial.tools import list_ports
        if '--simulation' in arguments:
            raise SystemExit('A physical controller override cannot be used in full simulation.')
        matches = [p for p in list_ports.comports() if p.serial_number == options.controller_serial]
        if len(matches) != 1:
            raise SystemExit('The identified Squid controller is missing or ambiguous; no startup was attempted.')
        config.CONTROLLER_SN = options.controller_serial
    if options.simulate_camera:
        import control._def as config
        if '--simulation' in arguments or config.SIMULATE_MICROCONTROLLER:
            raise SystemExit('Camera-only simulation requires a real stage/controller configuration.')
        config.SIMULATE_CAMERA = True
    from control.microscope_control_server import MicroscopeControlServer
    from current_settings import install
    from stage_position import install as install_stage
    from imaging_lifecycle import install as install_lifecycle
    original = MicroscopeControlServer.__init__
    def initialize(self, *args, **kwargs):
        original(self, *args, **kwargs)
        install(self)
        install_stage(self)
        install_lifecycle(self)
        # Read-only capability evidence for deployment checks.
        reference = self._commands['get_stage_reference']
        self._commands['get_stage_reference'] = lambda: dict(reference(), state_io_version=1)
    MicroscopeControlServer.__init__ = initialize
    sys.argv = [str(main_file), *arguments]
    runpy.run_path(str(main_file), run_name='__main__')


if __name__ == '__main__':
    main()
