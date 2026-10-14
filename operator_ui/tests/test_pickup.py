"""Offline pickup verification tests: fake robot, fake camera, no connections."""
import copy
import sys
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pickup import PickupVerification
from autonomy import TransferError
from test_transfer import FakeService, PARAMS, CAM
from sequences import Runner, seq_grip


class PickupTests(unittest.TestCase):
    def setUp(self):
        self.v=PickupVerification();self.s=FakeService();self.r=Runner();self.r.state='running'
        self.s.gripper_status=lambda:{'ok':True,'e1_position':23.4,'e1_torque':-187}
        self.vision=SimpleNamespace(W=SimpleNamespace(CAL={'marker_offsets':{'3':dict(dx_mm=2,dy_mm=1,rel_yaw_deg=0)}},CLAW_ARM=[191.6,5.43]),
            model_stamps=lambda:('v1','v1'),view_center_world=lambda *a:(340,20))
        self.vision.solve=lambda *a,**kw:dict(detected=True,id=3,H_mm=220,marker_world=[340,20,self.s.pose['Z']-220],marker_yaw_deg=0)
        self.body=dict(marker_id=3,plate_center_dz_mm=-7,operator_confirmed=True,cell_clear=True,plate_calibration_confirmed=True,lift_mm=5)
        self.evidence=dict(ok=True,gripped=True,confirmed_at=time.time(),stopped_at_command=23.)
        self.approve=True
        def say(msg,*args):
            if msg.startswith('Lift completed'):self.v.confirm(self.v.public()['token'],self.approve)
        self.r.say=say

    def execute(self):return self.v.run(self.r,self.s,CAM,self.vision,self.body,self.evidence,PARAMS)

    def test_success(self):
        result=self.execute();self.assertTrue(result['ok'],result)
        self.assertEqual(len(self.s.moves),1);self.assertEqual(self.s.grips,[])
        snap=result['snapshot'];self.assertAlmostEqual(snap['measured_lift_mm'],5)
        self.assertEqual(set(snap['joints']),{'J1','J2','J3','J4'})
        self.assertTrue(snap['e1']['confirmed']);self.assertEqual(snap['plate_relative_to_gripper']['z_mm'],-227)
        self.v.invalidate();self.assertFalse(self.v.public()['verified'])

    def test_no_approval_no_motion(self):
        self.body['operator_confirmed']=False;self.assertFalse(self.execute()['ok']);self.assertEqual(self.s.moves,[])

    def test_disabled_envelope_no_motion(self):
        self.s.envelope_enabled=False;self.assertFalse(self.execute()['ok']);self.assertEqual(self.s.moves,[])

    def test_weak_or_missing_grip(self):
        for report in [{'ok':True},{'ok':True,'e1_position':23,'e1_torque':-187},{'ok':True,'e1_position':23.4,'e1_torque':0},{'ok':True,'e1_position':float('nan'),'e1_torque':-187},{'ok':True,'recovered':True}]:
            self.s.gripper_status=lambda:report
            self.assertFalse(self.execute()['ok']);self.assertEqual(self.s.moves,[])

    def test_stale_grip(self):
        self.evidence['confirmed_at']-=121;self.assertFalse(self.execute()['ok']);self.assertEqual(self.s.moves,[])

    def test_marker_missing(self):
        self.vision.solve=lambda *a,**kw:{'detected':False}
        self.assertFalse(self.execute()['ok']);self.assertEqual(self.s.moves,[])

    def test_plate_not_lifted(self):
        self.vision.solve=lambda *a,**kw:dict(detected=True,id=3,H_mm=220,marker_world=[340,20,80],marker_yaw_deg=0)
        self.assertFalse(self.execute()['ok']);self.assertFalse(self.v.public()['verified'])

    def test_operator_rejects(self):
        self.approve=False;self.assertFalse(self.execute()['ok']);self.assertEqual(len(self.s.moves),1)

    def test_lift_failure_no_retry(self):
        self.s.motion_failure='recovered';self.assertFalse(self.execute()['ok']);self.assertEqual(len(self.s.moves),1)

    def test_wrong_confirmation_token(self):
        with self.assertRaises(TransferError):self.v.confirm('wrong',True)

    def test_snapshot_expires(self):
        self.assertTrue(self.execute()['ok'])
        with patch('pickup.time.time',return_value=time.time()+31):self.assertFalse(self.v.public()['verified'])

    def test_unconfirmed_grip_sequence_not_success(self):
        self.s.move_gripper=lambda v:{'ok':True,'gripper':{'e1_position':v,'e1_torque':-187,'position_error':0}}
        self.s.torque_report=lambda:{'ok':True,'telemetry_live':True,'joints':dict(J1=350,J2=1,J3=1,J4=1)}
        result=seq_grip(self.r,self.s,dict(start=28,floor=1))
        self.assertFalse(result['ok']);self.assertFalse(result['gripped'])

    def test_confirmation_route_during_owned_sequence(self):
        import app as application
        v=PickupVerification();v.state={'phase':'awaiting_visual','token':'test','verified':False}
        with patch.object(application,'pickup',v),patch.object(application,'runner',SimpleNamespace(active=True)):
            client=application.app.test_client()
            self.assertEqual(client.post('/jog',json={'axis':'Z','delta':1}).status_code,409)
            self.assertEqual(client.post('/pickup/confirm',json={'token':'wrong','confirmed':True}).status_code,400)
            self.assertTrue(client.post('/pickup/confirm',json={'token':'test','confirmed':False}).json['ok'])
            self.assertEqual(client.post('/pickup/confirm',json={'token':'test','confirmed':True}).status_code,400)

    def test_approval_route_refuses_missing_confirmation(self):
        import app as application
        with patch.object(application,'runner',SimpleNamespace(active=False)):
            response=application.app.test_client().post('/seq/verify_pickup',json={})
            self.assertEqual(response.status_code,400)

    def test_no_snapshot_after_stop_during_review(self):
        def say(msg,*args):
            if msg.startswith('Lift completed'):
                self.r.request_stop();self.v.confirm(self.v.public()['token'],True)
        self.r.say=say
        self.assertFalse(self.execute()['ok']);self.assertFalse(self.v.public()['verified'])


if __name__=='__main__':unittest.main()
