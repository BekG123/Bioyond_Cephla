"""Offline pinned Cellvis route and unchanged 48-well routing checks."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from autonomy import TransferError
import cellvis24_hamilton_route as cellvis
from hamilton_short_side_trial import validate_shape, validate_route
from short_side_hover_transfer import validate_speeds
from trajectory_queue import prepare_points


class CellvisRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.plan=cellvis.reference()

    def test_forward_and_reverse_preserve_ik_limits_and_winding(self):
        p=self.plan;env={k:(p['global_envelope'][k]['min'],p['global_envelope'][k]['max']) for k in ('X','Y','Z')}
        for direction in ('forward','reverse'):
            r=p['routes'][direction];name='cellvis24_hamilton_'+direction
            q=validate_route(r['start'],r['points'],r['start_joints'],p['config'],env,name)
            self.assertLess(abs(q['J4']),215)
            quantized,_=prepare_points(r['start'],r['start_joints'],r['points'],p['config'],reviewed=True,hamilton_short_side=name)
            self.assertEqual(quantized,r['points'])
            validate_speeds(r['start'],r['points'],name,r['segment_speeds'])

    def test_arbitrary_endpoint_or_fast_seating_rejected(self):
        r=self.plan['routes']['forward'];name=cellvis.PROFILES[0]
        points=deepcopy(r['points']);points[-1]['Z']-=1
        with self.assertRaises(TransferError):validate_shape(r['start'],points,name)
        with self.assertRaises(TransferError):validate_speeds(r['start'],r['points'],name,[137]*5)

    def test_changed_global_limits_rejected(self):
        p=self.plan;r=p['routes']['forward']
        env={k:(p['global_envelope'][k]['min'],p['global_envelope'][k]['max']) for k in ('X','Y','Z')};env['Z']=(0,400)
        with self.assertRaises(TransferError):validate_route(r['start'],r['points'],r['start_joints'],p['config'],env,cellvis.PROFILES[0])

    def test_plan_receipt_cannot_be_edited_in_place(self):
        with patch.object(cellvis.PLAN.__class__,'read_bytes',return_value=b'{}'):
            with self.assertRaises(TransferError):cellvis.reference()

    def test_real_lua_protocol_with_simulated_vendor_calls(self):
        from test_short_side_hover_transfer import HoverTransferTests
        from trajectory_queue import LuaTrajectory
        for direction in ('forward','reverse'):
            fixture=HoverTransferTests();fixture.setup_route()
            r=self.plan['routes'][direction]
            fixture.s.pose=deepcopy(r['start']);fixture.s.q=deepcopy(r['start_joints'])
            result=LuaTrajectory(fixture.s).execute(fixture.run,r['start'],r['start_joints'],r['points'],
                self.plan['config'],137,lambda *args:None,reviewed=True,
                hamilton_short_side='cellvis24_hamilton_'+direction,segment_speeds=r['segment_speeds'])
            self.assertTrue(result['ok']);self.assertEqual(result['completion_barriers'],1)


if __name__=='__main__':unittest.main()
