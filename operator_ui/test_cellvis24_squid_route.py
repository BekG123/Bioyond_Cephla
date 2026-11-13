"""Offline Cellvis Squid sequencing, stage checks and real Lua protocol tests."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
from autonomy import TransferError
import cellvis24_squid_route as trial
from home_squid_transfer import checked


class SquidHandlingTests(unittest.TestCase):
    def setUp(self):
        self.g=trial.geometry();original=trial.FOLDER
        data=json.loads((original/'home_short_release.json').read_bytes())
        self.state=deepcopy(data['final']);self.e1=28;self.angle=90.71386;self.jaws=[];self.moves=[]
        self.contact_hint=False;self.stall=False
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
        (self.folder/'home_short_release.json').write_text(json.dumps(data))
        self.svc=Mock();self.svc.envelope=self.g['envelope'];self.svc.program.return_value={'ok':True}
        self.svc._locked.side_effect=lambda fn:fn();self.svc._hostpoint.side_effect=self.host
        self.svc.pose_mm.side_effect=lambda:deepcopy(self.state['pose_mm'])
        self.svc.move_gripper.side_effect=self.jaw
        self.svc.torque_report.side_effect=lambda:dict(ok=True,telemetry_live=True,e1_position=self.e1,e1_torque=-100)
        self.run=Mock();self.run.stopped.return_value=False
        for p in [patch.object(trial,'FOLDER',self.folder),patch.object(trial,'preflight',side_effect=lambda svc:deepcopy(self.state)),
                  patch.object(trial,'native',side_effect=lambda svc:dict(moving=False,external_axes={'E1':self.e1,'E2':self.angle})),
                  patch.object(trial,'instrument_ready',return_value=self.g['squid_loading_position']),patch.object(trial.time,'sleep')]:
            p.start();self.addCleanup(p.stop)
        p=patch('trajectory_queue.LuaTrajectory');self.lua=p.start();self.addCleanup(p.stop)
        self.lua.return_value.capability.return_value={'available':True,'version':220109}
        self.lua.return_value.execute.side_effect=self.queue

    def host(self,params,mode,timeout):
        if mode==13:self.svc.robot.get_sys_var_i.return_value={7:params[7],8:250104}
        elif mode==14:self.angle=params[9]
        else:raise AssertionError(mode)
        return {'ok':True}

    def jaw(self,target,speed):
        self.jaws.append((target,speed));self.e1=target+.221 if self.stall else target
        return {'ok':True,'gripper':{'grip_detected':self.contact_hint,'e1_position':target+.221}}

    def queue(self,run,start,joints,points,cfg,speed,progress,**flags):
        from trajectory_queue import prepare_points
        prepare_points(start,joints,points,cfg,**{k:v for k,v in flags.items() if k in ('reviewed','home_transit','squid_queue','vertical_runs')})
        q=checked(start,points,joints,cfg,self.g['envelope'])
        self.moves.append((deepcopy(points),speed,flags));self.state.update(pose_mm=deepcopy(points[-1]),joints=q)
        progress('done',1,1);return {'ok':True}

    def execute(self,phase):
        p=trial.plan(self.svc,self.g['cfg'],phase)
        return trial.execute(self.run,self.svc,self.g['cfg'],p)

    def accept(self,name,source):
        (self.folder/name).write_text(json.dumps(dict(accepted=True,source_sha256=hashlib.sha256((self.folder/source).read_bytes()).hexdigest())))

    def test_full_phase_order_preserves_grip_policy_and_waits_for_support(self):
        result=self.execute('deliver');self.assertEqual(result['payload'],'held')
        self.assertEqual(self.angle,1.77);self.assertEqual(self.jaws,[(4.9,10),(3.9,5)])
        with self.assertRaises(FileNotFoundError):self.execute('release_squid')
        self.accept('squid_seating_acceptance.json','squid_deliver.json')
        self.execute('release_squid');self.execute('empty_return');self.execute('retrieve')
        self.assertEqual(self.e1,3.9);self.assertAlmostEqual(self.state['pose_mm']['Z'],75.72)
        with self.assertRaises(FileNotFoundError):self.execute('release_home')
        self.accept('squid_HOME_return_acceptance.json','squid_retrieve.json')
        self.execute('release_home');self.assertEqual(self.e1,28)
        self.assertAlmostEqual(self.state['pose_mm']['Z'],105.72)
        self.assertEqual(self.jaws,[(4.9,10),(3.9,5),(7,5),(4.9,10),(3.9,5),(28,5)])

    def test_uncertain_queue_stops_and_blocks_retry(self):
        self.lua.return_value.execute.side_effect=TransferError('Uncertain queue')
        with self.assertRaises(TransferError):self.execute('deliver')
        self.svc.program.assert_called_once_with('stop')
        with self.assertRaises(TransferError):self.execute('deliver')
        self.assertEqual(self.lua.return_value.execute.call_count,1)

    def test_early_contact_hint_with_settled_feedback_matches_reference_grip(self):
        self.contact_hint=True
        result=self.execute('deliver')
        self.assertEqual(result['payload'],'held')
        self.assertEqual(self.jaws,[(4.9,10),(3.9,5)])
        self.svc.program.assert_not_called()

    def test_persistent_position_error_stops_before_lift(self):
        self.contact_hint=True;self.stall=True
        with self.assertRaises(TransferError):self.execute('deliver')
        self.assertEqual(len(self.jaws),1)
        self.assertAlmostEqual(self.state['pose_mm']['Z'],75.72)
        self.svc.program.assert_called_once_with('stop')

    def prepare_continuation(self):
        self.state.update(pose_mm=deepcopy(self.g['seat']),joints=deepcopy(self.g['start_joints']))
        self.angle=1.914
        failed=self.folder/'squid_deliver.json'
        failed.write_text(json.dumps(dict(status='failed_or_uncertain',error='Uncertain grip/opening; no retry or lift.')))
        opening=self.folder/'authorized_open_test.json'
        opening.write_text(json.dumps(dict(status='opened_verified',target_e1=28,after={'robot':self.state})))
        authorization=dict(status='released_after_review',operator_requested_continuation=True,
            failed_sha256=trial.digest(failed),opening_file=opening.name,opening_sha256=trial.digest(opening),final=self.state)
        (self.folder/'squid_continuation_authorization.json').write_text(json.dumps(authorization))

    def test_explicit_continuation_retreats_before_rotation_preserves_failure(self):
        self.prepare_continuation();failed=(self.folder/'squid_deliver.json').read_bytes()
        original=self.host
        def host(params,mode,timeout):
            if mode==14:
                self.assertEqual(self.e1,28)
                self.assertAlmostEqual(self.state['pose_mm']['Z'],self.g['clearance']['Z'])
            return original(params,mode,timeout)
        self.svc._hostpoint.side_effect=host
        self.assertEqual(self.execute('continue_delivery')['payload'],'held')
        self.assertEqual((self.folder/'squid_deliver.json').read_bytes(),failed)
        self.assertEqual(self.moves[0][1],5)
        self.accept('squid_seating_acceptance.json','squid_continue_delivery.json')
        self.execute('release_squid')
        self.assertEqual(self.e1,7)

    def test_changed_recovery_receipt_blocks_all_motion(self):
        self.prepare_continuation()
        (self.folder/'authorized_open_test.json').write_text('{}')
        with self.assertRaises(TransferError):self.execute('continue_delivery')
        self.assertFalse(self.moves);self.assertFalse(self.jaws)

    def test_empty_clearance_recovery_requires_payload_confirmation_and_keeps_failure(self):
        self.state.update(pose_mm=deepcopy(self.g['points'][0]),joints=deepcopy(self.g['start_joints']))
        self.state['joints']['J1']+=self.g['points'][0]['Z']-self.g['proof']['Z']
        self.angle=1.7658
        failed=self.folder/'squid_continue_delivery.json'
        failed.write_text(json.dumps(dict(status='failed_or_uncertain',error='Squid vertical motion exceeded reviewed height')))
        data=dict(status='empty_open_after_review',failed_sha256=trial.digest(failed),final=self.state,
                  native={'external_axes':{'E1':28}},operator_confirmed_plate_in_holder_jaws_empty=False)
        auth=self.folder/'squid_clearance_recovery_authorization.json'
        auth.write_text(json.dumps(data))
        with self.assertRaises(TransferError):self.execute('deliver_after_clearance_stop')
        self.assertFalse(self.moves)
        data['operator_confirmed_plate_in_holder_jaws_empty']=True;auth.write_text(json.dumps(data))
        original=failed.read_bytes()
        self.assertEqual(self.execute('deliver_after_clearance_stop')['payload'],'held')
        self.assertEqual(failed.read_bytes(),original)
        self.accept('squid_seating_acceptance.json','squid_deliver_after_clearance_stop.json')
        self.execute('release_squid');self.assertEqual(self.e1,7)

    def test_connector_recovery_exercises_actual_queue_geometry_checks(self):
        self.state.update(pose_mm=deepcopy(self.g['points'][0]),joints=deepcopy(self.g['start_joints']))
        self.state['joints']['J1']+=self.g['points'][0]['Z']-self.g['proof']['Z'];self.angle=1.77
        failed=self.folder/'squid_deliver_after_clearance_stop.json'
        failed.write_text(json.dumps(dict(status='failed_or_uncertain',error='Queued path segment exceeds the reviewed step size.')))
        data=dict(status='empty_open_after_review',failed_sha256=trial.digest(failed),final=self.state,
                  native={'external_axes':{'E1':28}},operator_confirmed_plate_in_holder_jaws_empty=True)
        (self.folder/'squid_connector_recovery_authorization.json').write_text(json.dumps(data))
        self.assertEqual(self.execute('deliver_after_connector_check')['payload'],'held')
        self.assertTrue(self.moves[0][2]['vertical_runs'])
        self.accept('squid_seating_acceptance.json','squid_deliver_after_connector_check.json')
        self.execute('release_squid');self.execute('empty_return');self.execute('retrieve')
        self.accept('squid_HOME_return_acceptance.json','squid_retrieve.json');self.execute('release_home')
        self.assertEqual(self.e1,28)


class SquidRouteTests(unittest.TestCase):
    def test_cellvis_height_monitor_keeps_vertical_and_height_limits(self):
        from squid_single_queue import check_vertical_feedback
        g=trial.geometry();path=[g['proof']]+g['points'];height=293.24
        check_vertical_feedback(g['points'][0],path,clearance_z=height)
        with self.assertRaises(TransferError):check_vertical_feedback(g['points'][0],path)
        for pose in (dict(g['points'][0],Z=293.5),dict(g['points'][-1],X=224.3),
                     dict(g['points'][1],Z=292),dict(g['proof'],Z=g['proof']['Z']-.3)):
            with self.assertRaises(TransferError):check_vertical_feedback(pose,path,clearance_z=height)

    def test_live_monitor_samples_cellvis_clearance_during_real_lua_execution(self):
        from test_short_side_hover_transfer import HoverTransferTests
        from trajectory_queue import LuaTrajectory
        from autonomy import check_path
        from squid_single_queue import check_vertical_feedback
        g=trial.geometry()
        for start,points,joints,speeds in [(g['proof'],g['points'],g['start_joints'],g['speeds']),
                                         (g['points'][-1],g['reverse'],g['end_joints'],g['reverse_speeds'])]:
            f=HoverTransferTests();f.setup_route();f.s.pose=deepcopy(start);f.s.q=deepcopy(joints)
            def finish():
                f.s.robot.barriers+=1
                for target,*_ in f.s.robot.calls:
                    end=dict(zip(('X','Y','Z','Rz'),target[:3]+(target[5],)))
                    f.s.q=check_path(f.s.pose,end,f.s.q,g['cfg'],None);f.s.pose=end
                    time.sleep(.25)
            f.s.robot.lua.globals().MOVFINISH=finish
            with patch('squid_single_queue.check_vertical_feedback',wraps=check_vertical_feedback) as monitor:
                result=LuaTrajectory(f.s).execute(f.run,start,joints,points,g['cfg'],137,lambda *args:None,
                    reviewed=True,squid_queue='cellvis24_home_holder',segment_speeds=speeds)
                self.assertTrue(result['ok']);self.assertGreaterEqual(monitor.call_count,4)
                self.assertTrue(all(abs(c.kwargs['clearance_z']-293.24)<.01 for c in monitor.call_args_list))

    def test_stage_must_remain_at_confirmed_loading_position(self):
        g=trial.geometry();p=dict(g['squid_loading_position'],x_mm=1.0)
        with patch.object(trial,'SquidAdapter') as adapter,patch.object(trial,'native_command',return_value=p):
            adapter.return_value.connect.return_value={'stage_simulated':False,'status':'idle'}
            with self.assertRaises(TransferError):trial.instrument_ready(g)

    def test_real_lua_protocol_in_both_directions(self):
        from test_short_side_hover_transfer import HoverTransferTests
        from trajectory_queue import LuaTrajectory
        g=trial.geometry()
        for start,points,joints,speeds in [(g['proof'],g['points'],g['start_joints'],g['speeds']),
                                         (g['points'][-1],g['reverse'],g['end_joints'],g['reverse_speeds'])]:
            f=HoverTransferTests();f.setup_route();f.s.pose=deepcopy(start);f.s.q=deepcopy(joints)
            result=LuaTrajectory(f.s).execute(f.run,start,joints,points,g['cfg'],137,lambda *args:None,
                reviewed=True,squid_queue='cellvis24_home_holder',segment_speeds=speeds)
            self.assertTrue(result['ok']);self.assertEqual(result['completion_barriers'],1)


if __name__=='__main__':unittest.main()
