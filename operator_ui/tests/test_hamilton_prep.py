"""Physical-command semantics tested against a fake Prep; no hardware traffic."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hamilton_prep import HamiltonPrep,digest,decoded,error_summary
from researcher_teaching import TeachingError


class Events:
    def __init__(self,adapter):self.adapter=adapter
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def drain(self):
        rows=self.adapter.request.events[:];self.adapter.request.events.clear();return rows


class Device:
    def __init__(self):
        self.calls=[];self.events=[];self.errors=[];self.run_id=None
        self.phase='Idle';self.result='Completed';self.start_count=0;self.fail_start=False
        self.definition={'id':1002,'steps':['dispense']};self.instructions=[{'deckPosition':3}]
        self.info=['Serial Number: PRPGD2427','Connected: True','Initialization Status: Initialized']
        self.channel_results=[self.channel_result(1)]
        self.channel_outcome='Pass';self.emit_channel_result=True;self.door=True
        self.rack_site=7;self.selection_required=False;self.self_success=True

    @staticmethod
    def channel_result(number,status='Pass'):
        return dict(id=number,calibrationDate=f'2026-10-25T03:{number:02}:00',status=status,
                    hasError=status!='Pass',channelWarnings=[],channelOffset=dict(yzAxisOffsets=[
                        dict(index=i,offsetZValid=status=='Pass') for i in (0,1)]))

    def finish_channel(self):
        if self.emit_channel_result:self.channel_results.insert(0,self.channel_result(2,self.channel_outcome))

    def __call__(self,method,path,body):
        self.calls.append((method,path,deepcopy(body)))
        if path=='instruments/connection-info':return self.info
        if path=='instruments/global-run-state':return 'Idle'
        if path=='service-software-api/is-parked':return True
        if path=='service-software-api/sensor-status':return dict(isDoorClosed=self.door,isEnclosurePresent=True)
        if path=='service-software-api/has-tips':return False
        if path=='verification/status':return {}
        if path=='calibration/channel-results':return deepcopy(self.channel_results)
        if path=='labware/273':return dict(id=273,name='235903',displayName='300 uL framed conductive filtered',classification='tiprack')
        if path=='deck/scan/3':return [dict(positionId=self.rack_site,isOccupied=True,detectedLabwareId=273,confidence=.91)]
        if path=='protocols':return [{'id':1002,'name':'Water'}]
        if path=='protocols/1002':return self.definition
        if path=='errors/check-for-pending-errors':return []
        if path.startswith('errors?'):return {'items':self.errors}
        if path=='maintenance/errors':return [{'message':'Close the door and continue the assay'}]
        if path=='protocol-run':
            return dict(protocolId=1002,runDatalId=self.run_id,isRunInProgress=self.phase!='Idle',
                        protocolRunState=self.phase,isSimulation=False)
        if path in ('instruments/initialize','calibration/self-calibration'):
            self.events.append(('instinctevents',dict(code='preparinginstrument')))
            if path.startswith('calibration') and self.self_success:
                self.events.append(('instinctevents',dict(code='calibrationdata',data=dict(id='calibration',spinnerShown=False,buttonText='Finish',textSections=[['Calibration successful']]))))
            return None
        if path=='calibration/channel-height-squeeze':
            self.events.append(('instinctevents',dict(code='preparinginstrument')))
            if self.selection_required:
                self.events.append(('instinctevents',dict(code='calibrationdata',data=dict(id='rack-choice',spinnerShown=False,inputType='tiprack',textSections=[['Select tip labware and place on the deck.']]))))
            else:self.finish_channel()
            return None
        if path=='calibration/close-labware-view':self.finish_channel();return None
        if path=='protocol-run/create':
            self.start_count+=1
            if self.fail_start:raise TimeoutError('response lost')
            self.run_id='run'+str(self.start_count);self.phase='Loading';return None
        if path=='protocol-run/load-instructions':return self.instructions
        if path=='protocol-run/load-complete':self.phase='Idle';return None
        if path.startswith('run-data/'):
            return dict(id=self.run_id,runResult=self.result,errorMessages=[],deviceSerialNumber='PRPGD2427')
        if path in ('protocol-run/abort','calibration/abort','errors/runtime'):
            self.phase='Idle';self.events.append(('instinctevents',dict(code='aborted')));return None
        if path=='calibration/close-view':return None
        raise AssertionError((method,path,body))


class PrepTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.config=self.root/'config.json';self.device=Device()
        self.settings=dict(base_url='http://192.168.100.101/NimbusLite/api/v1',serial_number='PRPGD2427',timeout_s=.1,
            recipes={'Water':dict(reviewed=True,protocol_id=1002,protocol_hash=digest(self.device.definition),inventory_id='rack-a',
                cycle_loads=[dict(load_instructions_hash=digest(self.device.instructions),load_complete=dict(residualTips=[{'cycle':i}])) for i in range(3)])})
        self.config.write_text(json.dumps(self.settings))
        self.adapter=HamiltonPrep(self.config,self.device,Events,self.root/'logs',sleep=lambda _:None)

    def operator_answers(self,state):
        """Explicit simulated operator, used only by tests that accept instructions."""
        if self.adapter.prompt:self.adapter.respond(self.adapter.prompt['id'],'Ok')

    def test_status_and_plan_send_no_writes(self):
        self.assertTrue(self.adapter.status()['connected'])
        self.adapter.prepare('Water',repetitions=3)
        self.assertTrue(all(x[0]=='GET' for x in self.device.calls))

    def test_one_start_exact_completed_job_and_persistent_inventory(self):
        plan=self.adapter.prepare('Water',repetitions=2)
        for _ in range(2):
            ticket=self.adapter.start(plan,'plate',lambda x:None)
            self.assertTrue(self.adapter.wait(plan,ticket,lambda x:None,lambda:False,lambda x:None)['ok'])
        self.assertEqual(self.device.start_count,2)
        bodies=[x[2] for x in self.device.calls if x[1]=='protocol-run/load-complete']
        self.assertEqual([x['residualTips'][0]['cycle'] for x in bodies],[0,1])
        self.assertFalse(any(x['simulate'] for x in bodies))
        fresh=HamiltonPrep(self.config,self.device,Events,self.root/'logs')
        with self.assertRaisesRegex(TeachingError,'capacity'):fresh.prepare('Water',repetitions=2)

    def test_start_timeout_never_retries_and_blocks_after_restart(self):
        plan=self.adapter.prepare('Water');self.device.fail_start=True
        with self.assertRaisesRegex(TeachingError,'uncertain'):self.adapter.start(plan,'p',lambda x:None)
        self.assertEqual(self.device.start_count,1)
        fresh=HamiltonPrep(self.config,self.device,Events,self.root/'logs')
        with self.assertRaisesRegex(TeachingError,'unresolved'):
            fresh.run_action('initialize')
        self.assertEqual(self.device.start_count,1)

    def test_failed_owned_operation_keeps_actual_diagnosis_after_restart(self):
        with self.assertRaisesRegex(TeachingError,'abort acknowledgment missing'):
            with self.adapter.owned('full_calibration') as ticket:
                ticket.update(write_attempted=True,step='channel_calibration')
                raise TeachingError('abort acknowledgment missing')
        saved=json.loads((self.adapter.folder/'active.json').read_text())
        self.assertEqual(saved['status'],'failed_or_uncertain')
        fresh=HamiltonPrep(self.config,self.device,Events,self.root/'logs')
        self.assertEqual(fresh.active['error'],'abort acknowledgment missing')
        with self.assertRaisesRegex(TeachingError,'unresolved'):fresh.preflight()

    def test_idle_aborted_record_is_not_success(self):
        plan=self.adapter.prepare('Water');ticket=self.adapter.start(plan,'p',lambda x:None)
        self.device.result='Aborted'
        with self.assertRaisesRegex(TeachingError,'successful completion'):
            self.adapter.wait(plan,ticket,lambda x:None,lambda:False,lambda x:None)
        self.assertEqual(self.adapter.active['status'],'aborted')
        self.assertFalse((self.root/'logs/active.json').exists())

    def test_changed_protocol_or_load_instructions_blocks_execution(self):
        plan=self.adapter.prepare('Water');self.device.definition['steps']=['changed']
        with self.assertRaisesRegex(TeachingError,'changed'):self.adapter.start(plan,'p',lambda x:None)
        self.assertEqual(self.device.start_count,0)

    def test_loading_mismatch_never_sends_load_complete(self):
        plan=self.adapter.prepare('Water');ticket=self.adapter.start(plan,'p',lambda x:None)
        self.device.instructions=[{'deckPosition':4}]
        with self.assertRaisesRegex(TeachingError,'loading instructions changed'):
            self.adapter.wait(plan,ticket,lambda x:None,lambda:False,lambda x:None)
        self.assertFalse(any(x[1]=='protocol-run/load-complete' for x in self.device.calls))

    def test_full_calibration_chains_once_without_extra_confirmation(self):
        result=self.adapter.run_action('full_calibration',progress=self.operator_answers)
        self.assertTrue(result['ok'])
        self.assertEqual(result['completed_steps'],['self_calibration','channel_calibration'])
        self.assertEqual(result['channel_result']['id'],2)
        writes=[x[1] for x in self.device.calls if x[0]!='GET']
        self.assertEqual(writes,['calibration/self-calibration','calibration/close-view','calibration/channel-height-squeeze'])

    def test_explicit_initialize_remains_available(self):
        self.assertTrue(self.adapter.run_action('initialize')['ok'])
        self.assertEqual([p for m,p,_ in self.device.calls if m!='GET'],['instruments/initialize'])

    def test_site_and_catalog_id_reach_native_rack_dialog(self):
        self.device.rack_site=4;self.device.selection_required=True
        setup=self.adapter.calibration_setup(tip_site=4)
        self.assertTrue(self.adapter.run_action('channel_calibration',calibration_setup=setup,progress=self.operator_answers)['ok'])
        self.assertIn(('POST','calibration/channel-height-squeeze',dict(tipLabwareId=273,tipLabwareSite=4)),self.device.calls)
        self.assertEqual(setup['reference_id'],'235903')
        self.assertIn(('POST','calibration/close-labware-view',dict(viewId='rack-choice',viewResult='Ok',labwareId='273',labwarePosition=4)),self.device.calls)
        self.assertFalse(any(p=='calibration/close-view' for _,p,_ in self.device.calls))

    def test_wrong_rack_override_is_rejected_before_hardware_calls(self):
        with self.assertRaisesRegex(TeachingError,'configured calibration tip rack'):
            self.adapter.calibration_setup(tip_site=7,tip_labware_id=1)
        self.assertEqual(self.device.calls,[])

    def test_default_rack_is_300ul_and_stale_50ul_setup_cannot_resume(self):
        setup=self.adapter.calibration_setup()
        self.assertEqual((setup['tip_labware_id'],setup['reference_id'],setup['tip_site']),(273,'235903',7))
        self.adapter.active=dict(status='running',calibration_setup=dict(setup,tip_labware_id=1))
        self.adapter.prompt=dict(id='old-rack',action='full_calibration',data=dict(inputType='tiprack'))
        with self.assertRaisesRegex(TeachingError,'configured calibration tip rack'):
            self.adapter.respond('old-rack','Ok')
        self.assertFalse(any(m!='GET' for m,_,_ in self.device.calls))

    def test_old_pass_and_idle_cannot_complete_new_channel_calibration(self):
        self.device.emit_channel_result=False
        with self.assertRaisesRegex(TeachingError,'timed out'):self.adapter.run_action('channel_calibration')
        self.assertEqual(sum(p=='calibration/channel-height-squeeze' for _,p,_ in self.device.calls),1)

    def test_failed_self_calibration_never_starts_channels(self):
        self.device.self_success=False
        with self.assertRaisesRegex(TeachingError,'timed out'):self.adapter.run_action('full_calibration')
        self.assertFalse(any(p=='calibration/channel-height-squeeze' for _,p,_ in self.device.calls))

    def test_failed_new_channel_result_never_reports_success(self):
        self.device.channel_outcome='Fail'
        with self.assertRaisesRegex(TeachingError,'did not pass'):self.adapter.run_action('full_calibration',progress=self.operator_answers)
        self.assertNotEqual(self.adapter.active['status'],'completed')

    def test_missing_calibration_blocks_liquid_handling_before_inventory_reservation(self):
        plan=self.adapter.prepare('Water')
        self.device.channel_results.insert(0,self.device.channel_result(2,'Fail'))
        with self.assertRaisesRegex(TeachingError,'full calibration'):self.adapter.start(plan,'plate',lambda x:None)
        self.assertEqual(self.device.start_count,0)
        self.assertFalse(list((self.root/'logs').glob('inventory_*')))
        with self.assertRaisesRegex(TeachingError,'full calibration'):self.adapter.prepare('Water')
        # A combined plan can include calibration first; start still enforces the pass.
        self.adapter.prepare('Water',allow_uninitialized=True)

    def test_wrong_rack_site_never_accepts_native_loading_prompt(self):
        self.device.rack_site=4;self.device.selection_required=True
        with self.assertRaisesRegex(TeachingError,'camera'):
            self.adapter.run_action('channel_calibration',progress=self.operator_answers)
        self.assertFalse(any(p=='calibration/close-labware-view' for _,p,_ in self.device.calls))

    def test_self_calibration_never_requires_a_tip_rack(self):
        self.device.rack_site=None
        self.assertTrue(self.adapter.run_action('self_calibration',progress=self.operator_answers)['ok'])
        self.assertFalse(any(p=='deck/scan/3' for _,p,_ in self.device.calls))

    def test_full_calibration_empty_deck_then_rack_loading(self):
        self.device.rack_site=None;self.device.selection_required=True
        waiting=[]
        def progress(state):
            if self.adapter.prompt and self.adapter.prompt['data'].get('inputType')=='tiprack':
                waiting.append(state)
                paths=[p for _,p,_ in self.device.calls]
                self.assertEqual(state['completed_steps'],['self_calibration'])
                self.assertIn('calibration/channel-height-squeeze',paths)
                self.assertNotIn('deck/scan/3',paths)
                self.device.rack_site=7  # Operator loads supplies after the native instruction.
            self.operator_answers(state)
        result=self.adapter.run_action('full_calibration',progress=progress)
        self.assertTrue(result['ok'])
        self.assertEqual(len(waiting),1)
        self.assertEqual(sum(p=='calibration/channel-height-squeeze' for _,p,_ in self.device.calls),1)

    def test_success_display_waits_for_operator_finish_before_channels(self):
        with self.assertRaisesRegex(TeachingError,'timed out'):
            self.adapter.run_action('full_calibration')
        paths=[p for _,p,_ in self.device.calls]
        self.assertIn('calibration/self-calibration',paths)
        self.assertNotIn('calibration/channel-height-squeeze',paths)

    def test_stop_while_waiting_for_native_rack_instruction_never_accepts_it(self):
        self.device.rack_site=None;self.device.selection_required=True
        waiting=[]
        def progress(state):
            if self.adapter.prompt and self.adapter.prompt['data'].get('inputType')=='tiprack':waiting.append(state)
            else:self.operator_answers(state)
        with self.assertRaisesRegex(TeachingError,'stopped'):
            self.adapter.run_action('full_calibration',stopped=lambda:bool(waiting),progress=progress)
        self.assertFalse(any(p=='calibration/close-labware-view' for _,p,_ in self.device.calls))

    def test_open_door_does_not_block_when_automation_ready(self):
        # The watchdog drives the door actuator, so an open sensor is not a blocker.
        self.device.rack_site=7;self.device.door=False
        self.adapter.calibration_motion_ready()

    def test_open_door_still_blocks_when_interlock_restored(self):
        self.settings['door_automation_ready']=False
        self.config.write_text(json.dumps(self.settings))
        self.device.rack_site=7;self.device.door=False
        with self.assertRaisesRegex(TeachingError,'door'):self.adapter.calibration_motion_ready()

    def test_stop_after_self_calibration_prevents_channels(self):
        def stopped():return any(p=='calibration/close-view' for _,p,_ in self.device.calls)
        with self.assertRaisesRegex(TeachingError,'stopped'):
            self.adapter.run_action('full_calibration',stopped,progress=self.operator_answers)
        self.assertFalse(any(p=='calibration/channel-height-squeeze' for _,p,_ in self.device.calls))

    def test_closed_door_prompt_also_waits_for_operator(self):
        ticket=dict(request_id='door',action='full_calibration',status='running')
        self.adapter.active=ticket
        self.adapter.prompt=dict(id='door-view',action='full_calibration',text='Close the door',data={})
        self.adapter.calibration_prompt(ticket)
        self.assertIsNotNone(self.adapter.prompt)
        self.assertFalse(self.device.calls)
        self.adapter.respond('door-view','Ok')
        self.assertIsNone(self.adapter.prompt)
        self.assertEqual(self.device.calls[-1][1],'calibration/close-view')

    def test_native_deck_and_needle_instruction_waits_for_operator(self):
        ticket=dict(request_id='physical-setup',action='full_calibration',status='running')
        self.adapter.active=ticket
        instruction=('Ensure the deck is clear of all labware and that the teaching needle occupies its correct location '
                     'on the waste bar. Close the door and press Next.')
        self.adapter.prompt=dict(id='native-setup',action='full_calibration',text=instruction,data=dict(inputType=None))
        for _ in range(3):self.adapter.calibration_prompt(ticket)
        self.assertEqual(self.adapter.prompt['id'],'native-setup')
        self.assertFalse(any(m!='GET' for m,_,_ in self.device.calls))
        # Only an explicit response to this exact native instruction advances it.
        self.adapter.respond('native-setup','Ok')
        self.assertIsNone(self.adapter.prompt)
        self.assertEqual(sum(p=='calibration/close-view' for _,p,_ in self.device.calls),1)

    def test_unknown_physical_door_instruction_is_not_auto_accepted(self):
        ticket=dict(request_id='new-setup',action='full_calibration',status='running')
        self.adapter.active=ticket
        self.adapter.prompt=dict(id='physical',action='full_calibration',text='Move the holder. Close the door.',data={})
        self.adapter.calibration_prompt(ticket)
        self.assertIsNotNone(self.adapter.prompt)
        self.assertFalse(self.device.calls)

    def test_aborted_idle_does_not_send_another_abort(self):
        ticket=dict(request_id='aborted',action='channel_calibration',write_attempted=True,terminal_event='aborted')
        self.adapter.active=ticket
        self.adapter.finish_abort(Events(self.adapter),ticket)
        self.assertEqual(ticket['status'],'aborted')
        self.assertTrue(all(m=='GET' for m,_,_ in self.device.calls))

    def test_negative_completion_text_is_not_a_pass(self):
        for text in ('Calibration unsuccessful','Calibration not successful','Calibration failed'):
            ticket=dict(request_id='negative',action='self_calibration')
            self.device.events=[('instinctevents',dict(code='calibrationdata',data=dict(
                id='result',spinnerShown=False,textSections=[[text]])))]
            self.adapter.consume(Events(self.adapter),ticket)
            self.assertFalse(ticket.get('stage_success_display'))

    def test_prompt_response_cannot_be_sent_twice(self):
        self.adapter.active=dict(request_id='once',action='self_calibration',status='running')
        self.adapter.prompt=dict(id='one',action='self_calibration',data={})
        self.adapter.respond('one','Ok')
        with self.assertRaisesRegex(TeachingError,'no longer active'):self.adapter.respond('one','Ok')
        self.assertEqual(sum(m=='POST' for m,_,_ in self.device.calls),1)

    def test_verified_abort_removes_stale_setup_prompt(self):
        with self.adapter.owned('full_calibration') as ticket:
            ticket['status']='aborted'
            self.adapter.prompt=dict(id='stopped-setup',action='full_calibration',data={})
        self.assertIsNone(self.adapter.prompt)
        with self.assertRaisesRegex(TeachingError,'no longer active'):
            self.adapter.respond('stopped-setup','Ok')
        self.assertFalse(self.device.calls)

    def test_stop_before_calibration_sends_no_start_or_initialize(self):
        with self.assertRaisesRegex(TeachingError,'stopped'):self.adapter.run_action('full_calibration',lambda:True)
        self.assertTrue(all(m=='GET' for m,_,_ in self.device.calls))

    def test_current_error_detected_even_with_empty_pending_endpoint(self):
        plan=self.adapter.prepare('Water');ticket=self.adapter.start(plan,'p',lambda x:None)
        self.device.errors=[{'id':'new','message':'Front Channel channel motor stalled'}]
        with self.assertRaisesRegex(TeachingError,'motor stalled'):
            self.adapter.wait(plan,ticket,lambda x:None,lambda:False,lambda x:None)
        self.assertFalse(any(x[1]=='protocol-run/load-complete' for x in self.device.calls))

    def test_websocket_error_and_connection_loss_fail_closed(self):
        for channel,event in [('connection_lost','closed'),('instincterrors',{'id':'bad','handled':False,'message':'fault'})]:
            self.device.events=[(channel,event)]
            with self.assertRaises(TeachingError):self.adapter.consume(Events(self.adapter),{'request_id':'test'})

    def test_native_fault_summary_preserves_specific_nested_errors(self):
        errors=[dict(message='GenericBusy',errorData=[dict(message='3844: The calibration tool was not detected')]),
                dict(message='Front Channel Z Out of Bounds')]
        summary=error_summary(errors)
        self.assertIn('3844',summary);self.assertIn('Z Out of Bounds',summary)
        self.assertNotIn('GenericBusy',summary)
        self.assertEqual(error_summary([dict(message='GenericBusy')]),'GenericBusy')
        self.device.errors=errors
        with self.assertRaisesRegex(TeachingError,'3844'):
            self.adapter.guard_errors(dict(request_id='native-error'),set())

    def test_nested_event_and_stale_prompt(self):
        self.device.events=[('instinctevents',{'code':'generic','data':json.dumps({'Name':'ShowCustomDialog','Payload':'view-1'})})]
        ticket={'request_id':'prompt-test','action':'self_calibration','status':'running'};self.adapter.active=ticket
        self.adapter.consume(Events(self.adapter),ticket)
        self.assertEqual(self.adapter.prompt['id'],'view-1')
        with self.assertRaisesRegex(TeachingError,'no longer active'):self.adapter.respond('old','Ok')
        self.adapter.respond('view-1','Ok');self.assertIsNone(self.adapter.prompt)

    def test_wrong_serial_and_nonlocal_url_block(self):
        self.device.info[0]='Serial Number: different'
        with self.assertRaises(TeachingError):self.adapter.preflight()
        self.settings['base_url']='http://example.com/NimbusLite/api/v1';self.config.write_text(json.dumps(self.settings))
        with self.assertRaises(TeachingError):self.adapter.settings()

    def test_unknown_protocol_and_missing_recipe_are_blockers(self):
        with self.assertRaisesRegex(TeachingError,'commissioned'):self.adapter.prepare('invented')

    def test_stale_run_id_cannot_confirm_pickup(self):
        plan=self.adapter.prepare('Water')
        with self.assertRaisesRegex(TeachingError,'not bound'):self.adapter.completed_for_pickup(plan,{'job_id':'old'})

    def test_concurrent_operation_rejected(self):
        with self.adapter.owned('initialize') as ticket:
            with self.assertRaisesRegex(TeachingError,'owns'):self.adapter.run_action('initialize')
            ticket['status']='aborted'

    def test_decoding_nested_json(self):
        self.assertEqual(decoded(json.dumps(json.dumps({'code':'finished'}))),{'code':'finished'})


if __name__=='__main__':unittest.main()
