"""Lacry plans through the clean lab API; only the researcher's Yes starts it. Fake machines only."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[2]))

from lacry_agent import LacryAgent  # noqa: E402
from lacry_facade import LabApi, PRESENCE  # noqa: E402
from researcher_teaching import TeachingError  # noqa: E402
from sequences import Runner  # noqa: E402
from labfacade import Facade, Signer, load_manifests  # noqa: E402
from labfacade.fakes import FakeMachine  # noqa: E402

FIXTURES = HERE.parents[2] / 'labfacade' / 'tests' / 'fixtures' / 'machines'
SCHEMA = HERE.parents[2] / 'machines' / 'manifest.schema.json'


def tool_call(name, **arguments):
    return dict(stop_reason='tool_use', content=[dict(type='tool_use', id='t-' + name, name=name, input=arguments)])


def text(reply):
    return dict(stop_reason='end_turn', content=[dict(type='text', text=reply)])


class LabApiTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='lacry_lab_api_'))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.fakes = dict(
            hamilton_prep=FakeMachine(sensors={'door_closed': True}, conditions={'initialized': True, 'parked': True}),
            bioyond_s4=FakeMachine(conditions={'plate released': True}),
            squid=FakeMachine(conditions={'no scan running': True, 'at loading position': True,
                                          'acquisition complete': True}))
        self.signer = Signer(b'lacry-test-key-0123456789')
        self.facade = Facade.from_manifests(load_manifests(FIXTURES, SCHEMA), self.fakes, self.signer, self.root / 'runs')
        self.run = Runner()
        self.client = Mock()
        self.agent = LacryAgent(Mock(), Mock(), lambda: self.run, client=self.client)
        self.agent.lab_api = LabApi(self.agent, facade=self.facade, signer=self.signer, runs=self.root / 'runs')
        self.agent.public = Mock(return_value={'ok': True})

    def ask(self, *responses, message='Park the Hamilton'):
        self.client.complete.side_effect = list(responses)
        self.agent.send(message)

    def finish(self):
        self.agent.lab_api.job['thread'].join(10)
        self.assertFalse(self.agent.lab_api.active)

    def test_model_sees_the_lab_tools_and_none_that_grant(self):
        self.ask(text('Hello.'), message='What can the machines do?')
        names = [t['name'] for t in self.client.complete.call_args.args[0]['tools']]
        for name in ('lab_describe', 'lab_status', 'plan_lab_operation'):
            self.assertIn(name, names)
        for word in ('approve', 'attest', 'confirm', 'override', 'resume', 'sign'):
            self.assertFalse(any(word in n.split('_') for n in names), word)
        self.assertIn('Clean lab API', self.client.complete.call_args.args[0]['system'])

    def plate_memory(self):
        from lacry_memory import LacryMemory
        from plate_registry import PlateRegistry
        registry = PlateRegistry(self.root/'plates.sqlite3')
        registry.record_scan(dict(at='2026-11-11T20:00:00+00:00',result='decoded',barcode='001',
            framed=True,response_hex=b'001\x04'.hex()),'offline test')
        self.agent.memory = LacryMemory(self.root/'memory.sqlite3',plate_registry=registry)
        return registry

    def test_plate_run_uses_exact_scanned_id_and_packages_identity(self):
        registry = self.plate_memory()
        with patch.dict('lacry_facade.PLATE_STEPS', {('bioyond_s4','pick_plate'):('squid stage','gripper')}):
            self.ask(tool_call('plan_lab_operation', machine='bioyond_s4',operation='pick_plate',
                               params={'station':'squid'},plate_id='001'), text('Plan ready.'))
            plan = self.agent.pending
            self.assertEqual(plan['lab_plan']['plates'], {'001':'squid stage'})
            self.assertEqual(plan['lab_plan']['steps'][0]['transfer']['plate'], '001')
            self.assertIn('actual plate ID is "001"', plan['confirmations'])
            self.agent.send('Yes')
            self.finish()
        folder = Path(self.agent.lab_api.last['run_folder'])
        self.assertEqual(json.loads((folder/'plate_identity.json').read_text())['plate']['plate_id'],'001')
        self.assertEqual(registry.get('001',history=True)['history'][0]['data']['outcome'],'completed')
        self.assertEqual(registry.get('001')['location'],'unknown')

    def test_plate_identity_missing_unknown_and_stale_refuse_before_motion(self):
        registry = self.plate_memory()
        with self.assertRaisesRegex(TeachingError, 'exact scanned plate ID'):
            self.agent.lab_api.propose('bioyond_s4','run_plate_workflow')
        with self.assertRaisesRegex(TeachingError, 'No scanned plate'):
            self.agent.lab_api.propose('bioyond_s4','run_plate_workflow',plate_id='999')
        self.agent.lab_api.propose('bioyond_s4','pick_plate',{'station':'squid'},plate_id='001')
        plan = self.agent.pending
        row = registry.get('001')
        registry.update('001',row['revision'],{'contents':'DNA'},'researcher')
        with self.assertRaisesRegex(TeachingError, 'changed after planning'):
            self.agent.lab_api.start(plan)
        self.assertEqual(self.fakes['bioyond_s4'].commands, [])

    def test_plan_then_yes_runs_once_and_logs(self):
        self.ask(tool_call('plan_lab_operation', machine='hamilton_prep', operation='park'), text('Plan ready.'))
        plan = self.agent.pending
        self.assertEqual(plan['dispatch'], 'labfacade')
        self.assertIn(PRESENCE, plan['requirements'])
        self.assertEqual(plan['checked'], ['door closed', 'initialized'])         # sensors and live checks
        self.assertEqual(self.fakes['hamilton_prep'].commands, [])               # planning sends nothing

        self.agent.send('Yes')
        self.finish()
        self.assertEqual([c['name'] for c in self.fakes['hamilton_prep'].commands], ['park'])
        run = Path(self.agent.lab_api.last['run_folder'])
        approval = json.loads((run / 'approval.json').read_text())
        self.assertEqual(approval['approver'], 'researcher via Lacry (researcher_chat)')
        self.assertTrue(self.signer.verify(approval))
        self.assertEqual(self.agent.lab_api.last['outcome'], 'completed')
        self.assertTrue(self.agent.run_state['ok'])
        self.assertIn('completed through the clean lab API', self.agent.transcript[-1]['text'])
        self.assertIsNone(self.agent.pending)

        self.agent.send('yes')                                                  # a second Yes starts nothing
        self.assertEqual(len(self.fakes['hamilton_prep'].commands), 1)

    def test_gates_no_sensor_can_answer_are_listed_and_signed(self):
        self.ask(tool_call('plan_lab_operation', machine='bioyond_s4', operation='pick_plate',
                           params={'station': 'squid'}), text('Plan ready.'))
        plan = self.agent.pending
        self.assertEqual(plan['confirmations'], ['path clear'])
        self.assertIn('Confirm: path clear.', plan['requirements'])
        self.assertNotIn(PRESENCE, plan['requirements'])                         # qualified, no E-stop gate
        self.agent.send('Yes')
        self.finish()
        self.assertEqual(self.agent.lab_api.last['outcome'], 'completed')

    def test_blocked_or_unwired_operation_is_refused_without_a_plan(self):
        for operation in ('plate_transfer', 'self_destruct'):
            self.ask(tool_call('plan_lab_operation', machine='hamilton_prep', operation=operation), text('No.'))
            self.assertIsNone(self.agent.pending)
            self.assertIn('Nothing was planned or started', self.agent.transcript[-1]['text'])
        self.fakes['squid'].unbound.add('return_to_loading')
        self.ask(tool_call('plan_lab_operation', machine='squid', operation='return_to_loading'), text('No.'))
        self.assertIn('not wired', self.agent.transcript[-1]['text'])
        self.assertTrue(all(f.commands == [] for f in self.fakes.values()))

    def test_out_of_limit_parameter_is_refused(self):
        self.ask(tool_call('plan_lab_operation', machine='hamilton_prep', operation='open_jaws',
                           params={'y_step': 0.8}), text('No.'))
        self.assertIsNone(self.agent.pending)
        self.assertIn('outside the limit', self.agent.transcript[-1]['text'])

    def test_condition_not_met_now_is_a_preview_only(self):
        self.fakes['hamilton_prep'].conditions['initialized'] = False
        self.ask(tool_call('plan_lab_operation', machine='hamilton_prep', operation='park'), text('Plan ready.'))
        self.assertFalse(self.agent.pending['executable'])
        with self.assertRaisesRegex(TeachingError, 'preview only'):
            self.agent.send('Yes')
        self.assertEqual(self.fakes['hamilton_prep'].commands, [])

    def test_read_only_operation_runs_at_once_without_a_plan(self):
        self.ask(tool_call('plan_lab_operation', machine='squid', operation='get_status'), text('Idle.'))
        self.assertIsNone(self.agent.pending)
        self.assertEqual([c['name'] for c in self.fakes['squid'].commands], ['get_status'])

    def test_describe_and_status_are_read_only(self):
        content, error = self.agent.lab_api.run_tool('lab_describe', {})
        listing = json.loads(content)['machines']
        self.assertFalse(error)
        self.assertEqual({m['machine'] for m in listing}, {'hamilton_prep', 'bioyond_s4', 'squid'})
        detail = json.loads(self.agent.lab_api.run_tool('lab_describe', dict(machine='hamilton_prep',
                                                                              operation='plate_transfer'))[0])
        self.assertEqual(detail['qualification']['status'], 'blocked')
        self.fakes['squid'].status_age_s = 60
        status = json.loads(self.agent.lab_api.run_tool('lab_status', dict(machine='squid'))[0])
        self.assertEqual(status['state'], 'unknown')
        self.assertTrue(all(f.commands == [] for f in self.fakes.values()))

    def test_machine_not_idle_at_yes_starts_nothing(self):
        self.ask(tool_call('plan_lab_operation', machine='hamilton_prep', operation='park'), text('Plan ready.'))
        self.fakes['hamilton_prep'].state = 'busy'
        with self.assertRaisesRegex(TeachingError, 'busy'):
            self.agent.send('Yes')
        self.assertEqual(self.fakes['hamilton_prep'].commands, [])

    def test_timeout_is_reported_not_retried_and_blocks_other_plans_while_running(self):
        self.fakes['hamilton_prep'].behaviors['park'] = dict(hang=1.0)
        self.ask(tool_call('plan_lab_operation', machine='hamilton_prep', operation='park'), text('Plan ready.'))
        self.agent.send('Yes')
        self.assertTrue(self.agent.lab_api.active)
        self.agent.pending = dict(id='other', at=time.time(), labels=['x'], steps=[], requirements=[])
        with self.assertRaisesRegex(TeachingError, 'in progress'):
            self.agent.confirm(dict(ready=True, plan_id='other'))
        stopped = self.agent.stop()
        self.assertIn('Stop requested', stopped['message'])
        self.assertIsNone(self.agent.lab_api.stop())                             # only once
        self.finish()
        self.assertEqual(len(self.fakes['hamilton_prep'].commands), 1)
        self.assertEqual(self.fakes['hamilton_prep'].aborts, 1)
        self.assertIn(self.agent.lab_api.last['outcome'], ('unknown',))
        self.assertIn('Nothing was retried', self.agent.transcript[-1]['text'])

    def test_without_labfacade_installed_no_tools_are_offered(self):
        api = LabApi(self.agent)
        api.__class__ = type('Missing', (LabApi,), {'available': property(lambda self: False)})
        self.assertEqual(api.tools(), [])
        content, error = api.run_tool('lab_status', dict(machine='squid'))
        self.assertTrue(error and 'not installed' in content)


if __name__ == '__main__':
    unittest.main()
