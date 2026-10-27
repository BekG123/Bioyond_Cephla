"""Fake model and local logs only; planning has no robot service or executor."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pickup_planner import PickupPlanner, TOOL
from researcher_teaching import TeachingError
from test_transfer import PARAMS, ENVELOPE
from flask import Flask
from researcher import register_researcher


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.credentials=SimpleNamespace(ready=lambda:True,model='test-haiku',key='secret-not-for-payload')
        self.routine=dict(id='saved',revision=7,reviewed=True,frame=dict(tool='T0',user='U0'),waypoints=[])
        for name,z,e1 in [('Home',300,28),('Calibrate',300,28),('Align',300,28),('Descend',100,28),('Grip',100,3),('Hamilton',100,3)]:
            self.routine['waypoints'].append(dict(station=name,captured_at='2026-10-16T17:00:00+00:00',
                source='robot_controller',pose_mm=dict(X=326.,Y=0.,Z=z,Rz=0.),
                joints=dict(J1=z,J2=60.,J3=60.,J4=-120.),gripper=dict(E1=e1)))
        self.samples=[]
        for i,(z,e1) in enumerate([(300,28),(200,28),(100,28),(100,10),(100,3),(105,3),(110,3)]):
            self.samples.append(dict(index=i,requested_at=f'2026-10-16T17:00:0{i}+00:00',valid=True,
                robot=dict(connected=True,errors=[],pose_mm=dict(X=326.,Y=0.,Z=z,Rz=0.),
                           joints=dict(J1=z,J2=60.,J3=60.,J4=-120.),external_axes=dict(E1=e1),
                           api_key='never include this raw field',control_mode=dict(mode='auto'),program_state=dict(state='running'))))
        self.path=self.root/'evidence.json'; self.write()
        self.teaching=Mock(); self.teaching.export.return_value=self.routine
        self.client=Mock(); self.record=Mock()
        self.planner=PickupPlanner(self.teaching,self.credentials,self.path,self.root/'out',lambda:PARAMS,
                                  lambda:(ENVELOPE,True),self.record,client=self.client)

    def write(self):
        self.path.write_text(json.dumps(dict(routine_id='saved',revision=7,samples=self.samples)))

    def answer(self, packet):
        return dict(stop_reason='tool_use',content=[dict(type='tool_use',name=TOOL['name'],id='proposal',input=dict(
            evidence_id=packet['evidence_id'],summary='Measured stages require review.',
            stages=[dict(action=name,from_sample=a,to_sample=b,explanation='Measured evidence')
                    for name,a,b in [('Descend',0,2),('Grip',2,4),('Pickup',4,6)]],review_needed=['Confirm grasp and path']))])

    def test_allowlisted_evidence_and_exact_closure_samples(self):
        packet=self.planner.evidence('saved')
        self.assertEqual([p['e1_mm'] for p in packet['samples']],[28,28,28,10,3,3,3])
        self.assertNotIn('api_key',json.dumps(packet))
        self.assertNotIn('secret',json.dumps(packet))
        self.assertEqual(packet['source_sample_count'],7)

    def test_source_revision_and_frame_must_match(self):
        self.routine['revision']=8
        with self.assertRaises(TeachingError):self.planner.evidence('saved')
        self.routine['revision']=7;self.routine['frame']['tool']='T1'
        with self.assertRaises(TeachingError):self.planner.evidence('saved')

    def test_model_cannot_invent_targets_or_call_motion(self):
        packet=self.planner.evidence('saved')
        for field,value in [('name','move_gripper'),('stop_reason','max_tokens')]:
            answer=self.answer(packet)
            if field=='name':answer['content'][0]['name']=value
            else:answer[field]=value
            with self.assertRaises(TeachingError):self.planner.validate(answer,packet)
        for key,value in [('from_sample',999),('from_sample',True),('x',300)]:
            answer=self.answer(packet);answer['content'][0]['input']['stages'][0][key]=value
            with self.assertRaises(TeachingError):self.planner.validate(answer,packet)

    def test_missing_stage_can_be_reported_without_invention(self):
        packet=self.planner.evidence('saved');answer=self.answer(packet)
        answer['content'][0]['input']['stages'][2].update(from_sample=None,to_sample=None)
        result=self.planner.validate(answer,packet)
        self.assertFalse(result['execution_ready'])
        self.assertEqual(result['hardware_commands_sent'],0)

    def test_faults_excluded_and_gaps_disclosed(self):
        self.samples[3]['robot']['errors']=[{'code':10}];self.write()
        packet=self.planner.evidence('saved')
        self.assertEqual(packet['excluded_sample_indices'],[3])
        self.assertEqual(packet['gaps_over_one_second'][0]['seconds'],2)
        answer=self.answer(packet);answer['content'][0]['input']['stages'][1]['from_sample']=3
        with self.assertRaises(TeachingError):self.planner.validate(answer,packet)

    def test_persisted_proposal_does_not_approve_reference(self):
        packet=self.planner.evidence('saved');self.client.complete.return_value=self.answer(packet)
        self.planner.run('test',packet)
        self.assertEqual(self.planner.public()['stage'],'review')
        result=json.loads((self.root/'out/test_proposal.json').read_text())
        self.assertFalse(result['execution_ready'])
        payload=self.client.complete.call_args.args[0]
        self.assertEqual([t['name'] for t in payload['tools']],['propose_pickup_plan'])
        self.assertEqual(self.client.complete.call_count,1)
        self.assertNotIn('secret',json.dumps(payload))
        self.assertEqual([c[0] for c in self.teaching.method_calls],['export'])

    def test_missing_key_and_duplicate_start(self):
        self.credentials.ready=lambda:False
        with self.assertRaises(TeachingError):self.planner.start('saved')
        self.client.complete.assert_not_called()
        self.credentials.ready=lambda:True
        with patch('pickup_planner.threading.Thread') as thread:
            self.planner.start('saved')
            with self.assertRaises(TeachingError):self.planner.start('saved')
            self.assertEqual(thread.call_count,1)

    def test_researcher_route_forwards_saved_id_only(self):
        app=Flask(__name__);planner=Mock();planner.start.return_value=dict(ok=True)
        register_researcher(app,Mock(),pickup_planner=planner)
        response=app.test_client().post('/researcher/api/routines/saved/pickup-plan',json={'move':'ignored'})
        self.assertEqual(response.status_code,200)
        planner.start.assert_called_once_with('saved')

    def test_feedback_resolves_stored_coordinates_and_refreshes_without_restart(self):
        self.planner.output_dir.mkdir()
        feedback=dict(source_id='saved',revision=7,sample_indices=[2,4,6],notes=['Use the measured closure.'],
                      pickup_location=dict(X=999999))
        path=self.planner.output_dir/'feedback.json'
        path.write_text(json.dumps(feedback))
        packet=self.planner.evidence('saved')
        self.assertEqual(packet['measured_corrections']['pickup_location']['pose_mm']['X'],326)
        self.assertNotIn('999999',json.dumps(packet))
        feedback['notes']=['Distinguish the first lift.'];path.write_text(json.dumps(feedback))
        next_packet=self.planner.evidence('saved')
        self.assertNotEqual(packet['evidence_id'],next_packet['evidence_id'])
        self.assertEqual(next_packet['measured_corrections']['notes'],feedback['notes'])

    def test_stationary_pickup_and_opening_grip_are_rejected(self):
        packet=self.planner.evidence('saved')
        for stage,first,last in [(1,3,2),(2,4,4)]:
            answer=self.answer(packet)
            answer['content'][0]['input']['stages'][stage].update(from_sample=first,to_sample=last)
            with self.assertRaises(TeachingError):self.planner.validate(answer,packet)
        answer=self.answer(packet)
        packet['samples'][2]['e1_mm']=0
        with self.assertRaisesRegex(TeachingError,'closure'):self.planner.validate(answer,packet)

    def test_invalid_feedback_sample_is_not_sent(self):
        self.planner.output_dir.mkdir()
        (self.planner.output_dir/'feedback.json').write_text(json.dumps(dict(source_id='saved',revision=7,sample_indices=[999],notes=[])))
        with self.assertRaises(TeachingError):self.planner.evidence('saved')
        self.client.complete.assert_not_called()


if __name__=='__main__':unittest.main()
