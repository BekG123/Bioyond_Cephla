"""Offline API workflow tests; no controller connections or motion."""
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
from unittest import TestCase,main
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import repeat_calibration_hamilton as batch


class BatchTests(TestCase):
    def exercise(self,fail=None,bad_finish=False,old_tolerance=False,initial_e1=28,at_home=False,initial_pose=None):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);events=[];count=0;plan=None
            state=dict(robot=dict(connected=True,ok=True,enabled=True,errors=[],
                control_mode={'mode':'auto'},program_state={'state':'running'},pose_mm=deepcopy(batch.IDLE),
                external_axes={'E1':initial_e1}),envelope={'enabled':True})
            if at_home:state['robot']['pose_mm']=deepcopy(batch.END)
            if initial_pose is not None:state['robot']['pose_mm']=deepcopy(initial_pose)
            ui=dict(running=dict(active=False,ok=True,done=[],step='ready'),pending=None)
            seq=dict(active=False,name='',result={'ok':True})
            _,_,grip=batch.reference('04')
            clear=dict(grip['descent_endpoint'],Z=grip['descent_endpoint']['Z']+30)
            def fake(path,body=None):
                nonlocal seq,plan,count
                if body is not None:events.append(path)
                if path=='state':return deepcopy(state)
                if path=='seq':return deepcopy(seq)
                if path=='researcher/api/lacry/state':return deepcopy(ui)
                if path=='researcher/api/lacry/stop':return {'ok':True}
                if path=='gripper':
                    self.assertEqual(body,dict(action='move',e1=28,speed=5))
                    self.assertTrue(batch.at_idle_pose(state['robot']['pose_mm']))
                    if fail=='opening':raise TimeoutError('uncertain opening')
                    if fail=='opening_feedback':return {'ok':True}
                    state['robot']['external_axes']['E1']=28
                    if fail=='opening_recovered':return {'ok':True,'recovered':'connection interruption'}
                    return {'ok':True}
                if path.endswith('/plate-session/begin'):
                    return dict(motion_started=False,session={'calibrated':False})
                if '/button/' in path:
                    if path.endswith('move_idle'):
                        plan=dict(id='idle',dispatch='ik_home_return',preserve_gripper=True,home=batch.IDLE,start=deepcopy(state['robot']['pose_mm']))
                    else:plan=dict(id='calibration',dispatch='classic_pickup',steps=[{'label':x} for x in batch.LABELS])
                    return {'plan':deepcopy(plan)}
                if path.endswith('/confirm'):
                    self.assertEqual(body['plan_id'],plan['id'])
                    if fail==plan['id']:raise TimeoutError('uncertain '+fail)
                    idle=plan['id']=='idle'
                    state['robot']['pose_mm']=deepcopy(batch.IDLE if idle else batch.END)
                    ui['running']=dict(active=False,ok=True,done=[] if idle else batch.LABELS,step='done')
                    result={'ok':True}
                    if not idle:
                        count+=1;receipt=root/f'calibration{count}.json'
                        receipt.write_text(json.dumps(dict(status='completed',action='Clearance',speed=137)))
                        result.update(payload='empty',record=str(receipt))
                    seq=dict(active=False,name='researcher_home' if idle else 'pickup_holder_clearance',result=result)
                    return {'ok':True}
                if path.endswith('/preview'):
                    evidence=json.loads(Path(body['calibration_record']).read_text())
                    self.assertEqual(evidence['status'],'calibration_completed_at_HOME')
                    plan=dict(id=f'{count:032x}',holder_tolerances_deg={'arrival':.1,'monitor':.15 if old_tolerance else .5})
                    return {'plan':plan}
                if path.endswith('/restore-original') or path.endswith('/start'):
                    restore=path.endswith('/restore-original');name='home_hamilton_restore_original' if restore else 'home_hamilton_exchange'
                    if fail==('restore' if restore else 'exchange'):raise TimeoutError('uncertain '+fail)
                    folder=root/'operator_ui/reports/plate_session/hamilton_exchanges';folder.mkdir(parents=True,exist_ok=True)
                    receipt=folder/(f'restore{count}.json' if restore else plan['id']+'.json')
                    status='completed' if restore else ('failed_or_uncertain' if bad_finish else 'completed_pending_operator_observation')
                    receipt.write_text(json.dumps(dict(status=status,at=time.time())))
                    if not restore:state['robot']['pose_mm']=deepcopy(clear)
                    result=dict(ok=True,record=str(receipt))
                    if not restore:result.update(payload='empty',station='HOME')
                    seq=dict(active=False,name=name,result=result)
                    return dict(ok=True,started=name)
                raise AssertionError(path)
            with patch.object(batch,'ROOT',root),patch.object(batch,'api',side_effect=fake),\
                 patch.object(batch,'healthy',side_effect=lambda s:s['robot']),\
                 patch.object(batch,'DragGoRPC') as native,patch('sys.stdout',new_callable=io.StringIO):
                native.return_value.info.side_effect=lambda:dict(moving=False,error=False,emergency=False,drag=False,manual=False,external_axes=deepcopy(state['robot']['external_axes']))
                runner=batch.Batch(5)
                try:runner.run()
                except (RuntimeError,TimeoutError):
                    if not (fail or bad_finish or old_tolerance or at_home and initial_e1!=28 or not batch.math.isfinite(initial_e1)):raise
                return deepcopy(runner.record),events,deepcopy(state)

    def test_five_complete_cycles_each_restore_and_fresh_calibration(self):
        record,events,state=self.exercise()
        self.assertEqual(record['completed_cycles'],5)
        self.assertEqual(record['status'],'all_requested_cycles_controller_completed')
        for suffix in ('/restore-original','/plate-session/begin','/button/full_calibration','/start'):
            self.assertEqual(sum(p.endswith(suffix) for p in events),5)
        self.assertEqual(sum(p.endswith('/button/move_idle') for p in events),4)
        self.assertNotIn('researcher/api/lacry/stop',events)
        self.assertEqual(state['robot']['external_axes']['E1'],28)
        self.assertNotEqual(state['robot']['pose_mm'],batch.IDLE)
        paths=[c['calibration_record'] for c in record['cycles']]
        self.assertEqual(len(set(paths)),5)

    def test_timeout_stops_batch_without_resending(self):
        for phase,suffix in [('restore','/restore-original'),('calibration','/confirm'),('exchange','/start')]:
            with self.subTest(phase=phase):
                record,events,_=self.exercise(fail=phase)
                self.assertEqual(record['completed_cycles'],0)
                self.assertEqual(len(record['cycles']),1)
                self.assertEqual(sum(p.endswith(suffix) for p in events),1)
                self.assertEqual(events[-1],'researcher/api/lacry/stop')

    def test_incomplete_exchange_never_counts_or_starts_next_cycle(self):
        record,events,_=self.exercise(bad_finish=True)
        self.assertEqual(record['completed_cycles'],0);self.assertEqual(len(record['cycles']),1)
        self.assertEqual(sum(p.endswith('/start') for p in events),1)

    def test_old_backend_tolerance_prevents_exchange(self):
        record,events,_=self.exercise(old_tolerance=True)
        self.assertEqual(record['completed_cycles'],0)
        self.assertFalse(any(p.endswith('/start') for p in events))

    def test_preview_never_contacts_hardware(self):
        with patch.object(batch,'api') as api,patch.object(batch,'DragGoRPC') as native,\
             patch.object(sys,'argv',['repeat_calibration_hamilton.py','--cycles','5']),\
             patch('sys.stdout',new_callable=io.StringIO) as output:
            batch.main();self.assertFalse(json.loads(output.getvalue())['motion_started'])
            api.assert_not_called();native.assert_not_called()

    def test_closed_empty_start_at_idle_opens_once_and_completes_five_cycles(self):
        record,events,_=self.exercise(initial_e1=.03)
        self.assertEqual(record['completed_cycles'],5)
        self.assertEqual(events[0],'gripper');self.assertEqual(events.count('gripper'),1)
        self.assertEqual(record['idle_jaw_preparation']['status'],'completed')

    def test_open_start_does_not_send_extra_gripper_command(self):
        record,events,_=self.exercise()
        self.assertEqual(record['completed_cycles'],5);self.assertNotIn('gripper',events)

    def test_closed_jaws_at_holder_never_open_or_depart_automatically(self):
        record,events,_=self.exercise(initial_e1=25,at_home=True)
        self.assertEqual(record['completed_cycles'],0);self.assertEqual(events,[])
        self.assertIn('At HOME',record['error'])

    def test_opening_timeout_or_bad_feedback_never_starts_calibration(self):
        for fail in ('opening','opening_feedback','opening_recovered'):
            with self.subTest(fail=fail):
                record,events,_=self.exercise(initial_e1=.03,fail=fail)
                self.assertEqual(record['completed_cycles'],0)
                self.assertEqual(events,['gripper','researcher/api/lacry/stop'])

    def test_nonfinite_jaw_feedback_never_dispatches(self):
        record,events,_=self.exercise(initial_e1=float('nan'))
        self.assertEqual(events,[]);self.assertIn('Invalid jaw',record['error'])

    def test_reported_idle_readback_skips_redundant_move_and_runs_all_cycles(self):
        pose=dict(X=290.009,Y=62.658,Z=248.003,Rz=-3.823)
        record,events,_=self.exercise(initial_pose=pose)
        self.assertEqual(record['completed_cycles'],5)
        self.assertEqual(record['cycles'][0]['phases'][0]['status'],'already_at_idle_verified')
        self.assertFalse(record['cycles'][0]['phases'][0]['motion_started'])
        self.assertEqual(sum(p.endswith('/button/move_idle') for p in events),4)

    def test_idle_rule_matches_ui_inside_outside_and_wrapped_yaw(self):
        from imitation_agent import close_pose
        for pose in (dict(batch.IDLE,X=batch.IDLE['X']+.49),
                     dict(batch.IDLE,X=batch.IDLE['X']+.51),
                     dict(batch.IDLE,Rz=batch.IDLE['Rz']+.49),
                     dict(batch.IDLE,Rz=batch.IDLE['Rz']+.51),
                     dict(batch.IDLE,Rz=batch.IDLE['Rz']+360)):
            self.assertEqual(batch.at_idle_pose(pose),close_pose(pose,batch.IDLE))

if __name__=='__main__':main()
