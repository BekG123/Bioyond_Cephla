import contextlib
import io
import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch,Mock
import run_home_hamilton_squid_handling as cli


class CliTests(unittest.TestCase):
    def test_flags_combine_in_calibration_hamilton_squid_order(self):
        a=cli.parse_args(['--home-to-squid-roundtrip','--full-calibration','--home-to-hamilton-roundtrip'])
        self.assertEqual(len(cli.selection(a)),3)
        self.assertTrue(cli.selection(a)[0].startswith('Full calibration'))
        self.assertFalse(a.execute)

    def test_single_workflows_are_independent(self):
        for flag in ('--full-calibration','--home-to-hamilton-roundtrip','--home-to-squid-roundtrip'):
            self.assertEqual(len(cli.selection(cli.parse_args([flag]))),1)

    def test_cycle_validation_and_preview(self):
        self.assertEqual(cli.parse_args(['--home-to-squid-roundtrip']).cycles,1)
        with contextlib.redirect_stderr(io.StringIO()):
            for extra in (['--cycles','0'],['--cycles','-2'],['--cycles','1.5']):
                with self.assertRaises(SystemExit):cli.parse_args(['--home-to-squid-roundtrip']+extra)
            with self.assertRaises(SystemExit):cli.parse_args(['--full-calibration','--cycles','5'])
        out=io.StringIO()
        with patch.object(cli,'api') as api,contextlib.redirect_stdout(out):
            cli.main(['--full-calibration','--home-to-hamilton-roundtrip','--home-to-squid-roundtrip','--cycles','5'])
        preview=json.loads(out.getvalue())
        self.assertEqual(preview['calibration_runs'],1);self.assertEqual(preview['handling_cycles'],5)
        api.assert_not_called()

    def test_preview_does_not_connect_or_move(self):
        with patch.object(cli,'api') as api,patch.object(cli,'native_command') as native,contextlib.redirect_stdout(io.StringIO()):
            cli.main(['--full-calibration','--home-to-squid-roundtrip'])
        api.assert_not_called();native.assert_not_called()

    def test_old_combined_command_is_preserved(self):
        a=cli.parse_args(['--calibration-record','test.json'])
        self.assertTrue(a.home_to_hamilton_roundtrip and a.home_to_squid_roundtrip)

    def test_delivery_uses_exchange_only_after_calibration(self):
        with TemporaryDirectory() as folder:
            source=Path(folder)/'receipt.json'
            source.write_text(json.dumps(dict(status='calibration_completed_at_HOME')))
            base,body,name=cli.hamilton_delivery(source)
            self.assertEqual(name,'home_hamilton_exchange');self.assertTrue(body['delivery_only'])
            source.write_text(json.dumps(dict(status='plate_released_at_HOME_clearance')))
            base,body,name=cli.hamilton_delivery(source)
            self.assertEqual(name,'hamilton_holder_dropoff');self.assertEqual(body['phase'],'deliver')

    def test_conflicting_evidence_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for args in ([],['--full-calibration','--source','x'],['--home-to-hamilton-roundtrip','--source','x','--calibration-record','y']):
                with self.assertRaises(SystemExit):cli.parse_args(args)

    def test_calibration_reuses_existing_runner_and_restore_contract(self):
        with patch('repeat_calibration_hamilton.Batch') as cls:
            b=cls.return_value;b.record={'cycles':[]}
            def ui(cycle,phase,button):
                if phase=='calibration':cycle['calibration_record']='fresh.json'
            b.ui_phase.side_effect=ui
            self.assertEqual(cli.calibrate(),'fresh.json')
            b.developer_phase.assert_called_once()
            self.assertEqual(b.developer_phase.call_args.args[-1],'home_hamilton_restore_original')
            self.assertEqual(b.developer_phase.call_args.args[-2],dict(ready=True,empty_gripper=True,holder_clear=True))

    def test_calibration_failure_does_not_start_handling(self):
        with patch('repeat_calibration_hamilton.Batch') as cls,patch.object(cli,'api') as api:
            b=cls.return_value;b.record={'cycles':[]};b.dispatched=True
            b.ui_phase.side_effect=RuntimeError('fault')
            with self.assertRaisesRegex(RuntimeError,'fault'):cli.calibrate()
            api.assert_called_once_with('researcher/api/lacry/stop',{})


class CycleTests(unittest.TestCase):
    def setUp(self):
        folder=TemporaryDirectory();self.addCleanup(folder.cleanup);self.folder=Path(folder.name)
        self.source=self.folder/'calibration.json'
        self.source.write_text(json.dumps(dict(status='calibration_completed_at_HOME')))
        self.record=dict(phases=[],cycles=[],completed_cycles=0,current_cycle=None)
        self.calls=[];self.failure=None;self.state=Mock(return_value={'healthy':True})
        self.ham=Mock();self.squid=Mock();self.save=Mock();self.say=Mock()
        p=patch.object(cli,'calibrate',return_value=str(self.source));self.cal=p.start();self.addCleanup(p.stop)
        p=patch.object(cli,'find_source',return_value=self.source);p.start();self.addCleanup(p.stop)
        p=patch.object(cli,'api',side_effect=AssertionError('No hardware API in offline test'));p.start();self.addCleanup(p.stop)

    def phase(self,label,base,body,name):
        cycle=self.record['current_cycle'];self.calls.append((cycle,label,body))
        self.record['phases'].append(dict(cycle=cycle,label=label))
        if self.failure==(cycle,label):raise TimeoutError('uncertain motion')
        receipt=self.folder/f'phase_{len(self.calls)}.json'
        receipt.write_text(json.dumps(dict(status='plate_released_at_HOME_clearance')))
        return str(receipt)

    def run_workflow(self,*flags):
        args=cli.parse_args(list(flags))
        return cli.run_selected(args,self.phase,self.state,self.ham,self.squid,self.record,self.save,self.say)

    def test_five_combined_cycles_calibrate_once_and_rotate_from_session_reference(self):
        result=self.run_workflow('--full-calibration','--home-to-hamilton-roundtrip','--home-to-squid-roundtrip','--cycles','5')
        self.cal.assert_called_once_with();self.assertEqual(len(self.calls),50)
        self.assertEqual(self.record['completed_cycles'],5)
        for cycle in range(1,6):
            calls=[x for x in self.calls if x[0]==cycle]
            self.assertEqual(calls[0][1],'Hamilton delivery')
            self.assertEqual(calls[0][2]['calibration_record'],str(self.source))
            self.assertEqual(calls[-1][1],'Final HOME release')
            self.assertEqual(self.record['cycles'][cycle-1]['status'],'controller_completed')
        self.assertEqual(self.record['cycles'][1]['previous_release_receipt'],str(self.folder/'phase_10.json'))
        self.assertEqual(result,str(self.folder/'phase_50.json'))

    def test_hamilton_only_chains_new_home_receipt_without_calibrating_again(self):
        self.run_workflow('--full-calibration','--home-to-hamilton-roundtrip','--cycles','3')
        self.cal.assert_called_once_with();self.assertEqual(len(self.calls),15)
        self.assertEqual(self.calls[5][2],dict(source=str(self.folder/'phase_5.json'),phase='deliver'))
        self.squid.assert_not_called()

    def test_squid_only_chains_each_final_release(self):
        self.run_workflow('--home-to-squid-roundtrip','--cycles','3')
        self.cal.assert_not_called();self.assertEqual(len(self.calls),15)
        self.assertEqual(self.calls[5][2]['source'],str(self.folder/'phase_5.json'))
        self.ham.assert_not_called()

    def test_failure_does_not_count_failed_cycle_retry_or_start_next_cycle(self):
        self.failure=(2,'Squid retrieve')
        with self.assertRaisesRegex(TimeoutError,'uncertain motion'):
            self.run_workflow('--full-calibration','--home-to-hamilton-roundtrip','--home-to-squid-roundtrip','--cycles','5')
        self.cal.assert_called_once_with();self.assertEqual(self.record['completed_cycles'],1)
        self.assertEqual(len(self.record['cycles']),2)
        self.assertEqual(self.record['cycles'][-1]['status'],'stopped_or_uncertain')
        self.assertEqual(self.calls[-1][:2],(2,'Squid retrieve'))

    def test_combined_repeats_reject_short_side_receipt_before_handling(self):
        self.source.write_text(json.dumps(dict(status='plate_released_at_HOME_clearance')))
        with self.assertRaisesRegex(RuntimeError,'fresh --calibration-record'):
            self.run_workflow('--home-to-hamilton-roundtrip','--home-to-squid-roundtrip','--cycles','2')
        self.assertEqual(self.calls,[]);self.cal.assert_not_called()

    def test_calibration_only_is_once_without_handling(self):
        self.run_workflow('--full-calibration')
        self.cal.assert_called_once_with();self.assertEqual(self.calls,[])
        self.assertEqual(self.record['completed_cycles'],0)


if __name__=='__main__':unittest.main()
