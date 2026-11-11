"""Offline tests of the IDLE CLI/API boundary; no hardware commands."""
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import repeat_calibration_hamilton as cli


class IdleCLITests(TestCase):
    def exercise(self, case='success', e1=3.9):
        state=dict(robot=dict(connected=True,ok=True,errors=[],enabled=True,
            control_mode={'mode':'auto'},program_state={'state':'running'},
            pose_mm=dict(X=312,Y=-65,Z=104,Rz=89),external_axes={'E1':e1}),
            envelope={'enabled':True})
        if case=='already':state['robot']['pose_mm']=deepcopy(cli.IDLE)
        if case=='stopped':state['robot']['program_state']['state']='stopped'
        if case=='disconnected':state['robot']['connected']=False
        pending=case=='pending';sent=False;events=[]
        plan=dict(id='fresh-idle',dispatch='ik_home_return',preserve_gripper=case!='startup_plan',
                  home=deepcopy(cli.IDLE),start=deepcopy(state['robot']['pose_mm']),e1=e1,steps=[])
        def fake(path,body=None):
            nonlocal sent
            events.append((path,body))
            if path=='state':return deepcopy(state)
            if path=='connect':state['robot']['connected']=True;return {'ok':True}
            if path=='seq':return dict(name='researcher_home' if sent else '',active=False,
                                       result={'ok':True},log=[])
            if path=='researcher/api/lacry/state':
                return dict(pending={'id':'other'} if pending else None,
                            running=dict(active=False,ok=True,step='Done'))
            if path=='researcher/api/lacry/button/move_idle':return {'plan':deepcopy(plan)}
            if path=='researcher/api/lacry/confirm':
                self.assertEqual(body,{'ready':True,'plan_id':'fresh-idle'})
                sent=True
                if case=='timeout':raise TimeoutError('uncertain dispatch')
                if case!='wrong_endpoint':state['robot']['pose_mm']=deepcopy(cli.IDLE)
                if case=='claw_changed':state['robot']['external_axes']['E1']+=1
                return {'ok':True}
            if path=='researcher/api/home/stop':return {'ok':True}
            raise AssertionError('Unexpected API '+path)
        error=None
        with TemporaryDirectory() as tmp,patch.object(cli,'ROOT',Path(tmp)),\
             patch.object(cli,'api',side_effect=fake),patch.object(cli,'DragGoRPC') as native,\
             patch('sys.stdout',new_callable=io.StringIO):
            native.return_value.info.return_value=dict(moving=False,error=False,emergency=False,drag=False,manual=False)
            try:cli.return_idle()
            except (RuntimeError,TimeoutError) as exc:error=exc
            records=list(Path(tmp).glob('operator_ui/reports/plate_session/idle_*/run.json'))
            self.assertEqual(len(records),1)
            record=json.loads(records[0].read_text())
        return record,events,error

    def test_preserves_both_loaded_and_open_claws_using_existing_plan(self):
        for e1 in (3.9,28):
            with self.subTest(e1=e1):
                record,events,error=self.exercise(e1=e1)
                self.assertIsNone(error);self.assertEqual(record['status'],'completed')
                self.assertEqual(record['final']['robot']['external_axes']['E1'],e1)
                posts=[p for p,b in events if b is not None]
                self.assertEqual(posts,['researcher/api/lacry/button/move_idle','researcher/api/lacry/confirm'])

    def test_already_idle_is_verified_without_a_new_plan(self):
        record,events,error=self.exercise('already')
        self.assertIsNone(error);self.assertEqual(record['status'],'already_at_idle_verified')
        self.assertFalse(any(b is not None for _,b in events))

    def test_connects_disconnected_idle_host_once(self):
        record,events,error=self.exercise('disconnected')
        self.assertIsNone(error);self.assertEqual(record['status'],'completed')
        self.assertEqual(sum(p=='connect' for p,b in events),1)

    def test_stopped_controller_pending_plan_or_startup_plan_never_confirm(self):
        for case in ('stopped','pending','startup_plan'):
            with self.subTest(case=case):
                _,events,error=self.exercise(case)
                self.assertIsNotNone(error)
                self.assertFalse(any(p.endswith('/confirm') or p.endswith('/stop') for p,b in events))

    def test_uncertain_dispatch_or_bad_completion_stops_once_without_replay(self):
        for case in ('timeout','wrong_endpoint','claw_changed'):
            with self.subTest(case=case):
                record,events,error=self.exercise(case)
                self.assertIsNotNone(error);self.assertEqual(record['status'],'stopped_or_uncertain')
                self.assertEqual(sum(p.endswith('/confirm') for p,b in events),1)
                self.assertEqual(sum(p=='researcher/api/home/stop' for p,b in events),1)

    def test_preview_never_connects_or_moves(self):
        with patch.object(sys,'argv',['repeat_calibration_hamilton.py','--idle-only']),\
             patch.object(cli,'api') as api,patch.object(cli,'DragGoRPC') as native,\
             patch('sys.stdout',new_callable=io.StringIO) as output:
            cli.main()
            self.assertFalse(json.loads(output.getvalue())['motion_started'])
            api.assert_not_called();native.assert_not_called()

    def test_idle_execute_selects_only_idle_entry_point(self):
        with patch.object(sys,'argv',['repeat_calibration_hamilton.py','--idle-only','--execute']),\
             patch.object(cli,'return_idle') as idle,patch.object(cli,'Batch') as batch:
            cli.main();idle.assert_called_once();batch.assert_not_called()

    def test_cycles_cannot_be_combined_with_idle_only(self):
        with patch.object(sys,'argv',['repeat_calibration_hamilton.py','--idle-only','--cycles','5']),\
             patch('sys.stderr',new_callable=io.StringIO),self.assertRaises(SystemExit) as error:
            cli.main()
        self.assertEqual(error.exception.code,2)


if __name__=='__main__':main()
