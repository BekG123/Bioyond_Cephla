import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import hotel_slot2_trial as h

class Slot2TrialTests(unittest.TestCase):
    def setUp(self):
        self.g=h.geometry();r=self.g['route']
        self.s=dict(pose_mm=deepcopy(r['start']),joints=deepcopy(self.g['start_joints']))
        self.n=dict(external_axes={'E1':3.9,'E2':1.77})
        self.service=SimpleNamespace(envelope=self.g['envelope'],program=Mock(return_value={'ok':True}),move_gripper=Mock())
        self.run=SimpleNamespace(stopped=lambda:False,say=Mock())
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        for p in (patch.object(h,'OUTPUT',Path(self.tmp.name)),patch.object(h,'state',side_effect=lambda *a,**k:(deepcopy(self.s),deepcopy(self.n)))):
            p.start();self.addCleanup(p.stop)

    def test_arrival_stops_held_without_release(self):
        p=h.preview(self.service,self.g['cfg'])
        def queue(run,start,joints,points,cfg,speed,monitor,**kw):
            self.assertEqual(kw['segment_speeds'],[137]*6+[20])
            self.assertEqual(kw['hotel_route'],h.PHASE)
            self.s.update(pose_mm=deepcopy(points[-1]),joints=deepcopy(self.g['route']['expected']));monitor()
            return {'ok':True}
        with patch('trajectory_queue.LuaTrajectory.execute',side_effect=queue):
            result=h.execute(self.run,self.service,self.g['cfg'],p)
        self.assertFalse(result['release_sent']);self.assertEqual(result['payload'],'held')
        self.service.move_gripper.assert_not_called();self.service.program.assert_not_called()

    def test_failed_queue_stops_without_retry_or_release(self):
        p=h.preview(self.service,self.g['cfg'])
        with patch('trajectory_queue.LuaTrajectory.execute',return_value={'ok':False}) as queue:
            with self.assertRaisesRegex(Exception,'no retry'):h.execute(self.run,self.service,self.g['cfg'],p)
        self.assertEqual(queue.call_count,1);self.service.program.assert_called_once_with('stop')
        self.service.move_gripper.assert_not_called()

    def test_changed_route_cannot_use_corridor_exception(self):
        p=h.preview(self.service,self.g['cfg']);owner=h.TrialService(self.service,p);r=self.g['route']
        changed=deepcopy(r['points']);changed[-2]['X']-=10
        with self.assertRaisesRegex(Exception,'route or speed changed'):
            h.prepare_for_service(owner,h.PHASE,r['start'],p['joints'],changed,self.g['cfg'],self.g['envelope'],r['speeds'])

if __name__=='__main__':unittest.main()
