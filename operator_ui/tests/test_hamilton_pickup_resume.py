import json
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import cellvis24_hamilton_continuation as c
import cellvis24_workflow as w
from test_cellvis24_workflow import WorkflowTests as Fixture
from autonomy import TransferError


class PickupResumeTests(unittest.TestCase):
    def setUp(self):
        h=self.h=Fixture('test_grip_or_holder_mismatch_prevents_dispatch');h.setUp();self.addCleanup(h.doCleanups)
        r=c.reference('opposite3')['routes']['reverse'];h.state.update(pose_mm=deepcopy(r['start']),joints=deepcopy(r['start_joints']))
        h.e1=28;h.angle=90.71661229181757
        for p in [patch.object(c,'preflight',side_effect=lambda s:deepcopy(h.state)),
                  patch.object(c,'native',side_effect=lambda s:dict(moving=False,external_axes={'E1':h.e1,'E2':h.angle})),
                  patch.object(c,'LuaTrajectory',w.LuaTrajectory),
                  patch('hamilton_transit_blend.require_capability',return_value={'blended_transit_capability':220114}),
                  patch('hamilton_transit_blend.BlendedTransitTrajectory',w.LuaTrajectory)]:
            p.start();self.addCleanup(p.stop)
        full=w.compile_steps(['hamilton','squid'],1,recorded_hamilton_variant='opposite3')
        pickup=max(i for i,s in enumerate(full) if s['station']=='hamilton' and s['label']=='Travel forward')
        self.source=w.RUNS/('b'*32)/'run.json';self.source.parent.mkdir(parents=True)
        failed=dict(status='stopped_or_uncertain',error='Jaw arrival not verified; no lift.',finished_at=time.time(),
                    plan=dict(steps=full),steps=[dict(s,status='completed' if i<pickup+2 else 'checking') for i,s in enumerate(full[:pickup+3])])
        self.source.write_text(json.dumps(failed))
        self.review=self.source.parent/'pickup_recovery_ready.json'
        self.review.write_text(json.dumps(dict(source_sha256=w.sha(self.source),at=time.time(),plate_reseated_site4=True,
            empty_jaws_open_verified=True,operator_requested_continuation=True,final=h.state)))
        def queue(run,start,joints,points,cfg,speed,progress,**flags):
            step=dict(kind='queue',points=points,flags={k:v for k,v in flags.items() if k!='reviewed'})
            h.state.update(w.validate_steps([step],dict(pose_mm=start,joints=joints),cfg,h.g['envelope']))
            h.moves.append((points,speed,flags,h.e1));return dict(ok=True)
        h.lua.return_value.execute.side_effect=queue

    def test_resume_only_pickup_then_squid_finishes_home(self):
        h=self.h;p=c.plan(h.service,h.g['cfg'],self.source,'resume_hamilton_pickup')
        self.assertEqual([s['target'] for s in p['steps'][1:3]],[26,25])
        self.assertFalse(any(s['station']=='hamilton' and s['label']=='Travel forward' for s in p['steps']))
        r=c.execute(h.run,h.service,h.g['cfg'],p)
        self.assertEqual(h.e1,28);self.assertEqual(h.state['pose_mm'],h.g['clearance'])
        self.assertEqual(json.loads(Path(r['record']).read_bytes())['payload'],'empty')
        h.service.program.assert_not_called()
        with self.assertRaisesRegex(TransferError,'already used'):c.source_record(self.source,'resume_hamilton_pickup')

    def test_missing_confirmation_and_changed_review_block(self):
        h=self.h;p=c.plan(h.service,h.g['cfg'],self.source,'resume_hamilton_pickup')
        d=json.loads(self.review.read_bytes());d['plate_reseated_site4']=False;self.review.write_text(json.dumps(d))
        with self.assertRaises(TransferError):c.execute(h.run,h.service,h.g['cfg'],p)
        self.assertFalse(h.moves);self.assertFalse(h.grips)


if __name__=='__main__':unittest.main()
