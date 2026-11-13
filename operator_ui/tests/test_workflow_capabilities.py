"""State composition and receipt-bound executor checks; no hardware I/O."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import workflow_capabilities as contracts
import capability_workflow as binding

PROFILE = binding.PROFILE


class ContractTests(unittest.TestCase):
    def state(self, location): return dict(plate_location=location, payload='empty', arm_location='HOME')
    def test_retrieval_already_satisfies_explicit_home_goal(self):
        plan = contracts.compose(['retrieve_squid', 'return_HOME'], self.state('Squid'), PROFILE)
        self.assertEqual(len(plan['capabilities']), 1)
        self.assertEqual(plan['trace'][-1]['satisfied_by'], 'verified_postcondition')
        self.assertEqual(plan['final'], self.state('HOME'))
    def test_home_goal_selects_capability_from_current_state(self):
        for station in ('Squid', 'Hamilton'):
            plan = contracts.compose(['return_HOME'], self.state(station), PROFILE)
            self.assertEqual(plan['capabilities'][0]['capability']['operation'], 'retrieve_'+station.lower())
    def test_composes_unlisted_cross_station_order(self):
        ops = ['retrieve_squid','return_HOME','deliver_hamilton','retrieve_hamilton','deliver_squid']
        plan = contracts.compose(ops, self.state('Squid'), PROFILE, 3)
        self.assertEqual(len(plan['capabilities']), 12)
        self.assertEqual(len(plan['trace']), len(ops)*3)
        self.assertEqual(plan['final'], self.state('Squid'))
    def test_new_declaration_needs_no_new_order_case(self):
        data, _ = contracts.load()
        cap = deepcopy(data['capabilities'][0])
        cap.update(id='fixture_inspect', operation='inspect_fixture', requires=self.state('HOME'), effects={'inspected': True})
        data['capabilities'].append(cap)
        plan = contracts.compose(['inspect_fixture','deliver_squid','retrieve_squid','return_HOME'], self.state('HOME'), PROFILE, registry=data)
        self.assertEqual(len(plan['capabilities']), 3)
        self.assertTrue(plan['final']['inspected'])
    def test_incompatible_state_profile_or_suffix_never_returns_prefix(self):
        for operations, state, profile in [
            (['retrieve_squid'], self.state('HOME'), PROFILE),
            (['retrieve_squid','squid_image'], self.state('Squid'), PROFILE),
            (['retrieve_squid'], self.state('Squid'), '48_well_projected_20261026'),
            (['retrieve_squid'], dict(self.state('Squid'), payload='held'), PROFILE)]:
            with self.subTest(operations=operations, profile=profile):
                with self.assertRaises(Exception): contracts.compose(operations,state,profile)
    def test_repetition_rechecks_end_to_start_contract(self):
        with self.assertRaisesRegex(Exception,'cycle 2'):
            contracts.compose(['retrieve_squid','return_HOME'],self.state('Squid'),PROFILE,2)
    def test_home_goal_at_home_has_no_physical_capability(self):
        self.assertEqual(contracts.compose(['return_HOME'],self.state('HOME'),PROFILE)['capabilities'],[])
    def test_executor_rejects_falsified_contract(self):
        cap = deepcopy(contracts.load()[0]['capabilities'][1])
        cap['effects']['plate_location'] = 'Hamilton'
        with self.assertRaisesRegex(Exception,'contract'): binding.bind_phase(cap)


class RouterTests(unittest.TestCase):
    def agent(self):
        a=Mock();a.lock=threading.RLock();a.pending=None
        a._plan_view.side_effect=lambda plan:deepcopy(plan)
        return a
    def test_router_delegates_unlisted_order_to_contract_composer(self):
        from lacry_workflow_router import WorkflowRouter
        a=self.agent();ops=['retrieve_squid','return_HOME','deliver_hamilton','retrieve_hamilton','return_HOME']
        with patch.object(binding,'CapabilityWorkflow') as api:
            api.return_value.propose.return_value=dict(ok=True,awaiting_confirmation=True)
            result=WorkflowRouter(a).propose(ops)
        self.assertTrue(result['awaiting_confirmation'])
        api.return_value.propose.assert_called_once_with(ops,None,None,1)
        a.confirm.assert_not_called()
    def test_router_keeps_complete_request_on_actual_state_refusal(self):
        from lacry_workflow_router import WorkflowRouter
        a=self.agent();ops=['retrieve_squid','return_HOME']
        with patch.object(binding,'CapabilityWorkflow') as api:
            api.return_value.propose.side_effect=binding.TransferError('Live jaw state differs from receipt')
            result=WorkflowRouter(a).propose(ops)
        self.assertTrue(result['blocked']);self.assertEqual(a.pending['labels'],ops)
        self.assertIn('Live jaw state',a.pending['blockers'][0])
    def test_public_catalog_exposes_executor_preconditions_and_effects(self):
        from lacry_workflow_router import catalog
        c=catalog()['capability_registry']['capabilities']
        retrieve=next(item for item in c if item['operation']=='retrieve_squid')
        self.assertEqual(retrieve['requires']['plate_location'],'Squid')
        self.assertEqual(retrieve['effects']['plate_location'],'HOME')


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)/'compositions'; self.folder.mkdir()
        self.runs = Path(self.tmp.name)/'motions'; self.runs.mkdir()
        self.motion_path = self.runs/('a'*32)/'run.json'; self.motion_path.parent.mkdir()
        self.outer_path = self.folder/('c'*32+'.json')
        self.g = binding.geometry()
        self.pose = deepcopy(self.g['clearance'])
        self.joints = dict(J1=67.12272,J2=40.77098,J3=59.31776,J4=-10.24864)
        self.state = dict(ok=True, connected=True, enabled=True, errors=[], control_mode={'mode':'auto'},
                          program_state={'state':'running'}, pose_mm=self.pose, joints=self.joints)
        self.axes = dict(E1=6.9997,E2=1.774)
        outbound = binding.delivery_steps('Squid',False)
        self.motion = dict(status='experiment_delivery_complete',payload='empty',finished_at=time.time(),
            plan=dict(steps=outbound,acceptance_sha256=binding.evidence(),projected_trial=False,
                      taught_hamilton_delivery=False,recorded_hamilton_delivery=False),
            final=deepcopy(self.state),final_native=dict(external_axes=deepcopy(self.axes)),
            steps=[dict(s,status='completed') for s in outbound])
        self.outer = dict(status='completed_controller_verified',finished_at=time.time(),plate_id='P1',plate_destination='Squid',
            plan=dict(composition=dict(plate_profile=PROFILE,roundtrip=False,continuation=dict(delivery_steps=outbound))),
            steps=[dict(status='completed',result=dict(record=str(self.motion_path),plate_id='P1',plate_location='Squid'))])
        self.save()
        self.backend=Mock(); self.backend.params.return_value=self.g['cfg']
        self.backend.s.status.side_effect=lambda:deepcopy(self.state)
        self.backend.s._preflight.return_value=None
        self.backend.s.envelope=self.g['envelope'];self.backend.s.envelope_enabled=True
        self.registry=Mock();self.registry.get.return_value=dict(revision=3,metadata=dict(plate_type=PROFILE))
        self.check_station=Mock()
        for p in (patch.object(binding,'RUNS',self.runs),
                  patch.object(binding,'native',lambda _:dict(moving=False,external_axes=deepcopy(self.axes)))):
            p.start();self.addCleanup(p.stop)
        self.adapter=binding.CapabilityAdapter(backend=self.backend,registry=self.registry,folder=self.folder,station_check=self.check_station)
    def save(self):
        self.motion_path.write_text(json.dumps(self.motion),encoding='utf-8')
        self.outer_path.write_text(json.dumps(self.outer),encoding='utf-8')
    def preview(self, operations=None):
        return self.adapter.preview(operations or ['retrieve_squid','return_HOME'],chain_id='b'*32)
    def test_resolves_plate_and_binds_existing_retrieval_tail_read_only(self):
        spec=self.preview()
        self.assertEqual(spec['plate_id'],'P1');self.assertEqual(spec['destination'],'HOME')
        full=binding.delivery_steps('Squid',True);outbound=binding.delivery_steps('Squid',False)
        self.assertEqual(spec['motion_steps'],full[len(outbound):])
        self.assertEqual(spec['initial_e1'],7)
        self.backend.s.move_gripper.assert_not_called()
        self.backend.s.program.assert_not_called()
        self.adapter.verify(spec)
    def test_multiple_compatible_phases_validate_as_one_plan(self):
        spec=self.preview(['retrieve_squid','return_HOME','deliver_hamilton','retrieve_hamilton','return_HOME'])
        self.assertEqual(len(spec['capability_chain']['capabilities']),3)
        self.assertEqual(spec['destination'],'HOME')
        self.assertTrue(any(s.get('flags',{}).get('transit_blend') for s in spec['motion_steps']))
    def test_expired_receipt_not_silently_refreshed(self):
        self.outer['finished_at']-=1801;self.save()
        with self.assertRaisesRegex(Exception,'older than 30'):self.preview()
    def test_wrong_plate_profile_and_changed_registration_refused(self):
        for args in (dict(plate_id='P2'),dict(profile='48_well_projected_20261026')):
            with self.assertRaisesRegex(Exception,'differs'):
                self.adapter.preview(['retrieve_squid'],**args)
        spec=self.preview();self.registry.get.return_value['revision']+=1
        with self.assertRaisesRegex(Exception,'identity'):self.adapter.verify(spec)
    def test_pose_jaws_or_holder_changed_refused(self):
        for key in ('E1','E2'):
            self.axes[key]+=1
            with self.assertRaisesRegex(Exception,'checkpoint'):self.preview()
            self.axes[key]-=1
        self.pose['X']+=1
        with self.assertRaisesRegex(Exception,'Pose mismatch'):self.preview()
    def test_changed_or_uncertain_motion_cannot_supply_custody(self):
        self.motion['steps'][-1]['status']='dispatching';self.save()
        with self.assertRaisesRegex(Exception,'does not prove'):self.preview()
    def test_newer_motion_prevents_reusing_old_success(self):
        later=self.runs/('f'*32)/'run.json';later.parent.mkdir();later.write_text('{}')
        with self.assertRaisesRegex(Exception,'later Cellvis'):self.preview()
    def test_newer_uncertain_outer_record_prevents_reusing_old_success(self):
        (self.folder/('d'*32+'.json')).write_text(json.dumps(dict(status='stopped_or_uncertain')))
        with self.assertRaisesRegex(Exception,'unresolved'):self.preview()
    def test_equal_receipt_timestamps_cannot_hide_uncertainty(self):
        other=self.folder/('d'*32+'.json')
        other.write_text(json.dumps(dict(status='stopped_or_uncertain')))
        stamp=self.outer_path.stat().st_mtime_ns
        os.utime(other,ns=(stamp,stamp))
        with self.assertRaisesRegex(Exception,'ambiguous or unresolved'):self.preview()
    def test_model_cannot_replace_bound_steps(self):
        spec=self.preview();spec['motion_steps']=[]
        with self.assertRaisesRegex(Exception,'plan'):self.adapter.verify(spec)
    def test_one_existing_executor_receives_whole_chain_and_commanded_jaw_width(self):
        spec=self.preview();run=Mock();run.stopped.return_value=False
        with patch.object(binding,'LuaTrajectory') as queue, patch.object(binding,'execute_checked_steps') as execute:
            queue.return_value.capability.return_value=dict(available=True,version=220109)
            execute.return_value=dict(ok=True,record='fixture')
            result=self.adapter.execute_step(run,spec,'execute_capabilities',None)
        self.assertEqual(result['plate_location'],'HOME')
        self.assertEqual(execute.call_args.args[3]['steps'],spec['motion_steps'])
        self.assertEqual(execute.call_args.kwargs['initial_e1'],7)
        execute.assert_called_once()
    def test_uncertain_executor_is_not_retried(self):
        spec=self.preview();run=Mock();run.stopped.return_value=False
        with patch.object(binding,'LuaTrajectory') as queue, patch.object(binding,'execute_checked_steps') as execute:
            queue.return_value.capability.return_value=dict(available=True,version=220109)
            execute.return_value=dict(ok=True,recovered=True)
            with self.assertRaisesRegex(Exception,'uncertain'):
                self.adapter.execute_step(run,spec,'execute_capabilities',None)
            execute.assert_called_once()
    def test_stopped_run_never_probes_or_dispatches(self):
        spec=self.preview();run=Mock();run.stopped.return_value=True
        with patch.object(binding,'LuaTrajectory') as queue:
            with self.assertRaisesRegex(Exception,'stopped'):
                self.adapter.execute_step(run,spec,'execute_capabilities',None)
            queue.assert_not_called()


if __name__=='__main__':unittest.main()
