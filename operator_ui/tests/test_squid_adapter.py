"""Native acquisition outcomes, stale records and failed links; no hardware."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from squid_adapter import SquidAdapter, read_command
from lacry_agent import LacryAgent


class SquidAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now=1000.
        self.owner=dict(pid=123,created_at=900.,simulation=True,
                        state_file=str(Path(self.tmp.name)/'run.json'))
        self.api=dict(in_progress=False)
        self.adapter=SquidAdapter(identify=lambda:deepcopy(self.owner),
            request=lambda name:dict(status='ok') if name=='ping' else deepcopy(self.api),
            clock=lambda:self.now,background=False,
            log_path=Path(self.tmp.name)/'events.jsonl')
        self.events=[]
        self.adapter.on_event=self.events.append

    def record(self,**changes):
        record=dict(schema_version=1,run_id='job-1',pid=123,started_at=1001.,
                    heartbeat_at=1001.,experiment_id='plate-test',status='running',
                    reason=None,ended_at=None,progress={'fov':1},expected={'fovs':1},
                    stats=None,output_path='mock-images')
        record.update(changes)
        Path(self.owner['state_file']).write_text(json.dumps(record))
        self.api['experiment_id']=record['experiment_id']
        return record

    def complete(self,reason='completed',**changes):
        return self.record(status='ended',reason=reason,ended_at=self.now,
                           stats=dict(total_images=1,errors_encountered=0),**changes)

    def test_connect_reads_only_and_monitor_reports_exact_mock_job(self):
        self.assertFalse(self.adapter.status()['connected'])
        self.adapter.connect()
        self.now=1002.;self.api['in_progress']=True;self.record()
        self.assertEqual(self.adapter.poll()['status'],'running')
        self.api['in_progress']=False;self.complete()
        result=self.adapter.poll()
        self.assertEqual(result['status'],'completed')
        self.assertTrue(result['completion_confirmed'])
        self.assertFalse(result['real_imaging_complete'])
        self.assertFalse(result['retrieval_authorized'])
        self.assertEqual(result['job']['run_id'],'job-1')
        count=len(self.events);self.adapter.poll();self.assertEqual(len(self.events),count)
        with self.assertRaises(Exception):self.adapter.job_status('different-job')
        self.assertGreater(len(self.adapter.log_path.read_text().splitlines()),1)

    def test_finished_worker_is_not_complete_while_controller_still_busy(self):
        self.adapter.connect();self.now=1002.;self.complete()
        self.api['in_progress']=True
        self.assertEqual(self.adapter.poll()['status'],'finishing')
        self.assertFalse(self.adapter.status()['completion_confirmed'])

    def test_status_accepts_current_run_or_experiment_identity(self):
        self.adapter.connect();self.now=1002.;self.complete();self.adapter.poll()
        job=self.adapter.status()['job']
        for identity in (job['run_id'],job['experiment_id']):
            self.assertTrue(self.adapter.job_status(identity)['completion_confirmed'])

    def test_verified_completion_survives_host_reload_but_not_native_job_change(self):
        self.adapter.connect();self.now=1002.;self.complete();self.adapter.poll()
        self.now=1004.;self.adapter.enabled=False
        self.assertTrue(self.adapter.connect()['completion_confirmed'])
        self.adapter.enabled=False
        self.complete(run_id='other',started_at=1002.)
        self.assertFalse(self.adapter.connect()['completion_confirmed'])

    def test_uncertain_connection_invalidates_completion_receipt(self):
        self.adapter.connect();self.now=1002.;self.complete();self.adapter.poll()
        original=self.adapter.request
        self.adapter.request=Mock(side_effect=OSError('lost connection'))
        self.assertFalse(self.adapter.poll()['completion_confirmed'])
        self.adapter.request=original;self.now=1004.
        self.assertFalse(self.adapter.connect()['completion_confirmed'])

    def test_real_stage_mock_camera_completion_is_not_real_imaging(self):
        self.owner.update(stage_simulated=False,camera_simulated=True)
        self.adapter.connect();self.now=1002.;self.complete()
        self.api['cleanup']=dict(version=1,status='completed',experiment_id='plate-test')
        result=self.adapter.poll()
        self.assertTrue(result['completion_confirmed'])
        self.assertFalse(result['real_imaging_complete'])
        self.assertFalse(result['stage_simulated'])
        self.assertIn('real-stage test',result['message'])

    def test_images_finished_does_not_mean_stage_cleanup_finished(self):
        self.owner.update(stage_simulated=False,camera_simulated=True)
        self.adapter.connect();self.now=1002.;self.complete()
        self.assertEqual(self.adapter.poll()['status'],'cleanup_unverified')
        for status,expected in [('pending','finishing'),('running','finishing'),('failed','failed')]:
            self.api['cleanup']=dict(version=1,status=status,experiment_id='plate-test')
            state=self.adapter.poll()
            self.assertEqual(state['status'],expected)
            self.assertFalse(state['completion_confirmed'])
        self.api['cleanup']=dict(version=1,status='completed',experiment_id='other')
        self.assertFalse(self.adapter.poll()['completion_confirmed'])
        self.api['cleanup']['experiment_id']='plate-test'
        self.assertTrue(self.adapter.poll()['completion_confirmed'])

    def test_old_or_wrong_process_record_never_confirms_current_plate(self):
        self.complete(started_at=950.)
        self.adapter.connect()
        self.assertEqual(self.adapter.status()['status'],'historical')
        self.assertFalse(self.adapter.status()['completion_confirmed'])
        self.complete(pid=999)
        self.assertIsNone(self.adapter.poll()['job'])

    def test_abort_error_partial_and_missing_stats_never_succeed(self):
        self.adapter.connect();self.now=1002.
        for reason in ('user_abort','error','completed_with_errors','unrecognized'):
            self.complete(reason)
            self.assertFalse(self.adapter.poll()['completion_confirmed'],reason)
        self.record(status='ended',reason='completed',ended_at=1002.,stats={})
        self.assertFalse(self.adapter.poll()['completion_confirmed'])

    def test_disconnect_then_finish_is_uncertain_and_restart_needs_connect(self):
        self.adapter.connect();self.now=1002.;self.api['in_progress']=True
        self.record();self.adapter.poll()
        request=self.adapter.request
        self.adapter.request=Mock(side_effect=OSError('offline'))
        self.assertFalse(self.adapter.poll()['connected'])
        self.adapter.request=request;self.api['in_progress']=False;self.complete()
        self.assertEqual(self.adapter.poll()['status'],'unknown')
        self.assertFalse(self.adapter.status()['completion_confirmed'])
        self.owner['created_at']=1005.
        self.assertFalse(self.adapter.poll()['connected'])

    def test_stale_heartbeat_bad_json_and_stale_poll_cannot_confirm(self):
        self.adapter.connect();self.now=1100.;self.api['in_progress']=True
        self.record(heartbeat_at=1002.)
        self.assertEqual(self.adapter.poll()['status'],'unknown')
        Path(self.owner['state_file']).write_text('{broken')
        self.assertFalse(self.adapter.poll()['connected'])
        self.adapter.snapshot.update(connected=True,checked_at=1000.,completion_confirmed=True,
                                     real_imaging_complete=True)
        self.assertFalse(self.adapter.status()['completion_confirmed'])
        self.assertFalse(self.adapter.status()['real_imaging_complete'])

    def test_real_completed_job_is_distinct_from_mock(self):
        self.owner['simulation']=False
        self.adapter.connect();self.now=1002.;self.complete()
        self.assertTrue(self.adapter.poll()['real_imaging_complete'])

    def test_read_transport_never_accepts_imaging_or_motion_commands(self):
        for command in ('run_acquisition','move_to','execute_python','abort_acquisition'):
            with self.assertRaises(ValueError):read_command(command)

    def test_agent_announces_completion_without_planning_or_moving(self):
        backend=Mock();backend.squid=self.adapter;run=Mock(active=False,reserved=False)
        agent=LacryAgent(backend,Mock(),lambda:run,client=Mock())
        agent.link('squid')
        self.now=1002.;self.complete();self.adapter.poll()
        self.assertIn('mock imaging complete',agent.transcript[-1]['text'])
        self.assertIsNone(agent.pending)
        backend.execute_step.assert_not_called()
        run.start.assert_not_called()
        result,error=agent._run_tool('get_squid_status',{'job_id':'job-1'})
        self.assertFalse(error)
        self.assertTrue(json.loads(result)['simulation'])


if __name__=='__main__':unittest.main()
