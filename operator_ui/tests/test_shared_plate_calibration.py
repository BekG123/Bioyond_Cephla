"""Offline projection equivalence, pose transport and execution boundaries."""
import json
import math
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

import cellvis24_calibration as c
import cellvis24_workflow as w
from autonomy import TransferError
from projected_plate_calibration import solve, measurement_from_outlines
from test_cellvis24_workflow import WorkflowTests, FullCalibrationTests


def samples(profile):
    target=dict(zip(('x','y','rz'),profile.reference_target))
    return [dict(target=deepcopy(target),error_xy_mm=[0.,0.],measured_wells=profile.rows*profile.columns,
                 grid_rmse_px=1.,corners_preview_px=[[100,100],[500,100],[500,300],[100,300]]) for _ in range(3)]


class SharedMathTests(unittest.TestCase):
    def setUp(self):
        self.p=c.projected_profile();self.ms=samples(self.p)

    def test_identity_exact_taught_endpoint_grip_height_and_no_double_offset(self):
        solution=solve(self.ms,self.p)
        np.testing.assert_allclose(list(solution['endpoint'].values()),self.p.taught_endpoint,atol=1e-12)
        self.assertEqual(solution['grip_e1_mm'],3.9)
        self.assertEqual(solution['endpoint']['Z'],75.72)
        self.assertEqual(solve(self.ms,self.p),solution)
        self.assertFalse(solution['grip_authorized'])

    def test_known_rigid_plate_motion_moves_entire_taught_relationship_once(self):
        for m in self.ms:
            m['target']['x']+=.3;m['target']['y']-=.1;m['target']['rz']+=.3
        result=solve(self.ms,self.p)
        # Independent homogeneous-matrix composition.
        def matrix(x,y,a):
            a=math.radians(a)
            return np.array([[math.cos(a),-math.sin(a),x],[math.sin(a),math.cos(a),y],[0,0,1]])
        b=self.p.reference_target;s=self.p.taught_endpoint
        goal=matrix(b[0]+.3,b[1]-.1,b[2]+.3)@np.linalg.inv(matrix(*b))@matrix(s[0],s[1],s[3])
        np.testing.assert_allclose([result['endpoint']['X'],result['endpoint']['Y']],goal[:2,2],atol=1e-10)
        self.assertAlmostEqual(result['endpoint']['Rz'],s[3]+.3)

    def test_wrapped_yaw_and_plate_specific_grid(self):
        for m in self.ms:m['target']['rz']-=359.9
        self.assertAlmostEqual(solve(self.ms,self.p)['yaw_delta_deg'],.1)
        p48=replace(self.p,plate_id='48-test',rows=6,columns=8,min_wells=40)
        with self.assertRaises(TransferError):solve(self.ms,p48)
        self.assertEqual(solve(samples(p48),p48)['grid'],[6,8])

    def test_bad_grid_unstable_nonfinite_and_out_of_scope_fail(self):
        cases=[('measured_wells',19),('grid_rmse_px',8.1),('grid_rmse_px',-1),
               ('error_xy_mm',[.8,0]),('corners_preview_px',[[float('nan'),0]]*4)]
        for key,value in cases:
            ms=deepcopy(self.ms);ms[0][key]=value
            with self.subTest(key=key),self.assertRaises(TransferError):solve(ms,self.p)
        for delta in (.4,float('nan'),float('inf')):
            ms=deepcopy(self.ms);ms[0]['target']['x']+=delta
            with self.assertRaises(TransferError):solve(ms,self.p)
        ms=deepcopy(self.ms)
        for m in ms:m['target']['x']+=1.1
        with self.assertRaises(TransferError):solve(ms,self.p)

    def test_saved_cellvis_outlines_reproduce_original_vendor_measurement(self):
        import teach
        d=c.reference();source=json.loads((c.ROOT/d['files']['observation']['path']).read_bytes())
        cfg=next(x for x in teach._configs() if x['name']=='Wide')
        for b in source['bursts']:
            old=b['measurement']
            actual=measurement_from_outlines(old['projected_original_disks_px'],c.OBSERVATION,cfg)
            np.testing.assert_allclose(actual['mark'],old['mark'],atol=1e-10)
            np.testing.assert_allclose(list(actual['target'].values()),list(old['target'].values()),atol=1e-10)

    def test_recent_fixed_reference_rejection_produces_candidate_not_grip_acceptance(self):
        path=c.ROOT/'operator_ui/reports/plate_session/cellvis24_workflows/bc7a778234df4e33a875440d6bc04774/run.json'
        if not path.exists():self.skipTest('Historical run not bundled')
        record=json.loads(path.read_bytes())
        vision=next(s['measurement'] for s in record['steps'] if s['kind']=='vision')
        ms=[b['measurement'] for b in vision['bursts']]
        self.assertFalse(c.evaluate(ms)['ok'])
        result=c.projected_solution(ms)
        self.assertLess(result['endpoint_shift_mm'],1)
        self.assertGreater(result['yaw_delta_deg'],.2)
        self.assertFalse(result['grip_authorized'])
        self.assertEqual(result['physical_acceptance'],'pending')


class TrialExecutionTests(unittest.TestCase):
    # Reuse fake hardware setup, but do not inherit/run the unrelated station suite.
    setUp=WorkflowTests.setUp
    host=WorkflowTests.host
    grip=WorkflowTests.grip
    queue=WorkflowTests.queue
    setup_calibration=FullCalibrationTests.setup_calibration

    def prepare(self):
        align,capture=self.setup_calibration()
        ms=samples(c.projected_profile())
        for m in ms:m['target']['x']+=.3;m['target']['rz']+=.3
        self.solution=c.projected_solution(ms)
        capture.return_value=dict(projected_solution=self.solution)
        p=w.plan(self.service,self.g['cfg'],[],1,full_calibration=True,projected_trial=True)
        return p,align,capture

    def test_fresh_solution_reaches_alignment_and_descent_no_grip_no_station_receipt(self):
        p,align,capture=self.prepare()
        result=w.execute(self.run,self.service,self.g['cfg'],p,cam=Mock())
        self.assertEqual(result['status'],'awaiting_open_claw_inspection')
        self.assertFalse(result['full_calibration_complete']);self.assertFalse(result['grip_authorized'])
        self.assertEqual(self.state['pose_mm'],self.solution['endpoint'])
        target=align.call_args.args[2]
        self.assertEqual(target['x'],self.solution['endpoint']['X'])
        self.assertEqual(target['rz'],self.solution['endpoint']['Rz'])
        self.assertFalse(capture.call_args.kwargs['require_fixed_reference'])
        self.assertFalse(self.grips);self.assertEqual(self.e1,28)
        self.service.program.assert_not_called()
        w.hamilton_ready.assert_not_called();w.squid_ready.assert_not_called()
        record=json.loads(Path(result['record']).read_bytes())
        self.assertEqual(record['calibration_runs'],0)
        self.assertTrue(record['resolved_calibration']['ik_checked'])
        with self.assertRaises(TransferError):w.source_record(result['record'])

    def test_runtime_ik_failure_stops_at_observation_before_alignment(self):
        p,align,capture=self.prepare()
        real=w.validate_steps
        def validate(steps,*args):
            if steps and steps[0]['kind']=='align':raise TransferError('IK rejected measured endpoint')
            return real(steps,*args)
        with patch.object(w,'validate_steps',side_effect=validate),self.assertRaisesRegex(TransferError,'IK rejected'):
            w.execute(self.run,self.service,self.g['cfg'],p,cam=Mock())
        self.assertEqual(len(self.moves),1);self.assertFalse(self.grips);align.assert_not_called()
        self.service.program.assert_called_once_with('stop')

    def test_trial_cannot_be_combined_with_station_transfer(self):
        self.setup_calibration()
        for stations,cycles,full in [(['hamilton'],1,True),(['squid'],1,True),([],2,True),([],1,False)]:
            with self.assertRaises(TransferError):
                w.plan(self.service,self.g['cfg'],stations,cycles,full_calibration=full,projected_trial=True)
        self.assertFalse(self.moves)

    def test_code_change_invalidates_preview_without_dispatch(self):
        p,_,_=self.prepare()
        with patch.object(c,'implementation_binding',return_value={'changed':'version'}),self.assertRaises(TransferError):
            w.execute(self.run,self.service,self.g['cfg'],p,cam=Mock())
        self.assertFalse(self.moves);self.assertFalse(self.grips)


class TrialCliTests(unittest.TestCase):
    def test_preview_is_offline_and_shows_no_closure(self):
        from run_cellvis24_workflow import main,parse_args
        with patch('run_cellvis24_workflow.api',side_effect=AssertionError('Hardware called')),patch('builtins.print') as output:
            main(['--projected-calibration-trial'])
        d=json.loads(output.call_args.args[0])
        self.assertTrue(d['projected_trial']);self.assertEqual(d['calibration_runs'],0)
        self.assertFalse(any(s['kind']=='jaws' for s in d['steps']))
        with patch('sys.stderr'),self.assertRaises(SystemExit):
            parse_args(['--projected-calibration-trial','--home-to-squid-roundtrip'])


if __name__=='__main__':unittest.main()
