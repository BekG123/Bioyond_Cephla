"""Use Squid's Python and software cwd. All stage/controller objects are fake."""
from copy import deepcopy
import hashlib
import os
import sys
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

os.environ['QT_API']='pyqt5'
sys.path.insert(0,os.getcwd())
import control._def as config
from imaging_lifecycle import install,imaging_target

TEXT='acquisition: {widget_type: wellplate}\nwellplate_scan: {regions: [{name: A1, fovs: [[14.5, 12.0]]}]}\nz_stack: {z_range_mm: [1.05, 1.05]}\n'
LIMITS={'x_mm':[5,115],'y_mm':[4,76],'z_mm':[.05,6]}


class Tests(unittest.TestCase):
    def setUp(self):
        self.pose=dict(x_mm=.05,y_mm=.0508,z_mm=1.05);self.calls=[]
        self.target=deepcopy(self.pose)
        self.stage=NS(get_pos=lambda:NS(**self.pose))
        def move(axis,value,**kw):self.calls.append((axis,value));self.pose[axis]=value
        for axis in ('x','y','z'):
            setattr(self.stage,'move_'+axis+'_to',lambda v,a=axis,**kw:move(a+'_mm',v,**kw))
        def run(*a,**kw):self.calls.append(('acquire',deepcopy(self.pose)));return True
        self.finish=lambda:None
        self.controller=NS(experiment_ID='owned',run_acquisition=run,
                           _on_acquisition_completed=lambda:self.finish())
        self.server=NS(microscope=NS(stage=self.stage),multipoint_controller=self.controller,
            _cmd_get_acquisition_status=lambda:dict(in_progress=False,experiment_id='owned'),
            _commands={'get_stage_reference':lambda:dict(reference_hash='accepted',
                dropoff=self.target,scan_limits=LIMITS)})
        def native(stage,**kw):self.calls.append(('native_scan',kw));self.pose.update(x_mm=20,y_mm=20)
        for p in (patch('squid.stage.utils.move_to_scanning_position',side_effect=native),
                  patch.object(config.SLIDE_POSITION,'SCANNING_X_MM',20),
                  patch.object(config.SLIDE_POSITION,'SCANNING_Y_MM',20)):
            p.start();self.addCleanup(p.stop)
        install(self.server)

    def prepare(self,text=TEXT):
        return self.server._commands['prepare_confirmed_imaging'](text,hashlib.sha256(text.encode()).hexdigest(),'accepted')

    def status(self):return self.server._commands['get_acquisition_status']()

    def test_move_into_scan_area_before_native_acquisition_captures_start(self):
        self.assertEqual(self.server._commands['get_stage_reference']()['imaging_lifecycle_version'],1)
        self.assertFalse(self.calls)
        self.prepare();self.controller.run_acquisition()
        self.assertEqual([c[0] for c in self.calls],['native_scan','x_mm','y_mm','z_mm','acquire'])
        self.assertEqual(self.server._lacry_lifecycle['return_position'],dict(x_mm=14.5,y_mm=12.,z_mm=1.05))
        self.controller._on_acquisition_completed()
        self.assertEqual(self.status()['cleanup']['status'],'completed')

    def test_native_idle_and_images_finished_still_wait_for_cleanup(self):
        self.prepare();self.controller.run_acquisition()
        self.assertTrue(self.status()['in_progress'])
        entered,release=threading.Event(),threading.Event()
        def delayed():entered.set();self.assertTrue(release.wait(3))
        self.finish=delayed
        thread=threading.Thread(target=self.controller._on_acquisition_completed);thread.start()
        self.assertTrue(entered.wait(2))
        self.assertEqual(self.status()['cleanup']['status'],'running')
        self.assertTrue(self.status()['in_progress'])
        release.set();thread.join(3)
        self.assertFalse(self.status()['in_progress'])
        self.assertEqual(self.status()['cleanup']['status'],'completed')

    def test_cleanup_timeout_is_latched_and_no_retry_is_sent(self):
        self.prepare();self.controller.run_acquisition()
        def fail():raise TimeoutError('X return timeout')
        self.finish=fail
        with self.assertRaises(TimeoutError):self.controller._on_acquisition_completed()
        self.assertEqual(self.status()['cleanup']['status'],'failed')
        before=len(self.calls)
        with self.assertRaisesRegex(RuntimeError,'review'):self.controller.run_acquisition()
        self.assertEqual(len(self.calls),before)

    def test_cleanup_feedback_mismatch_is_failure_not_completion(self):
        self.prepare();self.controller.run_acquisition();self.pose['x_mm']+=.268
        with self.assertRaisesRegex(RuntimeError,'starting position'):self.controller._on_acquisition_completed()
        self.assertEqual(self.status()['cleanup']['status'],'failed')

    def test_bad_scan_target_or_reference_never_moves(self):
        with self.assertRaisesRegex(ValueError,'outside'):self.prepare(TEXT.replace('14.5','0.05'))
        with self.assertRaisesRegex(ValueError,'checksum'):
            self.server._commands['prepare_confirmed_imaging'](TEXT,'wrong','accepted')
        self.assertFalse(self.calls)

    def test_failed_scan_entry_does_not_start_images_or_retry(self):
        with patch('squid.stage.utils.move_to_scanning_position',side_effect=TimeoutError('entry failed')) as native:
            with self.assertRaises(TimeoutError):self.prepare()
            self.assertEqual(native.call_count,1)
        self.assertFalse(self.calls)

    def test_flexible_positions_use_recorded_z(self):
        text='acquisition: {widget_type: flexible}\nflexible_scan: {positions: [{fovs: [[15, 12, 1.2]]}]}\n'
        self.assertEqual(imaging_target(text,LIMITS),dict(x_mm=15,y_mm=12,z_mm=1.2))


if __name__=='__main__':unittest.main()
