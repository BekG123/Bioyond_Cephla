"""Pickup transport handoff and reservation checks; no controller connection."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pickup_home import PickupHome
from researcher_teaching import TeachingError
from sequences import Runner
from test_staged_lift_trial import Service


class PickupHomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.service=Service()
        self.runner=Runner()
        self.token=object()
        self.runner.reserve(self.token,threading.Event());self.runner.claim(self.token)
        self.cfg=json.loads((Path(__file__).resolve().parents[1]/'robot_params.json').read_bytes())
        self.home=SimpleNamespace(get_service=lambda:self.service,get_runner=lambda:self.runner,
                                  params=lambda:self.cfg,require_home_queue=lambda support:None)
        self.connection=Mock(home=self.home)
        def propose():
            return dict(start=self.service.pose_mm(),joints=self.service.joints(),e1=self.service.e1,
                cfg=deepcopy(self.cfg),envelope=deepcopy(self.service.envelope),
                preserve_gripper=True,home=dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88),
                target_id='home',points_sha256='points')
        self.connection.propose.side_effect=propose
        self.transport=PickupHome(self.connection,Path(self.tmp.name)/'lifts')
        self.transport.configuration_ready=lambda:None
        self.grip=Path(self.tmp.name)/'grip.json'
        self.grip.write_text(json.dumps(dict(ok=True,target_e1_mm=3.7,at=time.time(),
                                              pose_mm=self.service.pose_mm())))
        self.grip_result=dict(ok=True,target_e1_mm=3.7,executor='staged_reference_position',
                              record=str(self.grip))
        self.calls=[]
        self.fail=False
        test=self
        class Queue:
            def __init__(self,service):self.service=service
            def capability(self):return dict(available=True,max_speed_mm_s=137)
            def execute(self,run,start,joints,points,cfg,speed,progress,**kwargs):
                test.calls.append((deepcopy(points),speed))
                if test.fail:return dict(ok=False)
                self.service.service.pose=dict(points[-1])
                progress('motion',100,100)
                return dict(ok=True)
        active=patch('pickup_home.LuaTrajectory',Queue)
        active.start();self.addCleanup(active.stop)

    def lift(self):
        self.transport.start_lift(self.grip_result)
        self.runner._thread.join(3)
        self.assertFalse(self.runner.active)
        return self.runner.result

    def test_exact_five_mm_slow_lift_then_existing_home_connection(self):
        result=self.lift()
        self.assertTrue(result['ok'])
        self.assertEqual(self.calls, [([dict(X=312.58,Y=-66.2,Z=78.72,Rz=89.87)],5)])
        self.connection.start.return_value=({'ok':True},'home-attempt.json')
        self.transport.start_home(result)
        plan=self.connection.start.call_args.args[0]
        self.assertEqual(plan['start']['Z'],78.72)
        self.assertTrue(plan['preserve_gripper'])
        self.assertEqual(plan['e1'],3.7)
        self.assertEqual(len(self.calls),1)  # No extra 25 mm stage.
        self.transport.finish_home({'state':'done','result':{'ok':True}})
        self.connection.finish.assert_called_once()

    def test_failed_lift_blocks_home(self):
        self.fail=True
        result=self.lift()
        self.assertFalse(result['ok'])
        with self.assertRaises(TeachingError):self.transport.start_home(result)
        self.connection.start.assert_not_called()

    def test_gripper_change_after_lift_blocks_home(self):
        result=self.lift();self.service.e1=4
        with self.assertRaises(TeachingError):self.transport.start_home(result)
        self.connection.start.assert_not_called()

    def test_home_settings_change_after_lift_blocks_home(self):
        result=self.lift();self.cfg['j4_pref_abs_deg']-=1
        with self.assertRaises(TeachingError):self.transport.start_home(result)
        self.connection.start.assert_not_called()

    def test_external_thread_cannot_own_reserved_workflow(self):
        observations=[]
        thread=threading.Thread(target=lambda:observations.append(self.runner.owns_reservation))
        thread.start();thread.join()
        self.assertEqual(observations,[False])
        self.assertTrue(self.runner.owns_reservation)
        self.runner.request_stop()
        self.assertFalse(self.runner.owns_reservation)

    def test_failed_grip_and_unreserved_lift_are_refused(self):
        with self.assertRaises(TeachingError):self.transport.start_lift({'ok':False})
        self.runner.release(self.token)
        with self.assertRaises(TeachingError):self.transport.start_lift(self.grip_result)
        self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()
