"""Researcher status and production routing; all physical services mocked."""
from pathlib import Path
import tempfile
import threading
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from researcher import public_status
from researcher_teaching import StationTeaching, TeachingError
import os
_audit_storage = tempfile.TemporaryDirectory(prefix='cephla_audit_test_')
from lacry_memory import LacryMemory
_test_memory = LacryMemory(Path(_audit_storage.name)/'memory.sqlite3')
with patch.dict(os.environ, {'CEPHLA_AUDIT_DIR':_audit_storage.name}), \
        patch('lacry_memory.LacryMemory', return_value=_test_memory):
    import app as console

# API middleware invalidates Grip readiness on other actions. Never let fake
# requests consume the real robot's persisted descent receipt.
console.position_grip.folder = Path(_audit_storage.name) / 'position_grip'
console.position_grip.receipt = None


class ResearcherTests(unittest.TestCase):
    def test_home_area_routes_to_home_executor(self):
        with patch.object(console,'runner',SimpleNamespace(active=False)), \
                patch.object(console.home_return,'start',return_value=dict(ok=True)) as start:
            body=dict(ready=True,target_id='area')
            response=console.app.test_client().post('/researcher/api/home/area',json=body)
            self.assertEqual(response.status_code,200)
            start.assert_called_once_with({**body,'destination':'home_area'})

    def test_coactive_capture_is_developer_only_and_read_only_during_hand_guiding(self):
        with patch.object(console.draggo,'latched',True), \
                patch.object(console.coactive_pickup,'capture',return_value=dict(ok=True,message='saved')) as capture, \
                patch.object(console.svc,'program') as program:
            client=console.app.test_client()
            body=dict(action='Descend',reference_id='current',manually_demonstrated=True)
            self.assertEqual(client.post('/developer/api/coactive/capture',json=body).status_code,200)
            capture.assert_called_once_with(body);program.assert_not_called()
            self.assertEqual(client.post('/researcher/api/coactive/capture',json=body).status_code,404)

    def test_latest_route_dispatch_and_stop_ownership(self):
        with patch.object(console,'runner',SimpleNamespace(active=False)), \
                patch.object(console.latest_hamilton,'start',return_value=dict(ok=True)) as start:
            body=dict(ready=True,path_id='latest',direction='toward_home')
            self.assertEqual(console.app.test_client().post('/researcher/api/latest-hamilton/start',json=body).status_code,200)
            start.assert_called_once_with(body)
        with patch.object(console,'runner',SimpleNamespace(active=True)), \
                patch.object(console.latest_hamilton,'start') as start, \
                patch.object(console.latest_hamilton,'stop',return_value=dict(ok=True)) as stop:
            client=console.app.test_client()
            self.assertEqual(client.post('/researcher/api/latest-hamilton/start',json={}).status_code,409)
            start.assert_not_called()
            self.assertEqual(client.post('/researcher/api/latest-hamilton/stop',json={}).status_code,200)
            stop.assert_called_once()

    def test_haiku_credentials_are_not_blocked_by_hand_guiding(self):
        with patch.object(console.draggo,'latched',True), \
                patch.object(console.plate_agent.client,'set_key') as set_key, \
                patch.object(console.plate_agent.client,'ready',return_value=True), \
                patch.object(console.imitation,'invalidate') as invalidate:
            response=console.app.test_client().post('/agent/settings',json={'api_key':'test-value'})
            self.assertEqual(response.status_code,200)
            set_key.assert_called_once_with('test-value')
            invalidate.assert_not_called()

    def test_imitation_dispatch_busy_and_stop(self):
        with patch.object(console,'runner',SimpleNamespace(active=False)), \
                patch.object(console.imitation,'start',return_value=dict(ok=True)) as start:
            response = console.app.test_client().post('/researcher/api/imitation/Descend',json={'reference_id':'reviewed'})
            self.assertEqual(response.status_code,200)
            start.assert_called_once_with('Descend',{'reference_id':'reviewed'})
        with patch.object(console,'runner',SimpleNamespace(active=True)), \
                patch.object(console.imitation,'start') as start, \
                patch.object(console.imitation,'stop',return_value=dict(ok=True)) as stop:
            client = console.app.test_client()
            self.assertEqual(client.post('/researcher/api/imitation/Grip',json={}).status_code,409)
            start.assert_not_called()
            self.assertEqual(client.post('/researcher/api/imitation/stop',json={}).status_code,200)
            stop.assert_called_once()

    def test_manual_activity_invalidates_imitation_progress(self):
        with patch.object(console,'runner',SimpleNamespace(active=False)), \
                patch.object(console.imitation,'invalidate') as invalidate, \
                patch.object(console.draggo,'change',return_value=dict(ok=True)):
            console.app.test_client().post('/researcher/api/hand-guiding/start',json={'ready':True})
            invalidate.assert_called_once()

    def test_end_hand_guiding_cannot_interrupt_automatic_calibration(self):
        stopped = []
        with patch.object(console, 'runner', SimpleNamespace(active=True, request_stop=lambda:stopped.append(True))), \
                patch.object(console.plate_teaching, 'active_step', 'Calibrate'), \
                patch.object(console.draggo, 'change', return_value={'ok':True}) as change:
            response = console.app.test_client().post('/researcher/api/hand-guiding/end', json={})
            self.assertEqual(response.status_code,409)
            self.assertEqual(stopped,[])
            change.assert_not_called()

    def test_workflow_route_and_stop_ownership(self):
        with patch.object(console, 'runner', SimpleNamespace(active=False)), \
                patch.object(console.plate_teaching, 'start', return_value=dict(ok=True)) as start:
            response = console.app.test_client().post('/researcher/api/workflow/Calibrate', json={'ready':True})
            self.assertEqual(response.status_code, 200)
            start.assert_called_once_with('Calibrate', {'ready':True})
        with patch.object(console, 'runner', SimpleNamespace(active=True)), \
                patch.object(console.plate_teaching, 'start') as start, \
                patch.object(console.plate_teaching, 'stop', return_value=dict(ok=True)) as stop:
            client = console.app.test_client()
            self.assertEqual(client.post('/researcher/api/workflow/Align', json={'ready':True}).status_code,409)
            start.assert_not_called()
            self.assertEqual(client.post('/researcher/api/workflow/stop', json={}).status_code,200)
            stop.assert_called_once()

    def test_draggo_routes_use_shared_guard_and_invalidate_pickup(self):
        with patch.object(console, 'runner', SimpleNamespace(active=False)), \
                patch.object(console.draggo, 'change', return_value=dict(ok=True)) as change, \
                patch.object(console.pickup, 'invalidate') as invalidate:
            client = console.app.test_client()
            self.assertEqual(client.post('/researcher/api/hand-guiding/start', json={'ready':True}).status_code, 200)
            change.assert_called_once_with(True, ready=True)
            invalidate.assert_called_once()
            self.assertEqual(client.post('/researcher/api/hand-guiding/end', json={}).status_code, 200)
            self.assertEqual(change.call_args.args, (False,))

    def test_draggo_blocks_developer_commands_but_not_disable(self):
        with patch.object(console, 'runner', SimpleNamespace(active=False, request_stop=lambda: None)), \
                patch.object(console.draggo, 'latched', True), \
                patch.object(console.draggo, 'cancel') as cancel, \
                patch.object(console, 'svc') as svc:
            svc.set_enable.return_value = dict(ok=True)
            client = console.app.test_client()
            for path in ('/mode', '/enable', '/jog', '/disconnect', '/seq/find_disk'):
                self.assertEqual(client.post(path, json={}).status_code, 409)
            self.assertEqual(svc.mock_calls, [])
            self.assertEqual(client.post('/disable', json={}).status_code, 200)
            cancel.assert_called_once()

    def test_unknown_hand_guiding_blocks_capture(self):
        with patch.object(console, 'runner', SimpleNamespace(active=False)), \
                patch.object(console.draggo, 'public', return_value=dict(state='unknown', message='Check hand-guiding.')), \
                patch.object(console, 'svc') as svc, \
                patch.object(console.researcher_teaching, 'capture') as capture:
            response = console.app.test_client().post('/researcher/api/teaching/capture', json={})
            self.assertEqual(response.status_code, 409)
            capture.assert_not_called()

    def test_public_state_does_not_leak_errors_coordinates_or_false_capabilities(self):
        result = public_status(
            dict(ok=False, connected=True, error='SECRET TRACE', pose_mm={'X': 123}),
            dict(open=False, error='SECRET CAMERA ERROR'), dict(active=True))
        self.assertNotIn('SECRET', str(result))
        self.assertNotIn('pose_mm', result)
        self.assertEqual(result['robot'], 'Robot status unavailable')
        self.assertEqual(result['camera'], 'Camera disconnected')
        self.assertTrue(result['busy'])
        self.assertFalse(any(result['capabilities'].values()))
        self.assertEqual(result['routines'], [])

    def test_stale_camera_is_not_healthy(self):
        for age in (None, 6, 2000):
            result = public_status(dict(ok=True, connected=True), dict(open=True, enabled=True, age_s=age), {})
            self.assertEqual(result['camera'], 'Camera image unavailable')
        result = public_status(dict(ok=True, connected=True), dict(open=True, enabled=True, age_s=1), {})
        self.assertEqual(result['camera'], 'Camera connected')
        self.assertFalse(result['capabilities']['run'])

    def test_views_do_not_query_or_command_devices(self):
        with patch.object(console, 'svc') as svc, patch.object(console, 'cam') as cam:
            client = console.app.test_client()
            for path in ('/', '/researcher'):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'lacry.js', response.data)
                self.assertNotIn(b'torque_threshold', response.data)
                response.close()
            # The stage-by-stage console it replaced stays served, unchanged.
            with client.get('/researcher/classic') as response:
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'researcher.js', response.data)
                self.assertNotIn(b'torque_threshold', response.data)
            with client.get('/developer') as response:
                self.assertIn(b'Cephla Developer Console', response.data)
            self.assertEqual(svc.mock_calls, [])
            self.assertEqual(cam.mock_calls, [])

    def test_status_reads_shared_service_only(self):
        with patch.object(console, 'svc') as svc, patch.object(console, 'cam') as cam, \
                patch.object(console, 'runner', SimpleNamespace(active=False)):
            svc.status.return_value = dict(ok=True, connected=False)
            cam.info.return_value = dict(open=False)
            response = console.app.test_client().get('/researcher/api/status')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['robot'], 'Robot disconnected')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertEqual([c[0] for c in svc.mock_calls], ['status'])
            self.assertEqual([c[0] for c in cam.mock_calls], ['info'])

    def test_exceptions_are_logged_but_not_shown(self):
        with patch.object(console.svc, 'status', side_effect=RuntimeError('sensitive device detail')), \
                patch.object(console.app.logger, 'exception') as log:
            response = console.app.test_client().get('/researcher/api/status')
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('sensitive', response.get_data(as_text=True))
            log.assert_called_once()

    def test_direct_actions_cannot_bypass_unavailable_backend_or_mutate_other_sequence(self):
        with patch.object(console, 'svc') as svc, patch.object(console, 'cam') as cam, \
                patch.object(console, 'runner', SimpleNamespace(active=True)), \
                patch.object(console.pickup, 'invalidate') as invalidate:
            client = console.app.test_client()
            for action in ('record', 'save', 'run', 'pause', 'stop'):
                response = client.post('/researcher/api/' + action, json={'kind': 'browser-practice'})
                self.assertEqual(response.status_code, 501)
            self.assertEqual(svc.mock_calls, [])
            self.assertEqual(cam.mock_calls, [])
            invalidate.assert_not_called()

    def test_capture_and_connect_blocked_when_sequence_active(self):
        with patch.object(console, 'runner', SimpleNamespace(active=True)), \
                patch.object(console.researcher_teaching, 'capture') as capture, \
                patch.object(console, 'svc') as svc:
            client = console.app.test_client()
            for path in ('connect', 'teaching/capture', 'teaching/start'):
                response = client.post('/researcher/api/' + path, json={})
                self.assertEqual(response.status_code, 409)
                self.assertIn('lab task', response.json['message'])
            capture.assert_not_called()
            self.assertEqual(svc.mock_calls, [])

    def test_pickup_reservation_blocks_controls_between_steps(self):
        with patch.object(console, 'runner', SimpleNamespace(active=False,reserved=True)), \
                patch.object(console.researcher_teaching,'capture') as capture, \
                patch.object(console,'svc') as svc:
            for path in ('connect','teaching/capture','teaching/start'):
                response=console.app.test_client().post('/researcher/api/'+path,json={})
                self.assertEqual(response.status_code,409)
            capture.assert_not_called()
            self.assertEqual(svc.mock_calls,[])


    def test_busy_manual_command_rejects_capture_without_waiting(self):
        held, release = threading.Event(), threading.Event()
        def own_dispatch():
            with console._dispatch_lock:
                held.set()
                release.wait(5)
        thread = threading.Thread(target=own_dispatch)
        thread.start()
        try:
            self.assertTrue(held.wait(2))
            with patch.object(console.researcher_teaching, 'capture') as capture:
                response = console.app.test_client().post('/researcher/api/teaching/capture', json={})
                self.assertEqual(response.status_code, 409)
                self.assertIn('busy', response.json['message'])
                capture.assert_not_called()
        finally:
            release.set()
            thread.join(2)

    def test_connect_only_opens_shared_transport(self):
        with patch.object(console, 'runner', SimpleNamespace(active=False)), \
                patch.object(console, 'svc') as svc:
            svc.robot.connected = False
            svc.connect.return_value = dict(ok=True)
            response = console.app.test_client().post('/researcher/api/connect', json={})
            self.assertEqual(response.status_code, 200)
            self.assertEqual([c[0] for c in svc.mock_calls], ['connect'])


class FakeService:
    def __init__(self):
        self.robot = SimpleNamespace(connected=True)
        self.pose = dict(X=250., Y=0., Z=200., Rz=0.)
        self.joint = dict(J1=200., J2=10., J3=20., J4=30.)
        self.errors = []
        self.pose_reads = 0

    def status(self):
        return dict(ok=True, connected=self.robot.connected, errors=self.errors, endpoint='fake')

    def pose_mm(self):
        self.pose_reads += 1
        return self.pose.copy()

    def joints(self):
        return self.joint.copy()


class TeachingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'teaching.json'
        self.service = FakeService()
        self.teaching = StationTeaching(self.path, lambda: self.service, settle_seconds=0)
        self.teaching.start(dict(name='Home to Hamilton'))

    def body(self, **extra):
        draft = self.teaching.public()['draft']
        return dict(draft_id=draft['id'], revision=draft['revision'], **extra)

    def test_real_samples_persist_review_export_and_multiple_routines(self):
        self.teaching.capture(self.body(station='Home', pose_mm={'X': 9999}))
        self.service.pose['X'] = 270
        self.teaching.capture(self.body(station='Waypoint'))
        self.service.pose['X'] = 300
        self.teaching.capture(self.body(station='Hamilton'))
        with self.assertRaises(TeachingError):
            self.teaching.edit('save', self.body(reviewed=False))
        result = self.teaching.edit('save', self.body(reviewed=True))
        self.assertIsNone(result['draft'])
        self.assertEqual(len(result['routines']), 1)
        ident = result['routines'][0]['id']
        reopened = StationTeaching(self.path, lambda: self.service)
        raw = reopened.export(ident)
        self.assertEqual(raw['waypoints'][0]['pose_mm']['X'], 250)
        self.assertEqual(raw['waypoints'][2]['pose_mm']['X'], 300)
        self.assertEqual(raw['frame'], dict(tool='T0', user='U0'))
        self.assertFalse(raw['execution']['ready'])
        self.assertEqual(raw['capture_kind'], 'measured_station_waypoints')
        self.assertNotIn('pose_mm', str(result))
        self.assertEqual(reopened.public(), result)
        reopened.start(dict(name='Second attempt'))
        self.assertEqual(len(reopened.public()['routines']), 1)
        self.assertIsNotNone(reopened.public()['draft'])

    def test_order_and_stale_revision_prevent_duplicate_capture(self):
        with self.assertRaisesRegex(TeachingError, 'Home first'):
            self.teaching.capture(self.body(station='Hamilton'))
        old = self.body(station='Home')
        self.teaching.capture(old)
        with self.assertRaisesRegex(TeachingError, 'another window'):
            self.teaching.capture(old)
        self.assertEqual(self.service.pose_reads, 2)
        self.assertEqual(len(self.teaching.public()['draft']['waypoints']), 1)
        self.teaching.edit('undo', self.body())
        self.assertEqual(self.teaching.public()['draft']['waypoints'], [])

    def test_disconnect_fault_and_invalid_measurements_do_not_save(self):
        for connected, errors in ((False, []), (True, ['fault'])):
            self.service.robot.connected = connected
            self.service.errors = errors
            with self.assertRaises(TeachingError):
                self.teaching.capture(self.body(station='Home'))
        self.service.robot.connected = True
        self.service.errors = []
        for value in (float('nan'), float('inf'), None, True):
            self.service.pose['X'] = value
            with self.assertRaises(TeachingError):
                self.teaching.capture(self.body(station='Home'))
        self.assertEqual(self.teaching.public()['draft']['waypoints'], [])

    def test_moving_pose_and_joint_winding_rejected(self):
        before = self.service.pose.copy()
        with patch.object(self.service, 'pose_mm', side_effect=[before, {**before, 'X': before['X']+1}]):
            with self.assertRaisesRegex(TeachingError, 'arm moved'):
                self.teaching.capture(self.body(station='Home'))
        joints = self.service.joint.copy()
        with patch.object(self.service, 'joints', side_effect=[joints, {**joints, 'J4': joints['J4']+360}]):
            with self.assertRaisesRegex(TeachingError, 'arm moved'):
                self.teaching.capture(self.body(station='Home'))
        self.assertEqual(self.teaching.public()['draft']['waypoints'], [])

    def test_atomic_write_failure_keeps_previous_draft(self):
        original = self.path.read_bytes()
        with patch('researcher_teaching.os.replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                self.teaching.capture(self.body(station='Home'))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    def test_discard_removes_only_draft_and_does_not_read_robot(self):
        result = self.teaching.edit('discard', self.body())
        self.assertIsNone(result['draft'])
        self.assertEqual(self.service.pose_reads, 0)

    def test_corrupt_storage_is_not_overwritten(self):
        self.path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(Exception):
            self.teaching.start(dict(name='Do not overwrite'))
        self.assertEqual(self.path.read_text(), '{broken')


if __name__ == '__main__':
    unittest.main()
