import sys
import io
import json
from copy import deepcopy
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import repeat_holder_calibration_20261110 as batch


class CompletionChecks(TestCase):
    def test_callback_handoff_is_pending_not_failure(self):
        self.assertFalse(batch.terminal(dict(active=False,ok=None)))
        self.assertFalse(batch.terminal(dict(active=True,ok=None)))
        self.assertTrue(batch.terminal(dict(active=False,ok=True)))
        self.assertTrue(batch.terminal(dict(active=False,ok=False)))

    def test_pose_feedback_extra_axes(self):
        batch.near(batch.IDLE,dict(batch.IDLE,Rx=0,Ry=0))

    def setUp(self):
        self.robot=dict(pose_mm=batch.END,external_axes={'E1':28})
        p=patch.object(batch,'healthy',return_value=self.robot);p.start();self.addCleanup(p.stop)
        self.running=dict(ok=True,done=batch.LABELS)
        self.seq=dict(active=False,name='pickup_holder_clearance',result=dict(ok=True,payload='empty',record='new'))

    def test_failed_cycle_never_accepted(self):
        with self.assertRaises(RuntimeError):batch.verify_finish(dict(ok=False),self.seq,{},'calibration','old')

    def test_closed_jaws_never_accepted_as_release(self):
        self.robot['external_axes']['E1']=3.9
        with self.assertRaises(RuntimeError):batch.verify_finish(self.running,self.seq,{},'calibration','old')

    def test_old_receipt_is_not_another_cycle(self):
        with self.assertRaises(RuntimeError):batch.verify_finish(self.running,self.seq,{},'calibration','new')

    def test_missing_stage_blocks_next_cycle(self):
        self.running['done']=batch.LABELS[:-1]
        with self.assertRaises(RuntimeError):batch.verify_finish(self.running,self.seq,{},'calibration','old')

    def test_fresh_complete_receipt(self):
        with patch.object(Path,'read_bytes',return_value=b'{"status":"completed","action":"Clearance","speed":137}'):
            self.assertEqual(batch.verify_finish(self.running,self.seq,{},'calibration','old'),'new')


class BatchChecks(TestCase):
    def test_start_positions(self):
        self.assertEqual(batch.start_location(batch.IDLE),'idle')
        self.assertEqual(batch.start_location(batch.END),'holder_clearance')
        for pose in (dict(batch.IDLE,Z=0),dict(batch.IDLE,X=float('nan'))):
            with self.assertRaises(RuntimeError):batch.start_location(pose)

    def test_http_error_preserves_reason(self):
        error=batch.HTTPError('http://local',409,'Conflict',{},io.BytesIO(b'Already calibrated'))
        with patch.object(batch,'urlopen',side_effect=error):
            with self.assertRaisesRegex(RuntimeError,'409: Already calibrated'):batch.api('test',{})

    def run_fake(self, initial, fail_cycle=None):
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            state=dict(robot=dict(connected=True,ok=True,errors=[],enabled=True,
                control_mode={'mode':'auto'},program_state={'state':'running'},
                pose_mm=deepcopy(initial),external_axes={'E1':28}),envelope={'enabled':True})
            ui=dict(running=dict(active=False,ok=True,done=[],step=''),pending=None)
            seq=dict(active=False,name='',result={'ok':True})
            count=dict(begin=0,idle=0,calibration=0,stop=0)
            calibrated=True
            plan=None
            def fake(path,body=None):
                nonlocal calibrated,plan,seq
                if path=='state':return deepcopy(state)
                if path=='seq':return deepcopy(seq)
                if path=='researcher/api/status':return {'hand_guiding':{'state':'off'}}
                if path=='researcher/api/lacry/state':return deepcopy(ui)
                if path.endswith('/plate-session/begin'):
                    count['begin']+=1;calibrated=False
                    return dict(ok=True,motion_started=False,session={'calibrated':False})
                if '/button/' in path:
                    if path.endswith('move_idle'):
                        plan=dict(id=str(count),dispatch='ik_home_return',preserve_gripper=True,
                                  home=batch.IDLE,start=deepcopy(state['robot']['pose_mm']))
                    else:
                        if calibrated:raise RuntimeError('Already calibrated')
                        plan=dict(id=str(count),dispatch='classic_pickup',steps=[{'label':s} for s in batch.LABELS])
                    return {'plan':deepcopy(plan)}
                if path.endswith('/confirm'):
                    self.assertEqual(body['plan_id'],plan['id'])
                    if plan['dispatch']=='ik_home_return':
                        count['idle']+=1;state['robot']['pose_mm']=deepcopy(batch.IDLE)
                        seq=dict(active=False,name='researcher_home',result={'ok':True})
                        ui['running']=dict(active=False,ok=True,done=['Return IDLE'],step='done')
                    else:
                        count['calibration']+=1;calibrated=True
                        if count['calibration']==fail_cycle:raise TimeoutError('uncertain dispatch')
                        receipt=root/('receipt'+str(count['calibration'])+'.json')
                        receipt.write_text(json.dumps(dict(status='completed',action='Clearance',speed=137)))
                        state['robot']['pose_mm']=deepcopy(batch.END)
                        seq=dict(active=False,name='pickup_holder_clearance',result=dict(ok=True,payload='empty',record=str(receipt)))
                        ui['running']=dict(active=False,ok=True,done=batch.LABELS,step='done')
                    return {'ok':True}
                if path.endswith('/stop'):count['stop']+=1;return {'ok':True}
                raise AssertionError(path)
            with patch.object(batch,'ROOT',root),patch.object(batch,'api',side_effect=fake),patch.object(sys,'argv',['batch','--execute','--cycles','5']),patch('sys.stdout',new_callable=io.StringIO):
                if fail_cycle:
                    with self.assertRaises(TimeoutError):batch.main()
                else:batch.main()
            report=json.loads(next(root.glob('operator_ui/reports/pickup_holder/*/run.json')).read_text())
            return count,report

    def test_five_cycles_from_idle(self):
        count,report=self.run_fake(batch.IDLE)
        self.assertEqual(count,dict(begin=5,idle=4,calibration=5,stop=0))
        self.assertEqual(report['completed_cycles'],5)
        self.assertEqual(report['status'],'all_requested_cycles_controller_completed')

    def test_five_cycles_from_holder(self):
        count,report=self.run_fake(batch.END)
        self.assertEqual(count,dict(begin=5,idle=5,calibration=5,stop=0))
        self.assertEqual(report['completed_cycles'],5)

    def test_failure_stops_without_repeating_or_starting_later_cycles(self):
        count,report=self.run_fake(batch.IDLE,fail_cycle=2)
        self.assertEqual(count,dict(begin=2,idle=1,calibration=2,stop=1))
        self.assertEqual(report['completed_cycles'],1)
        self.assertEqual(report['status'],'stopped_or_uncertain')


if __name__=='__main__':main()
