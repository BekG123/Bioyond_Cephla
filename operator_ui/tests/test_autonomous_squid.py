"""One confirmed workflow; real robot planner/Lua against fake hardware only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import yaml
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from autonomous_squid import AutonomousSquid
from squid_execution import SquidExecution
from lacry_agent import LacryAgent
from researcher_teaching import TeachingError
import test_home_then_calibration as compound
import test_squid_handling as travel


class FakeMicroscope:
    def __init__(self, directory):
        self.now = 1000.
        self.calls = []
        self.pose = dict(x_mm=1.,y_mm=2.,z_mm=3.)
        self.state = dict(connected=True,status='idle',session='session-1',simulation=True,
                          completion_confirmed=False)
        self.yaml = yaml.safe_dump(dict(acquisition=dict(widget_type='wellplate',xy_mode='Current Position'),
            channels=[dict(name='BF')],wellplate_scan=dict(regions=[dict(name='current',center_mm=[21,2],fovs=[[21,2]])]),
            z_stack=dict(z_range_mm=[3,3],nz=1),time_series=dict(nt=1,delta_t_s=0)),sort_keys=True)
        self.finish = True
        self.failure = None
        self.on_start = None
        self.on_loading = None
        self.loading = None
        self.follow_stage = False
        self.imaged_yaml = None
        self.imaged_yamls = []
        self.acquisition_count = 0
        self.selection_cleared = False
        self.config = Path(directory)/'profiles.json'
        self.config.write_text(json.dumps(dict(default='current',profiles=dict(current=dict(
            label='Selected GUI settings',simulation=True,command='current_settings',params={},
            timeout_s=20,loading_position=None,return_waypoints=[])))))
        self.engine = SquidExecution(self,self.config,command=self.command,clock=lambda:self.now)

    def physical_loading(self):
        self.loading=deepcopy(self.pose)
        self.state['stage_simulated']=False
        data=json.loads(self.config.read_text())
        data['profiles']['current'].update(loading_position=self.loading,
            loading_command='return_to_recorded_dropoff',stage_controller_serial='test-controller')
        self.config.write_text(json.dumps(data))
        self.pose['x_mm']+=20  # Selecting a saved imaging site moved the stage.

    def poll(self):
        return deepcopy(self.state)

    def command(self, command, params):
        self.calls.append((command,deepcopy(params)))
        if command == 'get_position':
            return deepcopy(self.pose)
        if command == 'get_stage_reference':
            return dict(controller_serial='test-controller',stage_simulated=False,
                        dropoff=self.loading,reference_hash='accepted',imaging_lifecycle_version=1,
                        scan_limits={'x_mm':[.1,100],'y_mm':[.1,100],'z_mm':[.05,6]})
        if command == 'prepare_confirmed_imaging':
            from squid_bridge.imaging_lifecycle import imaging_target
            self.pose=imaging_target(params['settings_yaml'],{'x_mm':[.1,100],'y_mm':[.1,100],'z_mm':[.05,6]})
            return dict(ok=True,position=self.pose)
        if command == 'return_to_recorded_dropoff':
            if self.on_loading:self.on_loading()
            self.pose=deepcopy(self.loading)
            return dict(ok=True)
        if command in ('get_current_acquisition_settings','get_current_acquisition_controls'):
            if self.selection_cleared and command=='get_current_acquisition_settings':
                raise ValueError('Select the wells or imaging locations in Squid first.')
            text=self.yaml
            if self.follow_stage:
                data=yaml.safe_load(text)
                data['wellplate_scan']['regions']=[dict(name='current',
                    center_mm=list(self.pose.values()),fovs=[[self.pose['x_mm'],self.pose['y_mm']]])]
                data['z_stack']['z_range_mm']=[self.pose['z_mm']]*2
                text=yaml.safe_dump(data)
            data=yaml.safe_load(text)
            if self.selection_cleared:
                if data['acquisition']['widget_type']=='wellplate':data['wellplate_scan']['regions']=[]
                else:data['flexible_scan']['positions']=[]
                text=yaml.safe_dump(data,sort_keys=True)
            fovs=0 if self.selection_cleared else 1
            nz=data['z_stack'].get('nz',1);nt=data.get('time_series',{}).get('nt',1)
            channels=[c['name'] for c in data['channels']]
            return dict(yaml=text,sha256=hashlib.sha256(text.encode()).hexdigest(),
                        summary=dict(channels=channels,fovs=fovs,nz=nz,nt=nt,total_images=fovs*nz*nt*len(channels)))
        if command in ('run_current_acquisition','run_acquisition_from_yaml'):
            if command=='run_acquisition_from_yaml':
                self.imaged_yaml=Path(params['yaml_path']).read_text()
                self.imaged_yamls.append(self.imaged_yaml)
                assert 'settings_sha256' not in params
            if self.failure:
                raise self.failure
            experiment = params['experiment_id']+'_native'
            self.acquisition_count+=1
            self.state.update(status='completed' if self.finish else 'running',
                completion_confirmed=self.finish,
                job=dict(experiment_id=experiment,run_id=f'run-{self.acquisition_count}',started_at=self.now+.01))
            if self.on_start:
                self.on_start()
            return dict(started=True,experiment_id=experiment)
        if command == 'abort_current_acquisition':
            assert params['experiment_id'] == self.state['job']['experiment_id']
            self.state.update(status='aborted',completion_confirmed=False)
            return dict(aborted=True)
        raise AssertionError(command)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.fake=FakeMicroscope(self.tmp.name);self.engine=self.fake.engine
        self.saved=[]
        self.save=lambda value:self.saved.append(deepcopy(value))

    def start(self):
        self.plan=self.engine.prepare()
        return self.engine.start(self.plan,Path(self.tmp.name),self.save,lambda:False)

    def test_exact_selected_settings_and_completed_job(self):
        ticket=self.start()
        result=self.engine.wait(self.plan,ticket,self.save,lambda:False,lambda state:None)
        self.assertTrue(result['ok']);self.assertEqual(result['run_id'],'run-1')
        self.assertEqual((Path(self.tmp.name)/'confirmed_acquisition.yaml').read_text(),self.fake.yaml)
        self.assertEqual(self.saved[0]['status'],'start_requested')
        self.assertEqual(self.saved[-1]['status'],'completed')
        self.assertTrue(self.engine.restore_loading(self.plan,ticket,self.save,lambda:False,lambda:None)['ok'])

    def test_selection_away_from_loading_is_read_only_until_confirmed_return(self):
        self.fake.physical_loading()
        with self.assertRaisesRegex(TeachingError,'loading position'):self.engine.prepare()
        plan=self.engine.prepare(allow_loading_return=True)
        self.assertFalse(any(c[0]=='return_to_recorded_dropoff' for c in self.fake.calls))
        with self.assertRaisesRegex(TeachingError,'loading position'):self.engine.verify(plan)
        home=Mock()
        self.engine.prepare_loading(plan,lambda:False,home)
        self.assertEqual(home.call_count,2)
        self.assertEqual(self.fake.pose,self.fake.loading)
        self.assertEqual(plan['profile']['captured_yaml'],self.fake.yaml)
        self.engine.prepare_imaging(plan,lambda:False,home)
        self.engine.start(plan,Path(self.tmp.name),self.save,lambda:False)

    def test_loading_return_requires_home_idle_same_settings_and_no_stop(self):
        self.fake.physical_loading();plan=self.engine.prepare(allow_loading_return=True)
        with self.assertRaisesRegex(TeachingError,'not Home'):
            self.engine.prepare_loading(plan,lambda:False,Mock(side_effect=TeachingError('not Home')))
        with self.assertRaisesRegex(TeachingError,'Stopped'):
            self.engine.prepare_loading(plan,lambda:True,lambda:None)
        self.fake.state['status']='running'
        with self.assertRaisesRegex(TeachingError,'already imaging'):
            self.engine.prepare_loading(plan,lambda:False,lambda:None)
        self.fake.state['status']='idle';self.fake.yaml+='changed: true\n'
        with self.assertRaisesRegex(TeachingError,'settings changed'):
            self.engine.verify(plan,check_position=False)
        self.assertFalse(any(c[0]=='return_to_recorded_dropoff' for c in self.fake.calls))

    def test_acquisition_refuses_loading_pose_until_scan_entry_verified(self):
        self.fake.physical_loading();plan=self.engine.prepare(allow_loading_return=True)
        self.fake.pose=deepcopy(self.fake.loading)
        with self.assertRaisesRegex(TeachingError,'position'):
            self.engine.start(plan,Path(self.tmp.name),self.save,lambda:False)
        self.assertFalse(any(c[0].startswith('run_') for c in self.fake.calls))
        with self.assertRaisesRegex(TeachingError,'not Home'):
            self.engine.prepare_imaging(plan,lambda:False,Mock(side_effect=TeachingError('not Home')))
        self.engine.prepare_imaging(plan,lambda:False,lambda:None)
        self.assertEqual(self.fake.pose,plan['profile']['scan_entry'])
        self.engine.start(plan,Path(self.tmp.name),self.save,lambda:False)

    def test_old_addon_is_blocked_before_movement(self):
        self.fake.physical_loading();command=self.engine.command
        def old(name,args):
            result=command(name,args)
            if name=='get_stage_reference':result.pop('imaging_lifecycle_version')
            return result
        self.engine.command=old
        with self.assertRaisesRegex(TeachingError,'updated Squid add-on'):self.engine.prepare(allow_loading_return=True)
        self.assertFalse(any(c[0].startswith('run_') for c in self.fake.calls))

    def test_saved_selection_survives_reload_and_empty_loading_gui(self):
        self.fake.physical_loading()
        original=self.engine.prepare(allow_loading_return=True)
        self.fake.pose=deepcopy(self.fake.loading);self.fake.selection_cleared=True
        engine=SquidExecution(self.fake,self.fake.config,command=self.fake.command,clock=lambda:self.fake.now)
        restored=engine.prepare(allow_loading_return=True)
        self.assertEqual(restored['profile']['selection_source']['kind'],'saved_coordinates')
        self.assertEqual(restored['profile']['captured_yaml'],original['profile']['captured_yaml'])
        self.assertEqual(restored['profile']['settings_capture_position'],original['profile']['settings_capture_position'])
        engine.verify(restored)
        self.assertFalse(any(c[0]=='return_to_recorded_dropoff' or c[0].startswith('run_') for c in self.fake.calls))
        self.fake.selection_cleared=False;self.fake.yaml+='new_selected_site: true\n'
        with self.assertRaisesRegex(TeachingError,'settings changed'):engine.verify(restored)
        fresh=engine.prepare(allow_loading_return=True)
        self.assertNotIn('selection_source',fresh['profile'])
        self.assertIn('new_selected_site',fresh['profile']['captured_yaml'])

    def test_locations_survive_restart_but_confirmed_plans_do_not(self):
        self.fake.physical_loading();self.engine.prepare(allow_loading_return=True)
        self.fake.pose=deepcopy(self.fake.loading);self.fake.selection_cleared=True
        self.fake.state['session']='replacement'
        restored=self.engine.prepare(allow_loading_return=True)
        self.assertEqual(restored['session'],'replacement')
        self.assertTrue(restored['profile']['selection_source']['across_restart'])
        self.fake.state['session']='session-1'
        with self.assertRaisesRegex(TeachingError,'session or simulation mode changed'):
            self.engine.verify(restored)
        original=self.engine.command
        self.engine.command=lambda cmd,args: (_ for _ in ()).throw(TimeoutError('bridge unavailable')) if cmd=='get_current_acquisition_settings' else original(cmd,args)
        with self.assertRaisesRegex(TeachingError,'bridge unavailable'):self.engine.prepare(allow_loading_return=True)
        self.assertFalse(any(c[0].startswith('run_') for c in self.fake.calls))

    def test_missing_xy_preserves_live_time_channels_and_z_through_execution(self):
        self.fake.physical_loading();self.engine.prepare(allow_loading_return=True)
        self.fake.pose=deepcopy(self.fake.loading);self.fake.selection_cleared=True
        live=yaml.safe_load(self.fake.yaml)
        live['time_series']=dict(nt=5,delta_t_s=2)
        live['channels']=[dict(name='BF',exposure_time=30),dict(name='second',exposure_time=40)]
        live['z_stack']=dict(nz=3,delta_z_mm=.001,z_range_mm=[1.2,1.202])
        self.fake.yaml=yaml.safe_dump(live)
        plan=self.engine.prepare(allow_loading_return=True)
        captured=yaml.safe_load(plan['profile']['captured_yaml'])
        for key in ('time_series','channels','z_stack'):
            self.assertEqual(captured[key],live[key])
        self.assertEqual(captured['wellplate_scan']['regions'][0]['fovs'],[[21,2]])
        self.assertEqual(plan['profile']['selected_settings']['total_images'],30)
        self.engine.verify(plan)
        self.engine.prepare_imaging(plan,lambda:False,lambda:None)
        self.engine.start(plan,Path(self.tmp.name),self.save,lambda:False)
        self.assertEqual(yaml.safe_load(self.fake.imaged_yaml),captured)

    def test_live_controls_change_before_yes_invalidates_recovered_plan(self):
        self.fake.physical_loading();self.engine.prepare(allow_loading_return=True)
        self.fake.pose=deepcopy(self.fake.loading);self.fake.selection_cleared=True
        plan=self.engine.prepare(allow_loading_return=True)
        live=yaml.safe_load(self.fake.yaml);live['time_series']['nt']=5
        self.fake.yaml=yaml.safe_dump(live)
        with self.assertRaisesRegex(TeachingError,'settings changed'):
            self.engine.verify(plan)
        self.assertFalse(any(c[0].startswith('run_') for c in self.fake.calls))

    def test_old_addon_cannot_substitute_old_acquisition_controls(self):
        self.fake.physical_loading();self.engine.prepare(allow_loading_return=True)
        self.fake.pose=deepcopy(self.fake.loading);self.fake.selection_cleared=True
        original=self.engine.command
        def missing(command,args):
            if command=='get_current_acquisition_controls':raise ValueError('Unknown command')
            return original(command,args)
        self.engine.command=missing
        with self.assertRaisesRegex(TeachingError,'No saved acquisition settings were substituted'):
            self.engine.prepare(allow_loading_return=True)
        self.assertFalse(any(c[0].startswith('run_') for c in self.fake.calls))

    def test_changed_xy_layout_or_tab_is_not_replaced_with_history(self):
        self.fake.physical_loading();self.engine.prepare(allow_loading_return=True)
        self.fake.pose=deepcopy(self.fake.loading);self.fake.selection_cleared=True
        live=yaml.safe_load(self.fake.yaml);live['wellplate_scan']['scan_size_mm']=5
        self.fake.yaml=yaml.safe_dump(live)
        with self.assertRaisesRegex(TeachingError,'XY layout'):
            self.engine.prepare(allow_loading_return=True)

    def test_recovered_xy_does_not_restore_old_per_field_z(self):
        from squid_bridge.selection_snapshot import recover_xy
        old=yaml.safe_load(self.fake.yaml)
        old['wellplate_scan']['regions'][0]['fovs']=[[21,2,3]]
        old['wellplate_scan']['regions'][0]['center_mm']=[21,2,3]
        live=deepcopy(old);live['wellplate_scan']['regions']=[]
        live['z_stack']['z_range_mm']=[1.2,1.2]
        text=yaml.safe_dump(live)
        current=dict(yaml=text,sha256=hashlib.sha256(text.encode()).hexdigest(),
                     summary=dict(channels=['BF'],fovs=0,nz=1,nt=1))
        merged=yaml.safe_load(recover_xy(current,yaml.safe_dump(old))['yaml'])
        self.assertEqual(merged['wellplate_scan']['regions'][0]['fovs'],[[21,2]])
        self.assertEqual(merged['z_stack']['z_range_mm'],[1.2,1.2])

    def test_migrate_confirmed_settings_only_not_old_motion_authorization(self):
        self.fake.physical_loading();original=self.engine.prepare(allow_loading_return=True)
        self.engine.selection_path.unlink()  # Isolated temporary test file.
        self.engine.locations_path.unlink()  # Exercise legacy workflow migration only.
        folder=Path(self.tmp.name)/'reports/autonomous_squid/previous';folder.mkdir(parents=True)
        (folder/'workflow.json').write_text(json.dumps(dict(status='stopped_or_failed',confirmed_at=999.,
            plan={'imaging':original})))
        self.fake.pose=deepcopy(self.fake.loading);self.fake.selection_cleared=True
        restored=self.engine.prepare(allow_loading_return=True)
        self.assertEqual(restored['profile']['selection_source']['captured_at'],999.)
        self.assertEqual(restored['profile']['captured_yaml'],original['profile']['captured_yaml'])
        self.assertNotIn('confirmed_at',restored)
        self.assertFalse(any(c[0].startswith('run_') for c in self.fake.calls))

    def test_no_saved_setup_has_actionable_error_and_no_fallback_away_from_loading(self):
        self.fake.physical_loading();self.fake.selection_cleared=True
        with self.assertRaisesRegex(TeachingError,'loading position'):self.engine.prepare(allow_loading_return=True)
        self.fake.pose=deepcopy(self.fake.loading)
        with self.assertRaisesRegex(TeachingError,'no saved setup'):self.engine.prepare(allow_loading_return=True)

    def test_saved_selection_tampering_refused(self):
        self.fake.physical_loading();self.engine.prepare(allow_loading_return=True)
        cache=json.loads(self.engine.selection_path.read_text())
        cache['plan']['profile']['captured_yaml']+='tampered: true\n'
        self.engine.selection_path.write_text(json.dumps(cache))
        self.fake.pose=deepcopy(self.fake.loading);self.fake.selection_cleared=True
        with self.assertRaisesRegex(TeachingError,'checksum changed'):self.engine.prepare(allow_loading_return=True)

    def test_location_archive_preserves_each_tab_and_records_reuse(self):
        self.fake.physical_loading()
        wellplate=self.fake.yaml
        self.engine.prepare(allow_loading_return=True)
        flexible=yaml.safe_load(wellplate)
        flexible['acquisition']['widget_type']='flexible'
        del flexible['wellplate_scan']
        flexible['flexible_scan']=dict(nx=1,ny=1,positions=[dict(name='site',center_mm=[30,4],fovs=[[30,4],[31,4]])])
        self.fake.yaml=yaml.safe_dump(flexible);self.fake.now+=1
        self.engine.prepare(allow_loading_return=True)
        self.fake.yaml=wellplate;self.fake.now+=1
        self.engine.prepare(allow_loading_return=True)
        self.fake.pose=deepcopy(self.fake.loading);self.fake.selection_cleared=True
        self.fake.state['session']='new-process'
        flexible['time_series']=dict(nt=5,delta_t_s=2)
        self.fake.yaml=yaml.safe_dump(flexible)
        plan=self.engine.prepare(allow_loading_return=True)
        self.assertEqual(plan['profile']['selected_settings']['total_images'],10)
        self.assertEqual(plan['profile']['scan_entry']['x_mm'],30)
        events=[json.loads(line) for line in self.engine.locations_path.read_text().splitlines()]
        self.assertEqual([e['event'] for e in events],['capture','capture','capture','reuse_proposed'])
        self.assertTrue(all(e['motion_authorized'] is False for e in events))
        self.assertTrue(events[-1]['source']['across_restart'])

    def test_different_controller_or_reference_never_reuses_locations(self):
        self.fake.physical_loading();self.engine.prepare(allow_loading_return=True)
        self.fake.pose=deepcopy(self.fake.loading);self.fake.selection_cleared=True
        for change in ('controller','reference'):
            with self.subTest(change=change):
                command=self.fake.command
                def changed(name,args):
                    value=command(name,args)
                    if name=='get_stage_reference':
                        value['controller_serial' if change=='controller' else 'reference_hash']='changed'
                    return value
                self.engine.command=changed
                with self.assertRaisesRegex(TeachingError,'controller|loading reference'):
                    self.engine.prepare(allow_loading_return=True)

    def test_preservation_before_loading_reads_only_and_retains_missing_sites(self):
        self.fake.physical_loading()
        self.assertTrue(self.engine.preserve_current_locations()['saved'])
        before=self.engine.locations_path.read_text()
        self.fake.pose=deepcopy(self.fake.loading);self.fake.selection_cleared=True
        self.assertFalse(self.engine.preserve_current_locations()['saved'])
        self.assertEqual(self.engine.locations_path.read_text(),before)
        self.assertFalse(any(name.startswith('run_') or name=='return_to_recorded_dropoff' for name,_ in self.fake.calls))

    def test_append_only_archive_corruption_is_refused(self):
        self.fake.physical_loading();self.engine.prepare(allow_loading_return=True)
        event=json.loads(self.engine.locations_path.read_text())
        event['record']['captured_at']+=100
        self.engine.locations_path.write_text(json.dumps(event)+'\n')
        self.fake.pose=deepcopy(self.fake.loading);self.fake.selection_cleared=True
        with self.assertRaisesRegex(TeachingError,'archive is unreadable or changed'):
            self.engine.prepare(allow_loading_return=True)

    def test_current_position_images_captured_site_not_loading_position(self):
        self.fake.physical_loading();self.fake.follow_stage=True
        self.fake.pose['z_mm']+=.5
        self.fake.yaml=yaml.safe_dump(dict(acquisition={'xy_mode':'Current Position','widget_type':'wellplate'},
            wellplate_scan={},z_stack={},channels=[{'name':'BF','exposure':20}]))
        original=deepcopy(self.fake.pose)
        plan=self.engine.prepare(allow_loading_return=True)
        self.engine.prepare_loading(plan,lambda:False,lambda:None)
        self.assertNotEqual(original,self.fake.pose)
        self.engine.prepare_imaging(plan,lambda:False,lambda:None)
        self.engine.start(plan,Path(self.tmp.name),self.save,lambda:False)
        imaged=yaml.safe_load(self.fake.imaged_yaml)
        self.assertEqual(imaged['wellplate_scan']['regions'][0]['fovs'],[[original['x_mm'],original['y_mm']]])
        self.assertEqual(imaged['z_stack']['z_range_mm'],[original['z_mm']]*2)
        self.fake.yaml=self.fake.yaml.replace('exposure: 20','exposure: 25')
        with self.assertRaisesRegex(TeachingError,'settings changed'):self.engine.verify(plan)

    def test_changed_gui_settings_stop_before_start(self):
        plan=self.engine.prepare();self.fake.yaml+='changed: true\n'
        with self.assertRaisesRegex(TeachingError,'settings changed'):
            self.engine.start(plan,self.tmp.name,self.save,lambda:False)
        self.assertFalse(any(c[0].startswith('run_') for c in self.fake.calls))

    def test_other_job_or_session_never_authorizes_retrieval(self):
        ticket=self.start();self.fake.state['job']['run_id']='replacement'
        ticket['run_id']='original'
        with self.assertRaisesRegex(TeachingError,'job changed'):
            self.engine.wait(self.plan,ticket,self.save,lambda:False,lambda state:None)
        self.fake.state['session']='other'
        with self.assertRaisesRegex(TeachingError,'session'):
            self.engine.observe(self.plan,ticket,self.save)

    def test_old_imaging_record_and_disconnect_stop(self):
        ticket=self.start();self.fake.state['job']['started_at']=999
        with self.assertRaisesRegex(TeachingError,'stale'):
            self.engine.wait(self.plan,ticket,self.save,lambda:False,lambda state:None)
        self.fake.state.update(connected=False,status='disconnected')
        with self.assertRaisesRegex(TeachingError,'unavailable'):
            self.engine.observe(self.plan,ticket,self.save)

    def test_failure_and_uncertain_start_no_retries(self):
        self.fake.failure=TimeoutError('response lost')
        with self.assertRaisesRegex(TeachingError,'start is uncertain'):
            self.start()
        self.assertEqual(self.saved[-1]['status'],'start_uncertain')
        self.assertEqual(sum(c[0]=='run_current_acquisition' for c in self.fake.calls),1)

    def test_stop_aborts_only_owned_job_once(self):
        self.fake.finish=False;ticket=self.start()
        with self.assertRaisesRegex(TeachingError,'stopped'):
            self.engine.wait(self.plan,ticket,self.save,lambda:True,lambda state:None)
        self.engine.abort_owned(self.plan,ticket,self.save)
        self.assertEqual(sum(c[0]=='abort_current_acquisition' for c in self.fake.calls),1)

    def test_timeout_has_no_retrieval_or_retry(self):
        self.fake.finish=False;ticket=self.start();self.fake.now+=21
        with self.assertRaisesRegex(TeachingError,'exceeded'):
            self.engine.wait(self.plan,ticket,self.save,lambda:False,lambda state:None)

    def test_wrong_holder_position_prevents_robot_retrieval(self):
        ticket=self.start()
        self.engine.wait(self.plan,ticket,self.save,lambda:False,lambda state:None)
        self.fake.pose['x_mm']+=1
        with self.assertRaisesRegex(TeachingError,'loading position'):
            self.engine.restore_loading(self.plan,ticket,self.save,lambda:False,lambda:None)

    def test_real_stage_with_mock_camera_needs_reviewed_loading_pose(self):
        self.fake.state['stage_simulated']=False
        with self.assertRaisesRegex(TeachingError,'reviewed physical'):
            self.engine.prepare()
        data=json.loads(self.fake.config.read_text())
        data['profiles']['current'].update(loading_position=self.fake.pose,stage_simulated=False)
        self.fake.config.write_text(json.dumps(data))
        plan=self.engine.prepare()
        self.assertTrue(plan['simulation'])
        self.assertFalse(plan['stage_simulated'])
        self.fake.state['stage_simulated']=True
        with self.assertRaisesRegex(TeachingError,'stage mode'):
            self.engine.prepare()

    def test_failed_acquisition_does_not_qualify(self):
        ticket=self.start();self.fake.state.update(status='failed',completion_confirmed=False)
        with self.assertRaises(TeachingError):
            self.engine.wait(self.plan,ticket,self.save,lambda:False,lambda state:None)


class WorkflowTests(unittest.TestCase):
    enable_transport=compound.CompoundTests.enable_transport
    finish=compound.CompoundTests.finish
    home_motion=compound.CompoundTests.home_motion
    confirm=compound.CompoundTests.confirm

    def setUp(self):
        compound.CompoundTests.setUp(self)
        self.travel=travel.SquidHandlingTests();self.travel.setUp()
        self.addCleanup(self.travel.doCleanups)
        self.backend=self.travel.backend;self.backend.run=self.run
        self.backend.camera_plate_only=lambda actions:None
        self.agent=LacryAgent(self.backend,Mock(),lambda:self.run,client=Mock(),classic_pickup=self.pickup)
        self.agent._needs_prepare=lambda plan:False
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.fake=FakeMicroscope(self.temp.name)
        self.workflow=AutonomousSquid(self.agent,self.fake.engine,Path(self.temp.name)/'workflows')
        self.agent.automatic=self.workflow

    def test_one_yes_runs_entire_chain_using_real_lua_routes(self):
        plan=self.agent.button('automatic_experiment')
        self.assertFalse(self.travel.s.robot.calls)
        result=self.confirm(plan)
        self.assertTrue(result['ok'],result)
        self.assertEqual(self.calls,['Calibrate','Align','Descend','Grip','Lift','Home'])
        self.assertEqual(self.travel.s.grips,[5.,3.7])
        self.assertEqual([c[1] for c in self.travel.s.robot.calls],([137]*3+[10]+[5]+[137]*4)*2)
        self.assertEqual(len(result['done']),len(plan['steps']))
        self.assertIsNone(self.agent.review)
        record=json.loads(self.workflow.active_record.read_text())
        self.assertEqual(record['status'],'completed')
        self.assertEqual(record['ticket']['run_id'],'run-1')
        with self.assertRaises(TeachingError):
            self.agent.confirm(dict(ready=True,plan_id=plan['id']))

    def finish_batch(self,plan):
        self.agent.confirm(dict(ready=True,plan_id=plan['id']))
        self.pickup.thread.join(30)
        self.assertFalse(self.pickup.thread.is_alive())
        return self.pickup.public()

    def test_twenty_cycles_one_yes_one_pickup_unique_jobs_and_files(self):
        self.fake.physical_loading()
        data=yaml.safe_load(self.fake.yaml);data['time_series']=dict(nt=5,delta_t_s=2)
        self.fake.yaml=yaml.safe_dump(data)
        def check_previous_cycle():
            record=json.loads(self.workflow.active_record.read_text())
            if self.fake.acquisition_count>1:
                self.assertEqual(record['cycles'][self.fake.acquisition_count-2]['status'],'completed')
        self.fake.on_start=check_previous_cycle
        plan=self.workflow.propose(repetitions=20)
        self.assertEqual(plan['repetitions'],20)
        self.assertFalse(self.calls);self.assertFalse(self.travel.s.robot.calls)
        result=self.finish_batch(plan)
        self.assertTrue(result['ok'],result)
        self.assertEqual(self.calls,['Calibrate','Align','Descend','Grip','Lift','Home'])
        self.assertEqual(self.travel.s.grips,[5.,3.7]*20)
        self.assertEqual(len(result['done']),len(plan['steps']))
        self.assertEqual(self.fake.acquisition_count,20)
        record=json.loads(self.workflow.active_record.read_text())
        self.assertEqual(record['completed_cycles'],20)
        self.assertTrue(all(c['status']=='completed' for c in record['cycles']))
        self.assertEqual(len({c['ticket']['request_id'] for c in record['cycles']}),20)
        self.assertEqual(len({c['ticket']['run_id'] for c in record['cycles']}),20)
        self.assertEqual(len(list(self.workflow.active_record.parent.glob('cycle_*/confirmed_acquisition.yaml'))),20)
        self.assertEqual(len(self.fake.imaged_yamls),20)
        self.assertTrue(all(yaml.safe_load(t)['time_series']['nt']==5 for t in self.fake.imaged_yamls))
        self.assertIsNone(self.agent.pending);self.assertIsNone(self.agent.review)
        self.assertEqual(self.agent.run_meta['completed_cycles'],20)
        self.assertFalse(self.run.reserved)

    def test_second_cycle_start_failure_stops_batch_without_retry_or_third_cycle(self):
        self.fake.on_start=lambda:setattr(self.fake,'failure',TimeoutError('second start uncertain'))
        result=self.finish_batch(self.workflow.propose(repetitions=3,pickup_from_calibration=False))
        self.assertFalse(result['ok'])
        self.assertIn('Cycle 2/3: Start Squid imaging',result['step'])
        self.assertEqual(self.travel.s.grips,[5.,3.7,5.])
        self.assertEqual(sum(name.startswith('run_') for name,_ in self.fake.calls),2)
        record=json.loads(self.workflow.active_record.read_text())
        self.assertEqual(record['completed_cycles'],1)
        self.assertEqual(record['failed_cycle'],2)
        self.assertEqual(record['cycles'][2]['status'],'not_started')
        self.assertEqual(self.calls,[])

    def test_previous_cycle_job_cannot_authorize_second_retrieval(self):
        first={}
        def on_start():
            if self.fake.acquisition_count==1:first.update(deepcopy(self.fake.state['job']))
            else:self.fake.state['job']=deepcopy(first)
        self.fake.on_start=on_start
        result=self.finish_batch(self.workflow.propose(repetitions=3,pickup_from_calibration=False))
        self.assertFalse(result['ok']);self.assertIn('Cycle 2/3',result['step'])
        self.assertEqual(self.travel.s.grips,[5.,3.7,5.])
        self.assertEqual(self.fake.acquisition_count,2)
        self.assertIn('different or stale',result['error'])

    def test_stop_during_second_cycle_prevents_third_and_aborts_owned_job(self):
        def on_start():
            if self.fake.acquisition_count==2:
                self.fake.state.update(status='running',completion_confirmed=False)
                self.agent.stop()
        self.fake.on_start=on_start
        result=self.finish_batch(self.workflow.propose(repetitions=3,pickup_from_calibration=False))
        self.assertFalse(result['ok'])
        self.assertEqual(self.fake.acquisition_count,2)
        self.assertEqual(self.travel.s.grips,[5.,3.7,5.])
        aborts=[args for name,args in self.fake.calls if name=='abort_current_acquisition']
        self.assertEqual(len(aborts),1)
        record=json.loads(self.workflow.active_record.read_text())
        self.assertEqual(aborts[0]['experiment_id'],record['cycles'][1]['ticket']['experiment_id'])
        self.assertNotEqual(aborts[0]['experiment_id'],record['cycles'][0]['ticket']['experiment_id'])
        self.assertFalse(self.run.reserved)

    def test_repetitions_validate_before_any_hardware_or_stale_plan(self):
        for value in (0,-1,True,1.5,'20',1001):
            self.agent.pending={'id':'old'}
            with self.assertRaisesRegex(TeachingError,'repetition count'):
                self.workflow.propose(repetitions=value)
            self.assertIsNone(self.agent.pending)
        with self.assertRaisesRegex(TeachingError,'require retrieval'):
            self.workflow.propose(repetitions=2,retrieve=False)
        self.assertFalse(self.calls);self.assertFalse(self.travel.s.robot.calls)

    def test_chat_count_is_one_compiled_batch_and_compact_confirmation(self):
        self.agent.credentials.model='fixture'
        self.agent.client.complete.side_effect=[
            dict(content=[dict(type='tool_use',id='batch',name='plan_squid_experiment',
                              input=dict(repetitions=2,pickup_from_calibration=False))]),
            dict(content=[dict(type='text',text='The full batch is ready.')])]
        self.agent.send('The plate is held at Home. Run the full Squid experiment 2 times.')
        plan=self.agent.pending
        self.assertEqual(plan['repetitions'],2)
        self.assertIn('One Yes starts all 2 cycles',self.agent.transcript[-1]['text'])
        self.assertNotIn('Cycle 2/2:',self.agent.transcript[-1]['text'])
        self.agent.send('Yes')
        self.pickup.thread.join(15)
        self.assertTrue(self.pickup.public()['ok'],self.pickup.public())
        self.assertEqual(self.fake.acquisition_count,2)
        self.assertEqual(self.agent.client.complete.call_count,1)
        self.assertEqual(self.calls,[])

    def test_held_plate_one_yes_no_calibration_or_teaching_draft(self):
        self.pickup.teaching.public=lambda:{}
        self.fake.physical_loading()
        plan=self.workflow.propose(pickup_from_calibration=False)
        self.assertFalse(self.calls);self.assertFalse(self.travel.s.robot.calls)
        self.assertEqual(plan['pickup_step_count'],0)
        self.assertNotIn('The instrument is not started', ' '.join(plan['requirements']))
        self.assertNotIn('remains in its taught loading position', ' '.join(plan['requirements']))
        self.assertEqual(plan['steps'][0]['label'],'Prepare Squid loading position')
        result=self.confirm(plan)
        self.assertTrue(result['ok'],result)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.travel.s.grips,[5.,3.7])
        self.assertEqual(len(self.travel.s.robot.calls),18)
        self.assertEqual(len(result['done']),len(plan['steps']))
        self.assertFalse(self.run.reserved)
        self.assertEqual(self.travel.e1,3.7)
        with self.assertRaises(TeachingError):self.agent.confirm(dict(ready=True,plan_id=plan['id']))

    def test_new_experiment_offers_saved_setup_then_one_yes_runs_complete_chain(self):
        self.fake.physical_loading();self.fake.engine.prepare(allow_loading_return=True)
        self.fake.pose=deepcopy(self.fake.loading);self.fake.selection_cleared=True
        plan=self.workflow.propose(pickup_from_calibration=False)
        self.assertIn('saved XY locations with current imaging settings',plan['summary'])
        self.assertIn('does not resume', ' '.join(plan['requirements']))
        self.assertFalse(self.travel.s.robot.calls)
        result=self.confirm(plan)
        self.assertTrue(result['ok'],result)
        self.assertEqual(self.travel.s.grips,[5.,3.7])
        self.assertEqual(self.calls,[])
        self.assertEqual(self.fake.imaged_yaml,plan['imaging']['profile']['captured_yaml'])

    def test_held_plate_changed_jaws_blocks_before_any_movement(self):
        plan=self.workflow.propose(pickup_from_calibration=False)
        self.travel.e1=5.
        with self.assertRaises(Exception):self.confirm(plan)
        self.assertFalse(self.calls);self.assertFalse(self.travel.s.robot.calls)
        self.assertFalse(any(c[0]=='return_to_recorded_dropoff' for c in self.fake.calls))

    def test_held_plate_imaging_failure_stops_before_retrieval(self):
        self.fake.failure=TimeoutError('imaging start uncertain')
        result=self.confirm(self.workflow.propose(pickup_from_calibration=False))
        self.assertFalse(result['ok']);self.assertEqual(result['step'],'Start Squid imaging')
        self.assertEqual(self.calls,[]);self.assertEqual(self.travel.s.grips,[5.])

    def test_chat_tool_supports_held_plate_workflow(self):
        self.agent.credentials.model='fixture'
        self.agent.client.complete.side_effect=[
            dict(content=[dict(type='tool_use',id='held',name='plan_squid_experiment',
                              input={'pickup_from_calibration':False,'retrieve':True})]),
            dict(content=[dict(type='text',text='Deliver, image and retrieve with one Yes.')])]
        self.agent.send('The plate is already held at Home. Drop at Squid, image, retrieve and return Home.')
        self.assertEqual(self.agent.pending['dispatch'],'autonomous_squid')
        self.assertFalse(self.agent.pending['pickup_from_calibration'])
        self.agent.send('Yes')
        self.assertTrue(self.finish()['ok'])
        self.assertEqual(self.calls,[])

    def test_selected_site_returns_stage_after_pickup_before_robot_delivery(self):
        self.fake.physical_loading()
        def first_return():
            self.assertEqual(self.calls,['Calibrate','Align','Descend','Grip','Lift','Home'])
            self.assertFalse(self.travel.s.robot.calls)
            self.fake.on_loading=None
        self.fake.on_loading=first_return
        plan=self.workflow.propose()
        result=self.confirm(plan)
        self.assertTrue(result['ok'],result)
        record=json.loads(self.workflow.active_record.read_text())
        self.assertEqual(record['events'][0]['step'],'Prepare Squid loading position')
        self.assertEqual(plan['imaging']['profile']['captured_yaml'],self.fake.yaml)

    def test_loading_failure_stops_before_delivery(self):
        self.fake.physical_loading()
        self.fake.on_loading=Mock(side_effect=TimeoutError('stage return uncertain'))
        result=self.confirm(self.workflow.propose())
        self.assertFalse(result['ok'])
        self.assertEqual(result['step'],'Prepare Squid loading position')
        self.assertFalse(self.travel.s.robot.calls)
        self.assertFalse(any(c[0].startswith('run_') for c in self.fake.calls))

    def test_loading_clears_current_site_but_confirmed_snapshot_runs_to_home(self):
        self.fake.physical_loading();self.fake.follow_stage=True
        self.fake.yaml=yaml.safe_dump(dict(acquisition={'xy_mode':'Current Position','widget_type':'wellplate'},
            wellplate_scan={},z_stack={},channels=[{'name':'BF','exposure':20}]))
        plan=self.workflow.propose(pickup_from_calibration=False)
        expected=plan['imaging']['profile']['captured_yaml']
        def clear_selection():
            self.fake.selection_cleared=True
            self.fake.yaml+='new_unconfirmed_setting: true\n'
        self.fake.on_loading=clear_selection
        result=self.confirm(plan)
        self.assertTrue(result['ok'],result)
        self.assertEqual(self.fake.imaged_yaml,expected)
        self.assertEqual(self.travel.s.grips,[5.,3.7])
        self.assertEqual(len(self.travel.s.robot.calls),18)
        # Preview and initial confirmation only; no regeneration during delivery,
        # acquisition start, post-scan loading return, or robot retrieval.
        self.assertEqual(sum(c[0]=='get_current_acquisition_settings' for c in self.fake.calls),2)

    def test_changed_confirmed_snapshot_stops_before_stage_or_robot_moves(self):
        self.fake.physical_loading()
        plan=self.workflow.propose(pickup_from_calibration=False)
        plan['imaging']['profile']['captured_yaml']+='tampered: true\n'
        with self.assertRaisesRegex(TeachingError,'snapshot changed'):
            self.workflow.start(plan)
        self.assertFalse(self.travel.s.robot.calls)
        self.assertFalse(any(c[0]=='return_to_recorded_dropoff' for c in self.fake.calls))

    def test_pickup_failure_prevents_delivery_and_imaging(self):
        self.fail='Grip';result=self.confirm(self.workflow.propose())
        self.assertFalse(result['ok']);self.assertFalse(self.travel.s.robot.calls)
        self.assertFalse(any(c[0].startswith('run_') for c in self.fake.calls))

    def test_delivery_imaging_can_leave_plate_at_squid(self):
        plan=self.workflow.propose(retrieve=False)
        self.assertIsNone(plan['retrieval'])
        result=self.confirm(plan)
        self.assertTrue(result['ok'],result)
        self.assertEqual(self.calls,['Calibrate','Align','Descend','Grip','Lift','Home'])
        self.assertEqual(self.travel.s.grips,[5.])
        self.assertEqual(len(self.travel.s.robot.calls),9)
        self.assertEqual(len(result['done']),len(plan['steps']))
        record=json.loads(self.workflow.active_record.read_text())
        self.assertEqual(record['status'],'completed')
        self.assertEqual(record['ticket']['run_id'],'run-1')
        self.assertIn('plate remains at Squid',result['message'])

    def test_imaging_failure_stops_at_home_no_retrieval(self):
        self.fake.failure=TimeoutError('lost start response')
        result=self.confirm(self.workflow.propose())
        self.assertFalse(result['ok']);self.assertEqual(result['step'],'Start Squid imaging')
        self.assertEqual(self.travel.s.grips,[5.])
        self.assertEqual(len(self.travel.s.robot.calls),9)

    def test_stop_in_start_wait_gap_cancels_owned_imaging(self):
        self.fake.finish=False;self.fake.on_start=lambda:self.agent.stop()
        result=self.confirm(self.workflow.propose())
        self.assertFalse(result['ok']);self.assertEqual(self.travel.s.grips,[5.])
        self.assertEqual(sum(c[0]=='abort_current_acquisition' for c in self.fake.calls),1)

    def test_no_other_motion_during_imaging_wait(self):
        entered,release=threading.Event(),threading.Event()
        self.fake.finish=False
        wait=self.fake.engine.wait
        def held_wait(*args):
            entered.set();self.assertTrue(release.wait(4))
            self.fake.state.update(status='completed',completion_confirmed=True)
            return wait(*args)
        self.fake.engine.wait=held_wait
        plan=self.workflow.propose();self.agent.confirm(dict(ready=True,plan_id=plan['id']))
        self.assertTrue(entered.wait(4))
        self.assertFalse(self.run.start('other',lambda run:dict(ok=True))['ok'])
        with self.assertRaises(TeachingError):self.agent.link('squid')
        release.set();self.assertTrue(self.finish()['ok'])

    def test_changed_settings_before_yes_block_all_motion(self):
        plan=self.workflow.propose();self.fake.yaml+='new: settings\n'
        with self.assertRaisesRegex(TeachingError,'settings changed'):self.confirm(plan)
        self.assertFalse(self.calls);self.assertFalse(self.travel.s.robot.calls)

    def test_missing_bridge_does_not_leave_an_older_partial_plan(self):
        self.agent.pending=dict(id='old-home-only')
        self.fake.engine.prepare=Mock(side_effect=TeachingError('Load the settings add-on'))
        with self.assertRaisesRegex(TeachingError,'add-on'):self.workflow.propose()
        self.assertIsNone(self.agent.pending);self.assertFalse(self.calls)

    def test_unfinished_journal_never_resumes(self):
        folder=self.workflow.folder/'previous';folder.mkdir(parents=True)
        (folder/'workflow.json').write_text(json.dumps(dict(status='running')))
        with self.assertRaisesRegex(TeachingError,'no recorded ending'):self.workflow.propose()
        self.assertFalse(self.calls)

    def test_chat_uses_complete_experiment_tool_then_one_yes(self):
        self.agent.credentials.model='fixture'
        self.agent.client.complete.side_effect=[
            dict(content=[dict(type='tool_use',id='all',name='plan_squid_experiment',input={})]),
            dict(content=[dict(type='text',text='The complete experiment is ready.')])]
        self.agent.send('Calibrate, drop at Squid, image and retrieve after imaging finishes')
        self.assertEqual(self.agent.pending['dispatch'],'autonomous_squid')
        self.agent.send('Yes')
        self.assertTrue(self.finish()['ok'])


if __name__=='__main__':unittest.main()
