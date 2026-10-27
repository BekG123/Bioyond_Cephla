"""Offline request/response, fault, external-axis and asynchronous logging tests."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

from flask import Flask, jsonify, Response

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from audit_log import AuditLog, install_audit
from sequences import Runner
from robot_service import RobotService


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audit = AuditLog(self.tmp.name)
        self.app = Flask(__name__)
        install_audit(self.app,self.audit)
        self.client = self.app.test_client()

    def rows(self):
        return [json.loads(line) for p in sorted(Path(self.tmp.name).rglob('*.jsonl'))
                for line in p.read_text().splitlines()]

    def test_gripper_value_and_response_are_linked_to_developer(self):
        self.app.add_url_rule('/gripper',view_func=lambda:jsonify(ok=True,e1_position=.2),methods=['POST'])
        response = self.client.post('/gripper',json={'action':'move','e1':.2,'speed':2},headers={'X-Cephla-View':'developer'})
        request, reply = self.rows()[-2:]
        self.assertEqual(request['body']['e1'],.2)
        self.assertEqual(reply['body']['e1_position'],.2)
        self.assertEqual(request['request_id'],reply['request_id'])
        self.assertEqual(reply['request_id'],response.headers['X-Cephla-Request-ID'])
        self.assertEqual(request['view'],'developer')

    def test_researcher_rejection_and_nested_secrets(self):
        self.app.add_url_rule('/researcher/api/test',view_func=lambda:(jsonify(ok=False,error='busy'),409),methods=['POST'])
        self.client.post('/researcher/api/test?api_key=hidden',json={'password':'secret','nested':{'token':'hidden','step':'Grip'}})
        request, reply = self.rows()[-2:]
        self.assertEqual(request['view'],'researcher')
        self.assertEqual(reply['status'],409)
        self.assertEqual(request['body']['password'],'[REDACTED]')
        self.assertEqual(request['body']['nested']['token'],'[REDACTED]')
        self.assertEqual(request['query']['api_key'],'[REDACTED]')
        self.assertNotIn('hidden',json.dumps(self.rows()))

    def test_streaming_response_is_not_consumed(self):
        emitted = []
        def frames():
            for i in range(2):
                emitted.append(i)
                yield b'image'
        self.app.add_url_rule('/video',view_func=lambda:Response(frames(),mimetype='multipart/x-mixed-replace'))
        response = self.client.get('/video',buffered=False)
        self.assertLessEqual(len(emitted),1)
        self.assertEqual(self.rows()[-1]['body_omitted'],'binary, static, or streamed content')
        response.close()

    def test_rotation_retains_all_parts(self):
        self.audit.max_bytes = 200
        for n in range(10):
            self.audit.event('test',sample=n)
        self.assertEqual([r['sample'] for r in self.rows() if r['event']=='test'],list(range(10)))
        self.assertGreater(len(list(Path(self.tmp.name).rglob('*.jsonl'))),1)

    def test_export_is_valid_json_and_keeps_recording_independent(self):
        self.audit.max_bytes = 200
        for i in range(3):
            self.audit.event('sample',value=i)
        response = self.client.get('/audit/export')
        exported = response.json
        self.assertEqual([r['value'] for r in exported['events'] if r['event']=='sample'],[0,1,2])
        self.assertFalse(exported['replay_approved'])
        self.assertTrue(any(r.get('path')=='/audit/export' and r['event']=='http_response' for r in self.rows()))

    def test_io_failure_does_not_prevent_stop_response(self):
        blocker = Path(self.tmp.name)/'file'
        blocker.write_text('not a directory')
        self.audit.root = blocker
        self.app.add_url_rule('/stop',view_func=lambda:jsonify(ok=True),methods=['POST'])
        response = self.client.post('/stop',json={})
        self.assertTrue(response.json['ok'])
        self.assertEqual(response.headers['X-Cephla-Audit'],'error')
        self.assertFalse(self.audit.status()['ok'])

    def test_background_result_keeps_origin_after_request_ends(self):
        runner = Runner(self.audit.event,self.audit.context)
        def sequence(run):
            run.say('arrived')
            return dict(ok=True)
        self.app.add_url_rule('/researcher/api/start',view_func=lambda:jsonify(runner.start('test',sequence)),methods=['POST'])
        response = self.client.post('/researcher/api/start',json={})
        runner._thread.join(2)
        finish = next(r for r in self.rows() if r['event']=='sequence_finished')
        self.assertEqual(finish['sequence_origin']['request_id'],response.headers['X-Cephla-Request-ID'])
        self.assertTrue(finish['result']['ok'])
        self.assertTrue(any(r['event']=='sequence_progress' for r in self.rows()))

    def test_external_axes_logged_without_extra_controller_queries(self):
        service = RobotService.__new__(RobotService)
        calls = []
        def joints():
            calls.append('joints')
            return dict(joints={'J1':30},external={'E1':.2})
        service.robot = SimpleNamespace(connected=True,endpoint='fake',
            get_sys_state=lambda:{'state':'idle'},get_ctrl_mode=lambda:{'mode':'auto'},
            get_enable_status=lambda:False,get_prog_state=lambda:{'state':'stopped'},
            get_lua_app_status=lambda:True,get_robot_errors=lambda:[],get_joint_info=joints)
        service.pose_mm = lambda:dict(X=1,Y=2,Z=3,Rz=4)
        service.audit_sink = self.audit.event
        self.assertEqual(service.status()['external_axes']['E1'],.2)
        self.assertEqual(calls,['joints'])
        self.assertEqual(self.rows()[-1]['robot']['external_axes']['E1'],.2)

    def test_exception_and_failure_response_are_recorded(self):
        def fail():
            raise RuntimeError('test failure')
        self.app.add_url_rule('/fail',view_func=fail)
        self.assertEqual(self.client.get('/fail').status_code,500)
        self.assertTrue(any(r['event']=='request_exception' for r in self.rows()))
        self.assertTrue(any(r.get('status')==500 for r in self.rows()))


if __name__ == '__main__':
    unittest.main()
