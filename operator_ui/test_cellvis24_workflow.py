"""Offline repeatability tests using real geometry checks and fake hardware."""
import json
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock,patch

import cellvis24_workflow as w
from autonomy import TransferError
from home_squid_transfer import checked
from trajectory_queue import prepare_points


class WorkflowTests(unittest.TestCase):
    def test_hamilton_open_jaw_descents_fast_contact_moves_still_slow(self):
        steps=w.compile_steps(['hamilton'],1)
        for label in ('Hamilton open-jaw pickup descent','Empty connector to station route'):
            s=next(x for x in steps if x['label']==label)
            self.assertEqual(s['speed'],137)
            self.assertTrue(s['flags']['home_speed137'])
        for label in ('Proof lift5mm','Reseat in HOME'):
            self.assertEqual(next(x for x in steps if x['label']==label)['speed'],5)

    def setUp(self):
        self.g=w.geometry();d=json.loads((w.EVIDENCE/'squid_release_home.json').read_bytes())
        d['finished_at']=time.time();self.state=deepcopy(d['final']);self.e1=28;self.angle=1.77
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
        self.source=self.folder/'squid_release_home.json';self.source.write_text(json.dumps(d))
        self.moves=[];self.grips=[];self.stall=False
        self.service=Mock();self.service.envelope=self.g['envelope'];self.service._locked.side_effect=lambda f:f()
        self.service.program.return_value={'ok':True};self.service._hostpoint.side_effect=self.host
        self.service.move_gripper.side_effect=self.grip
        self.service.torque_report.side_effect=lambda:dict(ok=True,telemetry_live=True,e1_position=self.e1,e1_torque=-100)
        self.run=Mock();self.run.stopped.return_value=False
        for p in [patch.object(w,'EVIDENCE',self.folder),patch.object(w,'RUNS',self.folder/'runs'),
                  patch.object(w,'preflight',side_effect=lambda s:deepcopy(self.state)),
                  patch.object(w,'native',side_effect=lambda s:dict(moving=False,external_axes={'E1':self.e1,'E2':self.angle})),
                  patch.object(w,'hamilton_ready'),patch.object(w,'squid_ready'),patch.object(w.time,'sleep')]:
            p.start();self.addCleanup(p.stop)
        p=patch.object(w,'LuaTrajectory');self.lua=p.start();self.addCleanup(p.stop)
        self.lua.return_value.capability.return_value={'available':True,'version':220109}
        self.lua.return_value.execute.side_effect=self.queue

    def host(self,params,mode,timeout):
        self.assertEqual(self.e1,28)
        self.assertGreaterEqual(self.state['pose_mm']['Z'],105.7)
        if mode==13:self.service.robot.get_sys_var_i.return_value={7:params[7],8:250104}
        elif mode==14:self.angle=params[9]
        else:raise AssertionError(mode)
        return dict(ok=True)

    def grip(self,target,speed):
        self.grips.append((target,speed));self.e1=target+.25 if self.stall and target<28 else target
        return dict(ok=True,gripper={'grip_detected':target<28,'e1_position':target+.221})

    def queue(self,run,start,joints,points,cfg,speed,progress,**flags):
        prepare_points(start,joints,points,cfg,**{k:v for k,v in flags.items() if k not in ('segment_speeds','home_speed137')})
        self.moves.append((deepcopy(points),speed,flags,self.e1))
        if flags.get('hamilton_short_side'):
            from cellvis24_rack_route import validate_route
            q=validate_route(start,points,joints,cfg,self.g['envelope'],flags['hamilton_short_side'])
        else:q=checked(start,points,joints,cfg,self.g['envelope'])
        self.state.update(pose_mm=deepcopy(points[-1]),joints=q)
        progress('motion',100,100);return dict(ok=True)

    def test_two_combined_cycles_preserve_routes_grip_and_unique_receipts(self):
        p=w.plan(self.service,self.g['cfg'],['hamilton','squid'],2,self.source)
        result=w.execute(self.run,self.service,self.g['cfg'],p)
        self.assertEqual(result['completed_cycles'],2);self.assertEqual(self.e1,28)
        self.assertAlmostEqual(self.state['pose_mm']['Z'],105.72)
        fast=[m for m in self.moves if len(m[0])>1]
        self.assertEqual(len(fast),16)
        for points,speed,flags,e1 in fast:
            self.assertEqual(speed,137)
            self.assertIn(5,flags['segment_speeds'])
        self.assertTrue(all(speed==5 for target,speed in self.grips if target in (3.9,25,7,28)))
        self.assertTrue(all(speed==10 for target,speed in self.grips if target in (4.9,26)))
        self.service.program.assert_not_called()
        with self.assertRaises(TransferError):w.plan(self.service,self.g['cfg'],['squid'],1,self.source)
        next_plan=w.plan(self.service,self.g['cfg'],['squid'],1,result['record'])
        self.assertNotEqual(next_plan['id'],p['id'])

    def test_grip_stall_stops_before_lift_or_station_transfer(self):
        self.stall=True;p=w.plan(self.service,self.g['cfg'],['squid'],1,self.source)
        with self.assertRaises(TransferError):w.execute(self.run,self.service,self.g['cfg'],p)
        self.assertEqual(len(self.grips),1)
        self.assertAlmostEqual(self.state['pose_mm']['Z'],75.72)
        self.service.program.assert_called_once_with('stop')
        with self.assertRaises(TransferError):w.source_record()

    def test_grip_or_holder_mismatch_prevents_dispatch(self):
        self.e1=3.9
        with self.assertRaises(TransferError):w.plan(self.service,self.g['cfg'],['squid'],1,self.source)
        self.e1=28;self.angle=5
        with self.assertRaises(TransferError):w.plan(self.service,self.g['cfg'],['squid'],1,self.source)
        self.assertFalse(self.moves);self.assertFalse(self.grips)

    def test_changed_approved_route_blocks_all_motion(self):
        p=w.plan(self.service,self.g['cfg'],['squid'],1,self.source)
        next(s for s in p['steps'] if s['kind']=='queue')['points'][0]['X']+=1
        with self.assertRaises(TransferError):w.execute(self.run,self.service,self.g['cfg'],p)
        self.assertFalse(self.moves);self.assertFalse(self.grips)


class CliTests(unittest.TestCase):
    def test_calibration_only_preview_has_no_station_transfer(self):
        from run_cellvis24_workflow import main,parse_args
        with patch('run_cellvis24_workflow.api',side_effect=AssertionError('No API')),patch('builtins.print') as output:
            main(['--full-calibration'])
        d=json.loads(output.call_args.args[0])
        self.assertEqual(d['stations'],[])
        self.assertEqual({s['station'] for s in d['steps']},{'calibration'})
        self.assertEqual(d['calibration_runs'],1)
        with patch('sys.stderr'),self.assertRaises(SystemExit):parse_args(['--full-calibration','--cycles','5'])

    def test_full_calibration_preview_once_for_five_handling_cycles(self):
        from run_cellvis24_workflow import main
        with patch('run_cellvis24_workflow.api',side_effect=AssertionError('No API')),patch('builtins.print') as output:
            main(['--full-calibration','--home-to-hamilton-roundtrip','--home-to-squid-roundtrip','--cycles','5'])
        d=json.loads(output.call_args.args[0])
        self.assertEqual(d['calibration_runs'],1)
        self.assertEqual(sum(s['kind']=='vision' for s in d['steps']),1)
        self.assertEqual({s['cycle'] for s in d['steps']},{0,1,2,3,4,5})

    def test_failed_calibration_preparation_never_starts_handling(self):
        from run_cellvis24_workflow import main
        with patch('run_cellvis24_workflow.prepare_calibration',side_effect=RuntimeError('Restore failed')),patch('run_cellvis24_workflow.api') as api:
            with self.assertRaises(RuntimeError):main(['--full-calibration','--home-to-hamilton-roundtrip','--cycles','5','--execute'])
        api.assert_not_called()

    def test_preview_never_contacts_controller(self):
        from run_cellvis24_workflow import main
        with patch('run_cellvis24_workflow.api',side_effect=AssertionError('No API for offline preview')),patch('builtins.print') as output:
            main(['--cycles','2'])
        data=json.loads(output.call_args.args[0]);self.assertFalse(data['motion_started']);self.assertEqual(data['calibration_runs'],0)

    def test_uncertain_dispatch_requests_stop_once_without_resend(self):
        from run_cellvis24_workflow import main
        calls=[]
        def api(path,body=None):
            calls.append(path)
            if path.endswith('/preview'):return {'plan':{'id':'test'}}
            if path.endswith('/start'):raise TimeoutError('Acknowledgement lost')
            return {'ok':True}
        with patch('run_cellvis24_workflow.api',side_effect=api):
            with self.assertRaises(TimeoutError):main(['--execute'])
        self.assertEqual(calls,['developer/api/cellvis24-workflow/preview','developer/api/cellvis24-workflow/start','seq/stop'])

    def test_explicit_start_rejection_does_not_stop_other_work(self):
        from run_cellvis24_workflow import main,ApiRejected
        calls=[]
        def api(path,body=None):
            calls.append(path)
            if path.endswith('/preview'):return {'plan':{'id':'test'}}
            raise ApiRejected('Another sequence owns the arm')
        with patch('run_cellvis24_workflow.api',side_effect=api):
            with self.assertRaises(ApiRejected):main(['--execute'])
        self.assertEqual(len(calls),2)


class FullCalibrationTests(WorkflowTests):
    def test_residual_contact_deflection_corrects_only_after_release_and_clearance(self):
        self.setup_calibration();old_queue=self.queue;commands=[]
        def queue(*args,**kwargs):
            result=old_queue(*args,**kwargs)
            if self.e1<28:self.angle=1.732844
            return result
        self.lua.return_value.execute.side_effect=queue
        old_host=self.host
        def host(params,mode,timeout):
            if mode==14:commands.append(dict(e1=self.e1,pose=deepcopy(self.state['pose_mm']),target=params[9]))
            return old_host(params,mode,timeout)
        self.service._hostpoint.side_effect=host
        p=w.plan(self.service,self.g['cfg'],[],1,full_calibration=True)
        result=w.execute(self.run,self.service,self.g['cfg'],p,cam=Mock())
        self.assertTrue(result['ok']);self.assertEqual(len(commands),1)
        self.assertEqual(commands[0]['e1'],28);self.assertEqual(commands[0]['pose']['Z'],105.72)
        self.assertEqual(commands[0]['target'],1.77);self.service.program.assert_not_called()

    def test_uncertain_holder_correction_stops_without_retry(self):
        self.setup_calibration();old_queue=self.queue;commands=[]
        def queue(*args,**kwargs):
            result=old_queue(*args,**kwargs)
            if self.e1<28:self.angle=1.732844
            return result
        self.lua.return_value.execute.side_effect=queue
        old_host=self.host
        def host(params,mode,timeout):
            if mode==14:
                commands.append(mode)
                return dict(ok=False,error='uncertain response')
            return old_host(params,mode,timeout)
        self.service._hostpoint.side_effect=host
        p=w.plan(self.service,self.g['cfg'],[],1,full_calibration=True)
        with self.assertRaises(TransferError):w.execute(self.run,self.service,self.g['cfg'],p,cam=Mock())
        self.assertEqual(commands,[14]);self.service.program.assert_called_once_with('stop')

    def test_contact_deflection_does_not_stop_but_settles_before_next_pickup(self):
        self.setup_calibration()
        def contact_native(service):
            angle=1.732844 if self.e1<28 else self.angle
            return dict(moving=False,external_axes={'E1':self.e1,'E2':angle})
        with patch.object(w,'native',side_effect=contact_native):
            p=w.plan(self.service,self.g['cfg'],[],1,full_calibration=True)
            result=w.execute(self.run,self.service,self.g['cfg'],p,cam=Mock())
        d=json.loads(Path(result['record']).read_bytes())
        self.assertTrue(d['holder_contact_deflections']);self.assertEqual(self.e1,28)
        self.service.program.assert_not_called()

    def test_calibration_only_executes_proof_reseat_release_without_stations(self):
        align,capture=self.setup_calibration()
        p=w.plan(self.service,self.g['cfg'],[],1,full_calibration=True)
        self.assertEqual({s['station'] for s in p['steps']},{'calibration'})
        result=w.execute(self.run,self.service,self.g['cfg'],p,cam=Mock())
        d=json.loads(Path(result['record']).read_bytes())
        self.assertEqual(d['calibration_runs'],1)
        self.assertEqual(d['completed_cycles'],0)
        self.assertEqual(d['payload'],'empty')
        self.assertEqual(self.e1,28)
        self.assertAlmostEqual(self.state['pose_mm']['Z'],105.72)
        capture.assert_called_once();align.assert_called_once()
        w.hamilton_ready.assert_not_called();w.squid_ready.assert_not_called()
        self.assertFalse(any(m[2].get('hamilton_short_side') or m[2].get('squid_queue') for m in self.moves))
        with self.assertRaises(TransferError):w.plan(self.service,self.g['cfg'],[],1)
        with self.assertRaises(TransferError):w.plan(self.service,self.g['cfg'],[],2,full_calibration=True)

    def setup_calibration(self):
        import cellvis24_calibration as c
        from autonomy import alignment_plan
        original=w.ROOT/'operator_ui/reports/plate_session/cellvis24_validation'
        self.state=deepcopy(json.loads((original/'observation_plan.json').read_bytes())['start_state']['robot'])
        def align(run,service,target,hover,translation_speed=5):
            self.assertEqual(translation_speed,15)
            points=alignment_plan(self.state['pose_mm'],target,self.state['joints'],self.g['cfg'],self.g['envelope'],hover)
            q=checked(self.state['pose_mm'],points,self.state['joints'],self.g['cfg'],self.g['envelope'])
            self.state.update(pose_mm=points[-1],joints=q)
            return dict(ok=True)
        p=patch('sequences.seq_align',side_effect=align);a=p.start();self.addCleanup(p.stop)
        p=patch.object(c,'capture');capture=p.start();self.addCleanup(p.stop)
        return a,capture

    def test_calibration_once_then_five_complete_cycles(self):
        align,capture=self.setup_calibration()
        p=w.plan(self.service,self.g['cfg'],['hamilton','squid'],5,full_calibration=True)
        result=w.execute(self.run,self.service,self.g['cfg'],p,cam=Mock())
        d=json.loads(Path(result['record']).read_bytes())
        self.assertEqual(d['calibration_runs'],1);self.assertEqual(d['completed_cycles'],5)
        capture.assert_called_once();align.assert_called_once()
        self.assertEqual(self.grips[:3],[(4.9,10),(3.9,5),(28,5)])
        self.assertEqual(d['payload'],'empty');self.assertAlmostEqual(self.state['pose_mm']['Z'],105.72)
        self.service.program.assert_not_called()

    def test_camera_rejection_stops_before_alignment_grip_or_transfer(self):
        align,capture=self.setup_calibration();capture.side_effect=TransferError('Plate moved')
        p=w.plan(self.service,self.g['cfg'],['hamilton','squid'],5,full_calibration=True)
        with self.assertRaises(TransferError):w.execute(self.run,self.service,self.g['cfg'],p,cam=Mock())
        align.assert_not_called();self.assertFalse(self.grips)
        self.assertEqual(len(self.moves),1);self.service.program.assert_called_once_with('stop')

    def test_original_holder_required_before_camera_approach(self):
        self.setup_calibration();self.angle=90.71
        with self.assertRaises(TransferError):w.plan(self.service,self.g['cfg'],['squid'],1,full_calibration=True)
        self.assertFalse(self.moves)


class CameraReferenceTests(unittest.TestCase):
    def test_holder_monitor_accepts_recorded_drift_and_retains_bounds(self):
        from calibration_e2 import TARGET_DEGREES
        self.assertEqual(TARGET_DEGREES,1.77)
        for value in (1.74,1.749324037839865,1.77,1.82):
            self.assertTrue(w.angle_ok(value,TARGET_DEGREES))
        for value in (1.739999,1.820001,float('nan'),float('inf')):
            self.assertFalse(w.angle_ok(value,TARGET_DEGREES))

    def test_saved_cellvis_frame_uses_the_same_rim_and_grid_math(self):
        import cv2
        from cellvis24_calibration import reference,ROOT,OBSERVATION,assess
        from cellvis24_observation import measure,teach
        d=reference();source=ROOT/d['files']['observation']['path']
        frame=cv2.imread(str(source.with_name('median_0.png')))
        seed=json.loads((ROOT/d['files']['seed']['path']).read_bytes())['fitted']
        disks=json.loads((ROOT/d['files']['disks']['path']).read_bytes())
        cfg=next(c for c in teach._configs() if c['name']=='Wide')
        m=measure(frame,seed,disks,OBSERVATION,cfg,rim_sample_span=d['rim_sample_span'],rim_tangent_radius=d['rim_tangent_radius'])
        self.assertTrue(assess([deepcopy(m) for _ in range(3)])['accepted_reference_reused'])

    def test_accepted_bursts_pass_and_moved_plate_and_bad_grid_fail(self):
        from cellvis24_calibration import assess,reference,ROOT
        d=reference()
        accepted=[b['measurement'] for b in d['reference_reproduction']]
        self.assertTrue(assess(accepted)['accepted_reference_reused'])
        for kind in ('moved','yaw','grid','nan'):
            with self.subTest(kind=kind):
                samples=deepcopy(accepted)
                for m in samples:
                    if kind=='moved':m['target']['x']+=1
                    if kind=='yaw':m['target']['rz']+=1
                    if kind=='grid':m['measured_wells']=10
                    if kind=='nan':m['target']['x']=float('nan')
                with self.assertRaises(TransferError):assess(samples)


if __name__=='__main__':unittest.main()
