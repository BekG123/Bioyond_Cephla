"""Offline candidate planning using the recorded taught pose; no HTTP or motion."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import prepare_squid_destination as planner
from autonomy import TransferError


class DestinationTests(unittest.TestCase):
    def setUp(self):
        source=planner.ROOT/'operator_ui/reports/squid_48well_approach/destination_20261101T071149Z.json'
        self.record=json.loads(source.read_bytes())
        self.state=deepcopy(self.record['source_state'])
        self.cfg=self.record['cfg']

    def test_preserves_transit_and_handling_reaches_taught_winding(self):
        candidate=planner.build(self.state,self.cfg)
        old=planner.reference()[1]
        path=candidate['routes']['forward']
        self.assertEqual(path[:3],old[:3])
        self.assertEqual(path[-1],{k:self.state['robot']['pose_mm'][k] for k in planner.KEYS})
        self.assertEqual(candidate['handling'],planner.settings())
        self.assertEqual(candidate['lift_mm'],5)
        self.assertFalse(candidate['deployed'])
        self.assertFalse(candidate['collision_clearance_verified'])
        self.assertLess(max(abs(v) for v in candidate['validation']['taught_joint_difference'].values()),.01)

    def test_wrong_taught_winding_rejected(self):
        self.state['robot']['joints']['J4']+=360
        with self.assertRaisesRegex(TransferError,'winding'):planner.build(self.state,self.cfg)

    def test_changed_limits_rejected(self):
        with self.assertRaisesRegex(TransferError,'settings'):
            planner.build(self.state,dict(self.cfg,j2_margin_deg=0))

    def test_active_or_disconnected_capture_rejected(self):
        self.state['sequence']['active']=True
        with self.assertRaises(TransferError):planner.build(self.state,self.cfg)
        self.state['sequence']['active']=False;self.state['robot']['connected']=False
        with self.assertRaises(TransferError):planner.build(self.state,self.cfg)

    def test_endpoint_without_lift_clearance_rejected(self):
        self.state['robot']['pose_mm']['Z']=290
        with self.assertRaisesRegex(TransferError,'clearance'):planner.build(self.state,self.cfg)


if __name__=='__main__':unittest.main()
