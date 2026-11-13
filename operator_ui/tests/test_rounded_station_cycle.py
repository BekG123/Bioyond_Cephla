import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import cellvis24_workflow as w
from cellvis24_recorded_hamilton_route import reference
from test_cellvis24_workflow import WorkflowTests as Fixture
from autonomy import TransferError


class RoundedStationTests(unittest.TestCase):
    def test_full_handling_uses_new_hamilton_both_ways_and_preserves_squid(self):
        h=Fixture('test_grip_or_holder_mismatch_prevents_dispatch');h.setUp();self.addCleanup(h.doCleanups)
        def queue(run,start,joints,points,cfg,speed,progress,**flags):
            step=dict(kind='queue',points=points,flags={k:v for k,v in flags.items() if k!='reviewed'})
            h.state.update(w.validate_steps([step],dict(pose_mm=start,joints=joints),cfg,h.g['envelope']))
            h.moves.append((deepcopy(points),speed,flags,h.e1));return dict(ok=True)
        h.lua.return_value.execute.side_effect=queue
        with patch('hamilton_transit_blend.require_capability',return_value={'blended_transit_capability':220114}),patch('hamilton_transit_blend.BlendedTransitTrajectory',w.LuaTrajectory):
            p=w.plan(h.service,h.g['cfg'],['hamilton','squid'],1,h.source,recorded_hamilton_variant='opposite3')
            result=w.execute(h.run,h.service,h.g['cfg'],p)
        self.assertEqual(result['completed_cycles'],1)
        hamilton=[x for x in p['steps'] if x['station']=='hamilton' and x['label'].startswith('Travel ')]
        self.assertEqual(len(hamilton),4)
        for x in hamilton:
            direction=x['label'].split()[-1];r=reference('opposite3')['routes'][direction]
            self.assertEqual(x['points'],r['points']);self.assertEqual(x['flags']['segment_speeds'],r['segment_speeds'])
            self.assertTrue(x['flags']['transit_blend'])
        squid=[x for x in p['steps'] if x['station']=='squid' and x['label'].startswith('Travel ')]
        self.assertEqual(len(squid),4)
        self.assertTrue(all('transit_blend' not in x['flags'] for x in squid))
        self.assertIn((7,5),h.grips);self.assertIn((25,5),h.grips);self.assertIn((3.9,5),h.grips)
        self.assertEqual(h.e1,28);self.assertEqual(h.state['pose_mm'],h.g['clearance'])
        self.assertEqual(h.angle,1.77);h.service.program.assert_not_called()
        self.assertEqual(json.loads(Path(result['record']).read_bytes())['payload'],'empty')

    def test_conflicting_or_irrelevant_route_selection_rejected(self):
        with self.assertRaises(TransferError):w.compile_steps(['squid'],1,recorded_hamilton_variant='opposite3')
        with self.assertRaises(TransferError):w.compile_steps(['hamilton'],1,direct_hamilton=True,recorded_hamilton_variant='opposite3')


if __name__=='__main__':unittest.main()
