import json
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import cellvis24_hamilton_continuation as c
import cellvis24_workflow as w
from test_cellvis24_workflow import WorkflowTests
from autonomy import TransferError


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.h=WorkflowTests('test_grip_or_holder_mismatch_prevents_dispatch');self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        h=self.h;p=c.reference('opposite3');r=p['routes']['reverse']
        h.state.update(pose_mm=deepcopy(r['start']),joints=deepcopy(r['start_joints']))
        h.e1=25;h.angle=90.71661229181757
        for patcher in (patch.object(c,'preflight',side_effect=lambda s:deepcopy(h.state)),
                        patch.object(c,'native',side_effect=lambda s:dict(moving=False,external_axes={'E1':h.e1,'E2':h.angle})),
                        patch.object(c,'LuaTrajectory',w.LuaTrajectory),
                        patch('hamilton_transit_blend.require_capability',return_value={'blended_transit_capability':220114}),
                        patch('hamilton_transit_blend.BlendedTransitTrajectory',w.LuaTrajectory)):
            patcher.start();self.addCleanup(patcher.stop)
        self.source=w.RUNS/('a'*32)/'run.json';self.source.parent.mkdir(parents=True)
        forward=w.compile_steps(['hamilton'],1,recorded_hamilton_delivery=True,recorded_hamilton_variant='opposite3')
        self.source.write_text(json.dumps(dict(status='completed',payload='held',finished_at=time.time(),final=h.state,
            plan=dict(recorded_hamilton_delivery=True,recorded_hamilton_variant='opposite3',steps=forward))))
        def queue(run,start,joints,points,cfg,speed,progress,**flags):
            step=dict(kind='queue',points=points,flags={k:v for k,v in flags.items() if k!='reviewed'})
            h.state.update(w.validate_steps([step],dict(pose_mm=start,joints=joints),cfg,h.g['envelope']))
            h.moves.append((points,speed,flags,h.e1));progress('motion',1,1);return dict(ok=True)
        h.lua.return_value.execute.side_effect=queue

    def test_reverse_home_release_then_squid_only_delivery(self):
        h=self.h
        p=c.plan(h.service,h.g['cfg'],self.source,'return_home')
        result=c.execute(h.run,h.service,h.g['cfg'],p)
        d=json.loads(Path(result['record']).read_bytes())
        self.assertEqual(d['payload'],'empty');self.assertEqual(h.e1,28)
        self.assertEqual(h.grips,[(28,5)])
        self.assertEqual(h.moves[0][2]['segment_speeds'],[5]+[137]*5)
        self.assertEqual(h.angle,90.71661229181757)
        with self.assertRaisesRegex(TransferError,'already used'):c.plan(h.service,h.g['cfg'],self.source,'return_home')
        p=c.plan(h.service,h.g['cfg'],result['record'],'deliver_squid')
        delivered=c.execute(h.run,h.service,h.g['cfg'],p)
        d=json.loads(Path(delivered['record']).read_bytes())
        self.assertEqual(d['payload'],'held');self.assertEqual(h.e1,3.9)
        self.assertEqual(h.angle,1.77);self.assertEqual(h.moves[-1][0],h.g['points'])
        self.assertNotIn((7,5),h.grips);h.service.program.assert_not_called()
        p=c.plan(h.service,h.g['cfg'],delivered['record'],'return_squid')
        returned=c.execute(h.run,h.service,h.g['cfg'],p)
        d=json.loads(Path(returned['record']).read_bytes())
        self.assertEqual(d['payload'],'empty');self.assertEqual(h.e1,28)
        self.assertEqual(h.state['pose_mm'],h.g['clearance'])
        self.assertEqual(h.moves[-3][0],h.g['reverse'])
        h.service.program.assert_not_called()

    def test_uncertain_source_or_grip_blocks_before_motion(self):
        h=self.h;h.e1=24
        with self.assertRaises(TransferError):c.plan(h.service,h.g['cfg'],self.source,'return_home')
        h.e1=25;d=json.loads(self.source.read_bytes());d['status']='stopped_or_uncertain';self.source.write_text(json.dumps(d))
        with self.assertRaises(TransferError):c.plan(h.service,h.g['cfg'],self.source,'return_home')
        self.assertEqual(h.moves,[]);self.assertEqual(h.grips,[])

    def test_modified_plan_cannot_dispatch(self):
        h=self.h;p=c.plan(h.service,h.g['cfg'],self.source,'return_home')
        p['steps'][0]['points'][0]['Z']+=1
        with self.assertRaisesRegex(TransferError,'plan changed'):c.execute(h.run,h.service,h.g['cfg'],p)
        self.assertEqual(h.moves,[])


if __name__=='__main__':unittest.main()
