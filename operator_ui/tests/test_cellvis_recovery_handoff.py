import json
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

import cellvis_recovery_handoff as h


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);rec=root/'recoveries';rec.mkdir()
        self.path=rec/'one.json';self.e2=91.634;self.e1=28;self.calls=[]
        self.cfg={'test':1};self.g=dict(id='a'*32,cfg=self.cfg,station_clearance=h.HOME)
        self.s=dict(pose_mm=deepcopy(h.HOME),external_axes={'E1':28})
        self.d=dict(status='completed',payload_confirmed_empty=True,experiment_retried=False,
            final=self.s,plan={'external_axes':{'E2':self.e2}},finished_at=time.time())
        self.path.write_text(json.dumps(self.d))
        self.svc=SimpleNamespace(envelope_enabled=True,envelope={'X':(200,450),'Y':(-250,380),'Z':(70,400)},
            _locked=lambda fn:fn(),_hostpoint=self.hostpoint,program=lambda a:self.calls.append(a) or {'ok':True},
            robot=SimpleNamespace(get_sys_var_i=lambda keys:{7:self.token,8:250104}))
        self.run=SimpleNamespace(stopped=lambda:False,say=Mock())
        for p in (patch.object(h,'RECOVERIES',rec),patch.object(h,'OUTPUT',root/'out'),
            patch.object(h,'geometry',lambda ident:deepcopy(self.g)),patch.object(h,'preflight',lambda svc:deepcopy(self.s)),
            patch.object(h,'native',lambda svc:dict(moving=False,manual=False,drag=False,error=False,emergency=False,
                external_axes={'E1':self.e1,'E2':self.e2})),patch.object(h.time,'sleep',lambda _:None)):
            p.start();self.addCleanup(p.stop)
    def hostpoint(self,values,mode,timeout):
        self.calls.append(mode);self.token=int(values[7])
        if mode==14:self.e2=values[9]
        return {'ok':True}
    def preview(self):return h.preview(self.svc,self.cfg,self.path,self.g['id'])
    def test_readonly_preview_and_holder_only_handoff(self):
        p=self.preview();self.assertEqual(self.calls,[])
        result=h.execute(self.run,self.svc,self.cfg,json.loads(json.dumps(p)))
        d=json.loads(Path(result['record']).read_bytes())
        self.assertEqual(self.calls,[13,14]);self.assertEqual(self.e2,1.77)
        self.assertEqual(h.validate_source(result['record'],d),self.g)
        with self.assertRaises(Exception):self.preview()
    def test_closed_jaws_wrong_pose_and_stale_receipt_block(self):
        self.e1=25
        with self.assertRaises(Exception):self.preview()
        self.e1=28;self.s['pose_mm']['Z']-=5
        with self.assertRaises(Exception):self.preview()
        self.s['pose_mm']=deepcopy(h.HOME);self.d['finished_at']-=1801;self.path.write_text(json.dumps(self.d))
        with self.assertRaisesRegex(Exception,'expired'):self.preview()
        self.assertEqual(self.calls,[])
    def test_changed_target_or_holder_blocks_before_motion(self):
        p=self.preview();p['targets']=[90]
        with self.assertRaises(Exception):h.execute(self.run,self.svc,self.cfg,p)
        p=self.preview();self.e2+=.2
        with self.assertRaises(Exception):h.execute(self.run,self.svc,self.cfg,p)
        self.assertEqual(self.calls,[])
    def test_uncertain_rotation_stops_and_cannot_retry(self):
        p=self.preview();original=self.svc._hostpoint
        self.svc._hostpoint=lambda values,mode,timeout: {'ok':False} if mode==14 else original(values,mode,timeout)
        with self.assertRaisesRegex(Exception,'uncertain'):h.execute(self.run,self.svc,self.cfg,p)
        self.assertEqual(self.calls,[13,'stop'])
        with self.assertRaisesRegex(Exception,'already handed off'):self.preview()
    def test_modified_recovery_invalidates_successor(self):
        result=h.execute(self.run,self.svc,self.cfg,self.preview());p=Path(result['record']);d=json.loads(p.read_bytes())
        self.d['extra']='changed';self.path.write_text(json.dumps(self.d))
        with self.assertRaises(Exception):h.validate_source(p,d)


if __name__=='__main__':unittest.main()
