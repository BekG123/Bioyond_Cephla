"""Run in Squid's Python environment and software cwd. No hardware is created."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch
import tempfile

os.environ['QT_API']='pyqt5'
sys.path.insert(0,os.getcwd())
from qtpy.QtCore import QCoreApplication,QObject,QThread
from current_settings import install
from control.core.multi_point_utils import AcquisitionParameters
from control.microscope_control_server import MicroscopeControlServer
import yaml


class Controller(QObject):
    def __init__(self):
        super().__init__()
        self.busy=False;self.starts=[];self.runs=[];self.aborts=[]
        self.widget_type='wellplate';self.scan_size_mm=1.;self.overlap_percent=10.
        self.region_laser_af_offsets={};self.NZ=2;self.deltaZ=.001;self.Nt=3
        self.channel=dict(name='BF',exposure_time=12.5,illumination_intensity=17.)

    def acquisition_in_progress(self):return self.busy
    def request_abort_aquisition(self):self.aborts.append(QThread.currentThread())
    def set_base_path(self,path):self.base_path=path
    def start_new_experiment(self,ident):self.starts.append(ident);self.experiment_ID=ident+'_native'
    def run_acquisition(self):self.runs.append(QThread.currentThread());return True
    def _on_acquisition_completed(self):pass
    def build_params(self,coords):
        return AcquisitionParameters(self.experiment_ID,'ignored', [deepcopy(self.channel)],
            self.timestamp_acquisition_started,coords,1,0.,1,0.,self.NZ,self.deltaZ,self.Nt,5.,
            False,False,False,1.,'FROM BOTTOM',(3.,3.001))


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.controller=Controller();self.focus=False;self.configure_threads=[]
        coords=NS(region_centers={'A1':[1.,2.,3.]},region_fov_coordinates={'A1':[(1.,2.,3.)]},
                  region_shapes={'A1':'Square'},format='96 well plate')
        self.widget=NS(checkbox_useFocusMap=NS(isChecked=lambda:self.focus),
            channel_sequence=NS(ordered_selected_names=lambda:['BF']),scanCoordinates=coords,
            configure_controller_from_ui=lambda:self.configure_threads.append(QThread.currentThread()),
            set_acquisition_running_state=lambda *args:None)
        self.gui=QObject();self.gui.recordTabWidget=NS(currentWidget=lambda:self.widget)
        microscope=NS(objective_store=NS(current_objective='20x'),camera=NS(get_binning=lambda:(1,1)),
                      stage=NS(get_pos=lambda:NS(x_mm=14.,y_mm=12.,z_mm=1.05)))
        self.server=MicroscopeControlServer(microscope,multipoint_controller=self.controller,
                                            scan_coordinates=coords,gui=self.gui)
        install(self.server)

    def call(self,command,**args):
        result={}
        def worker():
            try:result['value']=self.server._commands[command](**args)
            except Exception as error:result['error']=error
        thread=threading.Thread(target=worker);thread.start()
        deadline=time.monotonic()+4
        while thread.is_alive() and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.001)
        thread.join(.1);self.assertFalse(thread.is_alive())
        if 'error' in result:raise result['error']
        return result['value']

    def test_native_serializer_preserves_selected_settings_without_start(self):
        snap=self.call('get_current_acquisition_settings');data=yaml.safe_load(snap['yaml'])
        self.assertEqual(data['z_stack']['nz'],2);self.assertEqual(data['time_series']['nt'],3)
        self.assertEqual(data['channels'][0]['exposure_time'],12.5)
        self.assertEqual(data['wellplate_scan']['regions'][0]['fovs'],[[1.,2.,3.]])
        self.assertEqual(snap['summary']['total_images'],6)
        self.assertFalse(self.controller.starts);self.assertFalse(self.controller.runs)
        self.assertEqual(self.configure_threads,[self.app.thread()])
        self.assertFalse(self.server._python_exec_enabled)
        self.assertFalse(hasattr(self.controller,'timestamp_acquisition_started'))
        self.assertFalse(hasattr(self.controller,'experiment_ID'))

    def test_start_checks_snapshot_on_same_qt_thread(self):
        snap=self.call('get_current_acquisition_settings')
        result=self.call('run_current_acquisition',settings_sha256=snap['sha256'],
                         experiment_id='Lacry_'+'a'*32,base_path='unused-test-output')
        self.assertTrue(result['started']);self.assertEqual(self.controller.runs,[self.app.thread()])

    def test_empty_locations_export_live_controls_without_start_or_gui_coordinate_change(self):
        self.widget.scanCoordinates.region_centers={}
        self.widget.scanCoordinates.region_fov_coordinates={}
        self.controller.Nt=5;self.controller.NZ=4
        self.controller.channel['exposure_time']=30
        with self.assertRaisesRegex(RuntimeError,'Select the wells'):
            self.call('get_current_acquisition_settings')
        snapshot=self.call('get_current_acquisition_controls')
        data=yaml.safe_load(snapshot['yaml'])
        self.assertEqual(data['time_series']['nt'],5)
        self.assertEqual(data['z_stack']['nz'],4)
        self.assertEqual(data['channels'][0]['exposure_time'],30)
        self.assertEqual(snapshot['summary']['total_images'],0)
        self.assertEqual(data['wellplate_scan']['regions'],[])
        self.assertEqual(self.widget.scanCoordinates.region_fov_coordinates,{})
        self.assertFalse(self.controller.starts);self.assertFalse(self.controller.runs)

    def test_changed_channel_exposure_refuses_start(self):
        snap=self.call('get_current_acquisition_settings');self.controller.channel['exposure_time']=20
        with self.assertRaisesRegex(RuntimeError,'settings changed'):
            self.call('run_current_acquisition',settings_sha256=snap['sha256'],
                      experiment_id='Lacry_'+'a'*32,base_path='unused-test-output')
        self.assertFalse(self.controller.starts)

    def test_busy_or_unsupported_focus_settings_are_not_silently_replaced(self):
        self.controller.busy=True
        with self.assertRaisesRegex(RuntimeError,'finish'):self.call('get_current_acquisition_settings')
        self.controller.busy=False;self.focus=True
        with self.assertRaisesRegex(RuntimeError,'focus map'):self.call('get_current_acquisition_settings')
        self.assertFalse(self.controller.starts)

    def test_wrong_identifier_cannot_start(self):
        with self.assertRaisesRegex(RuntimeError,'identifier'):
            self.call('run_current_acquisition',settings_sha256='unused',experiment_id='old',base_path='unused')
        self.assertFalse(self.controller.runs)

    def test_abort_is_atomic_and_specific_to_the_owned_job(self):
        self.controller.busy=True;self.controller.experiment_ID='owned'
        with self.assertRaisesRegex(RuntimeError,'different'):
            self.call('abort_current_acquisition',experiment_id='other')
        self.assertFalse(self.controller.aborts)
        self.assertTrue(self.call('abort_current_acquisition',experiment_id='owned')['abort_requested'])
        self.assertEqual(self.controller.aborts,[self.app.thread()])

    def test_launcher_adds_commands_without_editing_shipped_source(self):
        import launch
        original=MicroscopeControlServer.__init__
        cwd=os.getcwd();path=list(sys.path);argv=list(sys.argv)
        try:
            with tempfile.TemporaryDirectory() as folder:
                shipped=Path(folder)/'main_hcs.py';shipped.write_text('# shipped fixture\n')
                sys.argv=['launch.py','--software',folder,'--simulation','--start-server']
                with patch.object(launch.runpy,'run_path') as boot:
                    launch.main()
                    boot.assert_called_once_with(str(shipped),run_name='__main__')
                    self.assertEqual(sys.argv,[str(shipped),'--simulation','--start-server'])
                    server=MicroscopeControlServer(self.server.microscope,
                        multipoint_controller=self.controller,gui=self.gui)
                    self.assertIn('run_current_acquisition',server._commands)
                    self.assertIn('prepare_confirmed_imaging',server._commands)
                    self.assertEqual(server._lacry_lifecycle['version'],1)
                    self.assertFalse(server._python_exec_enabled)
                    self.assertEqual(shipped.read_text(),'# shipped fixture\n')
                os.chdir(cwd)
        finally:
            MicroscopeControlServer.__init__=original
            os.chdir(cwd);sys.path[:]=path;sys.argv=argv

    def test_camera_only_launcher_keeps_physical_controller(self):
        import launch
        import control._def as config
        original=MicroscopeControlServer.__init__
        cwd=os.getcwd();path=list(sys.path);argv=list(sys.argv)
        try:
            with tempfile.TemporaryDirectory() as folder:
                (Path(folder)/'main_hcs.py').write_text('# fixture\n')
                sys.argv=['launch.py','--software',folder,'--simulate-camera','--start-server']
                with patch.object(config,'SIMULATE_MICROCONTROLLER',False), \
                     patch.object(config,'SIMULATE_CAMERA',False), \
                     patch.object(launch.runpy,'run_path') as boot:
                    launch.main()
                    self.assertTrue(config.SIMULATE_CAMERA)
                    self.assertFalse(config.SIMULATE_MICROCONTROLLER)
                    self.assertNotIn('--simulation',sys.argv)
                    boot.assert_called_once()
                sys.argv=['launch.py','--software',folder,'--simulate-camera','--simulation']
                with patch.object(launch.runpy,'run_path') as boot:
                    with self.assertRaisesRegex(SystemExit,'real stage'):
                        launch.main()
                    boot.assert_not_called()
                os.chdir(cwd)
        finally:
            MicroscopeControlServer.__init__=original
            os.chdir(cwd);sys.path[:]=path;sys.argv=argv

    def test_controller_override_requires_one_matching_device(self):
        import launch
        import control._def as config
        from serial.tools import list_ports
        original=MicroscopeControlServer.__init__
        cwd=os.getcwd();path=list(sys.path);argv=list(sys.argv)
        try:
            with tempfile.TemporaryDirectory() as folder:
                (Path(folder)/'main_hcs.py').write_text('# fixture\n')
                args=['launch.py','--software',folder,'--controller-serial','confirmed-serial','--start-server']
                sys.argv=list(args)
                with patch.object(list_ports,'comports',return_value=[]), patch.object(launch.runpy,'run_path') as boot:
                    with self.assertRaisesRegex(SystemExit,'missing or ambiguous'):
                        launch.main()
                    boot.assert_not_called()
                sys.argv=list(args)
                with patch.object(list_ports,'comports',return_value=[NS(serial_number='confirmed-serial')]), \
                     patch.object(config,'CONTROLLER_SN','old'), patch.object(launch.runpy,'run_path') as boot:
                    launch.main()
                    self.assertEqual(config.CONTROLLER_SN,'confirmed-serial')
                    boot.assert_called_once()
                os.chdir(cwd)
        finally:
            MicroscopeControlServer.__init__=original
            os.chdir(cwd);sys.path[:]=path;sys.argv=argv

    def test_stage_only_excludes_absent_optics_but_keeps_real_xyz(self):
        import launch
        config=NS(SIMULATE_MICROCONTROLLER=False, SIMULATE_CAMERA=False,
                  HOMING_ENABLED_X=True,HOMING_ENABLED_Y=True,HOMING_ENABLED_Z=True)
        launch.configure_stage_only(config)
        self.assertFalse(config.SIMULATE_MICROCONTROLLER)
        self.assertTrue(config.SIMULATE_CAMERA)
        self.assertFalse(config.USE_EMISSION_FILTER_WHEEL)
        self.assertFalse(config.SUPPORT_LASER_AUTOFOCUS)
        self.assertFalse(config.USE_CELESTA_ETHERNET_CONTROL)
        self.assertTrue(config.HOMING_ENABLED_X and config.HOMING_ENABLED_Y and config.HOMING_ENABLED_Z)
        config.SIMULATE_MICROCONTROLLER=True
        with self.assertRaisesRegex(SystemExit,'physical controller'):
            launch.configure_stage_only(config)


if __name__=='__main__':unittest.main()
