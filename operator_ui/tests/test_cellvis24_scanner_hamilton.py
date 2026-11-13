import json
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import cellvis24_scanner_return as c
import cellvis24_workflow as w
import test_scanner_plate_workflow as fixtures
import test_cellvis24_workflow as workflow_fixtures
from test_trajectory_queue import PARAMS
from autonomy import TransferError,ik,wrap
from trajectory_queue import LuaTrajectory


class ScannerReturnTests(unittest.TestCase):
    def setUp(self):
        fixtures.LoadedScannerTests.setUp(self)
        old=dict(self.s.pose);q=self.s.q;start=dict(c.TARGET)
        q2,q3=ik(start['X'],start['Y'],(q['J2'],q['J3']),PARAMS)
        self.s.q=dict(J1=q['J1']+start['Z']-old['Z'],J2=q2,J3=q3,
                      J4=q['J4']+wrap(start['Rz']-old['Rz'])-(q2+q3-q['J2']-q['J3']))
        self.s.pose=start
        seat=dict(X=312.8,Y=-65.98,Z=75.72,Rz=90.12);proof=dict(seat,Z=80.72)
        self.g=dict(id='a'*32,start=start,points=[dict(start,Z=300),dict(proof,Z=300),proof],cfg=PARAMS,
            seat=seat,clearance=dict(seat,Z=105.72),station_clearance=dict(X=312.5,Y=-66.3,Z=105.72,Rz=89.84),sources={})
        for p in (patch.object(c,'geometry',return_value=self.g),patch.object(c,'RUNS',self.folder),
                  patch.object(c,'native',side_effect=lambda service:dict(moving=False,external_axes=dict(E1=self.s.e1,E2=1.77)))):
            p.start();self.addCleanup(p.stop)

    def test_reverse_single_fast_queue_then_slow_seating_no_release(self):
        approved=json.loads(json.dumps(c.plan(self.s,PARAMS,self.g['id'],'return_home')))
        result=c.execute(self.run,self.s,PARAMS,approved)
        self.assertEqual(result['status'],'at_HOME_held');self.assertEqual(self.s.grips,[])
        self.assertEqual([v[1] for v in self.s.robot.calls],[137,137,137,5])
        self.assertEqual(self.s.robot.barriers,2);self.assertEqual(self.s.envelope,c.ORIGINAL)
        self.assertEqual(self.s.e1,3.9)
        with self.assertRaises(TransferError):c.plan(self.s,PARAMS,self.g['id'],'return_home')

    def test_release_only_after_completed_seating_then_empty_clearance(self):
        result=c.execute(self.run,self.s,PARAMS,c.plan(self.s,PARAMS,self.g['id'],'return_home'))
        self.s.pose_mm=lambda:self.s.pose.copy()
        def grip(target,speed):self.s.e1=target;self.s.grips.append((target,speed));return dict(ok=True)
        self.s.move_gripper=grip
        result=c.execute(self.run,self.s,PARAMS,c.plan(self.s,PARAMS,self.g['id'],'release_home'))
        self.assertEqual(result['status'],'completed');self.assertEqual(result['payload'],'empty')
        self.assertEqual(self.s.grips,[(28,5)])
        for key in c.KEYS:self.assertAlmostEqual(self.s.pose[key],self.g['station_clearance'][key],places=4)

    def test_wrong_grip_or_changed_route_blocks_before_dispatch(self):
        self.s.e1=4.2
        with self.assertRaises(TransferError):c.plan(self.s,PARAMS,self.g['id'],'return_home')
        self.s.e1=3.9;p=c.plan(self.s,PARAMS,self.g['id'],'return_home');p=deepcopy(p);p['binding']['points'][0]['Z']=290
        with self.assertRaises(TransferError):c.execute(self.run,self.s,PARAMS,p)
        self.assertFalse(self.s.robot.calls)

    def test_unmonitored_return_cannot_bypass_queue_checks(self):
        self.s.envelope=dict(c.TRIAL)
        with self.assertRaises(TransferError):LuaTrajectory(self.s).execute(self.run,self.s.pose,self.s.q,self.g['points'],PARAMS,137,
            lambda *a:None,reviewed=True,scanner_loaded='cellvis_return')
        self.assertFalse(self.s.robot.calls)

    def test_contact_deflection_allows_seating_release_and_clearance(self):
        def native(service):
            return dict(moving=False,external_axes=dict(E1=self.s.e1,E2=1.9 if self.s.pose['Z']<80 else 1.77))
        with patch.object(c,'native',side_effect=native):
            c.execute(self.run,self.s,PARAMS,c.plan(self.s,PARAMS,self.g['id'],'return_home'))
            self.s.pose_mm=lambda:self.s.pose.copy()
            def grip(target,speed):self.s.e1=target;return dict(ok=True)
            self.s.move_gripper=grip
            result=c.execute(self.run,self.s,PARAMS,c.plan(self.s,PARAMS,self.g['id'],'release_home'))
        self.assertEqual(result['status'],'completed')
        self.assertEqual(self.s.e1,28)

    def test_excessive_seating_deflection_stops_and_records_bad_reading(self):
        # Final seating only: travel retains the ordinary setup range.
        def native(service):
            return dict(moving=False,external_axes=dict(E1=self.s.e1,E2=2.4 if self.s.pose['Z']<80 else 1.77))
        with patch.object(c,'native',side_effect=native):
            with self.assertRaises(TransferError):
                c.execute(self.run,self.s,PARAMS,c.plan(self.s,PARAMS,self.g['id'],'return_home'))
        record=json.loads((self.folder/self.g['id']/'return_home.json').read_text())
        self.assertEqual(record['status'],'stopped_or_uncertain')
        self.assertEqual(record['samples'][-1]['axes']['E2'],2.4)
        self.assertEqual(self.s.grips,[])

    def test_reseating_review_is_read_only_and_binds_failed_receipt(self):
        failed=self.folder/self.g['id']/'return_home.json';failed.parent.mkdir()
        failed.write_text(json.dumps(dict(status='stopped_or_uncertain',error='Original HOME holder angle changed.',plan=dict(binding=self.g))))
        recovery_root=self.folder/'recoveries';recovery=recovery_root/'one'/'run.json';recovery.parent.mkdir(parents=True)
        self.s.pose=dict(self.g['station_clearance']);self.s.e1=28
        recovery.write_text(json.dumps(dict(status='empty_clearance_plate_absent',plate_absent=True,prior_failure=str(failed),
            final=dict(pose_mm=self.s.pose),final_native=dict(external_axes=dict(E1=28)),finished_at=time.time())))
        with patch.object(c,'RECOVERIES',recovery_root):
            with self.assertRaises(TransferError):c.review_recovered_home(self.s,PARAMS,recovery,False)
            result=c.review_recovered_home(self.s,PARAMS,recovery,True)
            path=Path(result['record']);d=json.loads(path.read_bytes())
            c.validate_reseated_source(path,d)
            failed.write_text(failed.read_text()+' ')
            with self.assertRaises(TransferError):c.validate_reseated_source(path,d)
        self.assertFalse(self.s.robot.calls)
        self.assertFalse(result['motion_started'])


class HeldHamiltonTests(unittest.TestCase):
    def test_held_roundtrip_retains_grip_at_hamilton_and_reuses_exact_rack_routes(self):
        helper=workflow_fixtures.WorkflowTests();helper.setUp();self.addCleanup(helper.doCleanups)
        p=w.plan(helper.service,helper.g['cfg'],['hamilton'],1,helper.source,held_hamilton_roundtrip=True)
        r=w.execute(helper.run,helper.service,helper.g['cfg'],p)
        travel=[m for m in helper.moves if m[2].get('hamilton_short_side')]
        self.assertEqual(len(travel),2);self.assertTrue(all(m[3]==25 for m in travel))
        self.assertEqual(helper.grips,[(26,10),(25,5),(28,5)])
        self.assertEqual(r['completed_cycles'],1);self.assertEqual(helper.e1,28)
        helper.service.program.assert_not_called()

    def test_mode_does_not_accept_squid_or_new_calibration(self):
        with self.assertRaises(TransferError):w.compile_steps(['squid'],1,held_hamilton_roundtrip=True)
        with self.assertRaises(TransferError):w.compile_steps(['hamilton'],1,True,True)


if __name__=='__main__':unittest.main()
