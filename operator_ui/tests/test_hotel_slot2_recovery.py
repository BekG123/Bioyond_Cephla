import unittest
from copy import deepcopy
from unittest.mock import patch
from pathlib import Path
from test_hotel_slot_trial import HotelTests
from autonomy import check_path
import hotel_slot2_recovery as h

class RecoveryTests(HotelTests):
    def setUp(self):
        super().setUp()
    def recovery_state(self):
        q=check_path(self.d['start'],h.ANCHOR,self.d['start_joints'],self.cfg,None)
        q['J1']=h.ANCHOR['Z']-self.d['start']['Z']+self.d['start_joints']['J1']
        self.s.update(pose_mm=deepcopy(h.ANCHOR),joints=q,program_state={'state':'stopped'})
    def test_pinned_monotonic_ingress_only(self):
        self.recovery_state();p=h.preview(self.svc,self.cfg);owner=h.RecoveryService(self.svc,p)
        points,q=h.prepare_for_service(owner,'slot2_recovery',p['start'],p['joints'],p['points'],self.cfg,self.d['envelope'],p['speeds'])
        self.assertEqual(points[0]['X'],205);self.assertEqual(p['speeds'],[5]*4)
        wrong=deepcopy(p['points']);wrong[0]['X']=180
        with self.assertRaises(Exception):h.prepare_for_service(owner,'slot2_recovery',p['start'],p['joints'],wrong,self.cfg,self.d['envelope'],p['speeds'])
        wrong=deepcopy(p['points']);wrong[1]['X']=190
        with self.assertRaises(Exception):h.checked(p['start'],wrong,p['joints'],self.cfg,self.d['envelope'],self.d['start_joints'])
        self.assertEqual(self.calls,[])
    def test_recovery_failure_stops_no_retry(self):
        self.recovery_state();p=h.preview(self.svc,self.cfg)
        with patch.object(h,'OUTPUT',Path(self.tmp.name)),patch.object(h,'native',lambda svc:dict(external_axes=self.axes)),patch('trajectory_queue.LuaTrajectory.execute',return_value={'ok':False,'error':'timeout'}) as queue:
            with self.assertRaisesRegex(Exception,'uncertain'):h.execute(self.run,self.svc,self.cfg,p)
        queue.assert_called_once();self.assertEqual(self.calls,['enable','start','stop'])

if __name__=='__main__':unittest.main()
