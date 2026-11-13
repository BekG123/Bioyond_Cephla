import unittest
import json
from unittest.mock import patch
from copy import deepcopy
from autonomy import TransferError
from cellvis24_taught_three_route import reference, PROFILES, validate_shape, validate_speeds
from cellvis24_workflow import compile_steps
from trajectory_queue import LuaTrajectory
from test_cellvis_direct_wrist import DirectWristTests


class TaughtThreeTests(unittest.TestCase):
    def test_actual_lua_queue_both_directions(self):
        p = reference()
        for direction, profile in zip(('forward', 'reverse'), PROFILES):
            h, s, _, _ = DirectWristTests().setup_route()
            r = p['routes'][direction]
            s.pose = deepcopy(r['start']); s.q = deepcopy(r['start_joints'])
            result = LuaTrajectory(s).execute(h.run, s.pose, s.q, r['points'], p['config'], 137,
                lambda *a: None, reviewed=True, hamilton_short_side=profile,
                segment_speeds=r['segment_speeds'])
            self.assertTrue(result['ok'])
            self.assertEqual(s.robot.barriers, 1)
            self.assertEqual(len(s.robot.calls), 3)
            self.assertEqual([c[1] for c in s.robot.calls], r['segment_speeds'])
            self.assertFalse(s.grips)

    def test_delivery_stops_held_and_old_default_unchanged(self):
        steps = compile_steps(['hamilton'], 1, taught_hamilton_delivery=True)
        self.assertEqual(steps[-1]['label'], 'Travel forward')
        self.assertEqual(steps[-1]['flags']['hamilton_short_side'], PROFILES[0])
        self.assertEqual([s['target'] for s in steps if s['kind']=='jaws'], [26,25])
        self.assertFalse(any(s['label']=='Travel reverse' for s in steps))
        old = compile_steps(['hamilton'],1,held_hamilton_roundtrip=True)
        self.assertEqual(next(s for s in old if s['label']=='Travel forward')['flags']['hamilton_short_side'], 'cellvis24_rack_forward')
        for kw in (dict(cycles=2), dict(cycles=1,held_hamilton_roundtrip=True), dict(cycles=1,direct_hamilton=True)):
            with self.assertRaises(TransferError):
                compile_steps(['hamilton'], taught_hamilton_delivery=True, **kw)

    def test_tampered_route_or_fast_contact_rejected(self):
        r=reference()['routes']['forward']; points=deepcopy(r['points'])
        points[0]['X'] += 1
        with self.assertRaises(TransferError):validate_shape(r['start'],points,PROFILES[0])
        with self.assertRaises(TransferError):validate_speeds(r['start'],r['points'],PROFILES[0],[137]*3)

    def test_workflow_receipt_marks_held_payload_no_release(self):
        from test_cellvis24_workflow import WorkflowTests
        import cellvis24_workflow as w
        from cellvis24_taught_three_route import validate_route
        helper=WorkflowTests();helper.setUp()
        try:
            with patch('cellvis24_rack_route.validate_route',side_effect=validate_route):
                plan=w.plan(helper.service,helper.g['cfg'],['hamilton'],1,helper.source,taught_hamilton_delivery=True)
                result=w.execute(helper.run,helper.service,helper.g['cfg'],plan)
            from pathlib import Path
            record=json.loads(Path(result['record']).read_text())
            self.assertEqual(record['payload'],'held')
            self.assertEqual(helper.e1,25)
            self.assertEqual(helper.state['pose_mm'],reference()['routes']['forward']['points'][-1])
        finally:helper.doCleanups()


if __name__=='__main__':unittest.main()
