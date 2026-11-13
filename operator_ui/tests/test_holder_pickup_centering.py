import json
import unittest
from copy import deepcopy
import cellvis24_workflow as w
from autonomy import TransferError
from test_cellvis24_workflow import WorkflowTests as Fixture


class HolderPickupCenteringTests(unittest.TestCase):
    def fixture(self):
        h=Fixture('test_grip_or_holder_mismatch_prevents_dispatch')
        h.setUp();self.addCleanup(h.doCleanups)
        r=w.reference()['routes']['forward']
        h.state.update(pose_mm=dict(r['start'],Z=r['start']['Z']+25),joints=deepcopy(r['start_joints']))
        h.state['joints']['J1']+=25
        h.angle=90.41448570407123
        d=json.loads(h.source.read_text());d['final']=deepcopy(h.state)
        h.source.write_text(json.dumps(d))
        return h

    def test_accepted_contact_bias_is_corrected_before_any_pickup(self):
        h=self.fixture();observed=[];original=h.host
        def host(params,mode,timeout):
            if mode==14:
                observed.append((h.e1,len(h.moves),len(h.grips),params[9]))
            return original(params,mode,timeout)
        h.service._hostpoint.side_effect=host
        p=w.plan(h.service,h.g['cfg'],['hamilton'],1,h.source)
        result=w.execute(h.run,h.service,h.g['cfg'],p)
        self.assertEqual(observed[0],(28,0,0,90.71661229181757))
        self.assertEqual(result['completed_cycles'],1)
        h.service.program.assert_not_called()

    def test_ack_without_centered_feedback_stops_before_descent(self):
        h=self.fixture();original=h.host
        def host(params,mode,timeout):
            result=original(params,mode,timeout)
            if mode==14:h.angle=90.41448570407123
            return result
        h.service._hostpoint.side_effect=host
        p=w.plan(h.service,h.g['cfg'],['hamilton'],1,h.source)
        with self.assertRaisesRegex(TransferError,'pickup angle'):
            w.execute(h.run,h.service,h.g['cfg'],p)
        self.assertFalse(h.moves);self.assertFalse(h.grips)
        self.assertEqual(sum(c.args[1]==14 for c in h.service._hostpoint.call_args_list),1)


if __name__=='__main__':unittest.main()
