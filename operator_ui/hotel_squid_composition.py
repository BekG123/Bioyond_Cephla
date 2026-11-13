"""Accepted hotel retrieval adapter. Scanner/station handoffs require bindings.

No new coordinates, controller startup, recovery or inferred acceptance.
"""
import importlib
import hashlib
import json
import math
from pathlib import Path
from autonomy import TransferError
from scope_step_trial import preflight, near

PROFILE_ACCEPTANCE=Path(__file__).resolve().parents[1]/'Pick and Hold/Station Handling/workflows/hotel_slot1_retrieval_profiles.json'
PROFILE_ALIASES={'Falcon 48-well':'48_well_projected_20261026',
                 'Falcon 48-well plate':'48_well_projected_20261026'}


def profile_binding(profile,slot):
    profile=PROFILE_ALIASES.get(profile,profile)
    if profile=='48_well_projected_20261026':return dict(profile=profile,basis='original_workflow')
    if slot!=1 or profile!='Cellvis P24-1.5H-N':
        raise TransferError('No accepted retrieval binding for this plate profile and slot.')
    raw=PROFILE_ACCEPTANCE.read_bytes();acceptance=json.loads(raw)
    if (acceptance['slot']!=slot or acceptance['action']!='retrieve' or
            profile not in acceptance['profiles'] or acceptance['basis']!='operator_confirmation_of_previous_testing'):
        raise TransferError('Slot-1 profile acceptance changed.')
    return dict(profile=profile,acceptance_sha256=hashlib.sha256(raw).hexdigest(),
                geometry_sha256=acceptance['retrieval_geometry_sha256'],
                basis=acceptance['basis'])


def hotel(slot):
    if type(slot) is not int or slot not in (1,2,3):
        raise TransferError('Only accepted hotel slots 1, 2 and 3 are supported.')
    module=importlib.import_module('hotel_slot1_retrieval' if slot==1 else f'hotel_slot{slot}_handling')
    workflow=importlib.import_module(f'run_hotel_slot{slot}_workflow')
    accepted,plans=workflow.load_workflow()
    return module,accepted,plans['retrieve'] if slot==1 else plans


class HotelSquidAdapter:
    def __init__(self,agent=None,*,backend=None,registry=None,station_check=None):
        self.agent=agent
        self.backend=backend if backend is not None else agent.backend
        self._registry=registry
        self.station_check=station_check

    def registry(self):
        if self._registry is not None:return self._registry
        registry=getattr(self.agent.memory,'plates',None)
        if registry is None:raise TransferError('Plate registry unavailable.')
        return registry

    def preview(self,plate_id,slot,destination,plate_profile=None,roundtrip=False,instrument_request=None):
        from hotel_holder_preparation import preparation
        from home_hamilton_exchange import native
        if destination not in ('HOME','Squid','Hamilton'):raise TransferError('Unknown transfer destination.')
        if type(roundtrip) is not bool or (roundtrip and destination=='HOME'):
            raise TransferError('Roundtrip requires an instrument destination.')
        plate=self.registry().get(plate_id) if plate_id is not None else None
        recorded_profile=plate.get('metadata',{}).get('plate_type') if plate else None
        profile=plate_profile or recorded_profile
        binding=profile_binding(profile,slot)
        chain=None
        if instrument_request is not None:
            if (roundtrip or slot!=1 or binding['profile']!='Cellvis P24-1.5H-N' or
                    (instrument_request.get('stations') or ['HOME'])[0]!=destination):
                raise TransferError('Instrument chains require Cellvis slot 1 and the matching first destination.')
            from composed_instrument_chain import prepare
            chain=prepare(self.backend,instrument_request,self.agent)
        composition=None
        registration=bool(chain and any(x['capability']['executor']=='cellvis_registration' for x in chain['request'].get('composition',{}).get('capabilities',[])))
        if destination!='HOME' or registration:
            if slot!=1 or binding['profile']!='Cellvis P24-1.5H-N':
                raise TransferError('This scanner handoff is accepted for Cellvis slot 1 only.')
            from hotel_cellvis_handoff import scanner_reference
            from composed_cellvis_registration import delivery_steps
            from cellvis24_workflow import evidence, geometry, squid_ready, hamilton_ready
            composition=dict(scanner=scanner_reference(),delivery_steps=delivery_steps(destination,roundtrip) if destination!='HOME' else [],acceptance=evidence())
            if self.station_check is not None and destination!='HOME':self.station_check(destination.lower(),geometry())
            elif destination!='HOME' and not (chain and destination=='Squid' and chain['imaging']):
                hamilton_ready() if destination=='Hamilton' else squid_ready(geometry())
        if plate is not None and (not plate.get('scan_count') or
                PROFILE_ALIASES.get(recorded_profile,recorded_profile)!=binding['profile']):
            raise TransferError('Requested profile conflicts with the registered plate. Resolve its identity before retrieval.')
        module,workflow,geometry=hotel(slot)
        if binding.get('geometry_sha256') and workflow['geometry_sha256']['retrieve']!=binding['geometry_sha256']:
            raise TransferError('Slot-1 accepted retrieval geometry changed.')
        if (self.backend.params()!=geometry['cfg'] or
                {k:list(v) for k,v in self.backend.s.envelope.items()}!=geometry['envelope']):
            raise TransferError('Accepted hotel configuration or workspace changed.')
        if plate is not None and plate.get('location')!=f'rack:1/slot:{slot}':
            raise TransferError('Plate record does not place this plate in that slot. Ask its actual location; a reservation is insufficient.')
        s=preflight(self.backend.s);n=native(self.backend.s)
        try:
            if slot==1:
                from hotel_home_start import check_home_start
                check_home_start(s['pose_mm'],geometry['home'])
            else:near(s['pose_mm'],geometry['home'],.05)
        except TransferError as error:
            if slot==1:raise
            raise TransferError(f"Arm is outside HOME clearance. Measured: {s['pose_mm']}; required: {geometry['home']}. Use the checked HOME return first.") from error
        if n['moving']:raise TransferError('Arm is moving; wait until stationary before planning the transfer.')
        if not math.isfinite(n['external_axes']['E1']) or not 0<=n['external_axes']['E1']<=28.15:
            raise TransferError('Invalid jaw feedback.')
        holder_preparation=preparation(n['external_axes']['E2'])
        result=dict(plate_id=plate_id,revision=plate['revision'] if plate else None,
                    plate_profile=binding['profile'],profile_binding=binding,
                    identity_status='registered' if plate else 'unregistered_pending_scan',slot=slot,destination=destination,
                    workflow=workflow,geometry=geometry,start=s['pose_mm'],joints=s['joints'],axes=n['external_axes'],
                    continuation=composition,roundtrip=roundtrip,holder_preparation=holder_preparation)
        if chain:result['instrument_chain']=chain
        return result

    def verify(self,spec):
        from hotel_holder_preparation import preparation
        if spec['holder_preparation']!=preparation(spec['axes']['E2']):
            raise TransferError('Holder preparation changed; request a fresh plan.')
        options={'instrument_request':spec['instrument_chain']['request']} if spec.get('instrument_chain') else {}
        fresh=self.preview(spec['plate_id'],spec['slot'],spec['destination'],spec['plate_profile'],spec.get('roundtrip',False),**options)
        for key in ('start','joints','axes'):
            old,new=spec[key],fresh[key]
            if set(old)!=set(new) or any(abs(old[k]-new[k])>.05 for k in old):
                raise TransferError('Starting configuration changed; request a fresh plan.')
            fresh[key]=old
        if bool(fresh['holder_preparation'])==bool(spec['holder_preparation']):
            fresh['holder_preparation']=spec['holder_preparation']
        if fresh!=spec:raise TransferError('Plate or accepted route changed; request a fresh plan.')
        if spec.get('instrument_chain'):
            from composed_instrument_chain import verify
            verify(self.backend,spec['instrument_chain'],agent=self.agent)

    def steps(self,spec):
        steps=[dict(id='retrieve_hotel',label=f"Retrieve slot {spec['slot']} plate and reseat in HOME")]
        if spec.get('holder_preparation'):
            steps.insert(0,dict(id='prepare_home_holder',label=f"Open empty jaws to 28 mm; restore HOME holder from {spec['axes']['E2']:.3f} to 1.77 degrees and verify"))
        if spec['destination']!='HOME':
            steps[-1]['label']+='; verify released holder at 1.77 degrees, correcting small seating drift once if needed'
            destination=spec['destination'];roundtrip=spec.get('roundtrip',False)
            steps += [dict(id='register_barcode',label='Re-center released holder at HOME before barcode pickup; present and register barcode; return and release in HOME'),
                      dict(id=('roundtrip_' if roundtrip else 'deliver_')+destination.lower(),
                           label=(f'Deliver and release at {destination}; retrieve and release in HOME'
                                  if roundtrip else f'Deliver and release at {destination}; return empty to HOME'))]
        if spec.get('instrument_chain'):
            from composed_instrument_chain import steps as instrument_steps
            steps=[s for s in steps if s['id'] in ('prepare_home_holder','retrieve_hotel','register_barcode')]
            if spec.get('continuation') and not any(s['id']=='register_barcode' for s in steps):
                steps.append(dict(id='register_barcode',label='Register the barcode and return/release in HOME'))
            steps+=instrument_steps(spec['instrument_chain'])
        return steps

    def execute_step(self,run,spec,step,prior):
        if spec.get('instrument_chain') and step.startswith('instrument_'):
            from composed_instrument_chain import execute
            return execute(self,run,spec,step,prior)
        if step=='prepare_home_holder':
            if prior is not None or not spec.get('holder_preparation'):raise TransferError('Unbound holder preparation.')
            self.verify(spec)
            from hotel_holder_preparation import execute
            return execute(run,self.backend,spec,self.require)
        if step=='register_barcode' and prior and spec.get('continuation'):
            from hotel_cellvis_handoff import create
            from composed_cellvis_registration import register
            source=create(prior['record'],spec['profile_binding'],spec['continuation']['scanner'])
            return register(run,self.backend,source,spec['plate_id'],self.registry())
        station_step=('roundtrip_' if spec.get('roundtrip',False) else 'deliver_')+spec['destination'].lower()
        if step==station_step and prior and spec['destination']!='HOME':
            from cellvis24_workflow import evidence
            from composed_cellvis_registration import deliver
            if evidence()!=spec['continuation']['acceptance']:raise TransferError('Accepted station evidence changed.')
            options={'station_check':self.station_check} if self.station_check is not None else {}
            return deliver(run,self.backend,prior,spec['continuation']['delivery_steps'],
                           spec['destination'],spec.get('roundtrip',False),**options)
        if step!='retrieve_hotel':raise TransferError('Unbound retrieval step.')
        if spec.get('holder_preparation'):
            from hotel_holder_preparation import verify_receipt
            from calibration_e2 import accepted
            data=verify_receipt(run,spec,prior)
            options={'instrument_request':spec['instrument_chain']['request']} if spec.get('instrument_chain') else {}
            fresh=self.preview(spec['plate_id'],spec['slot'],spec['destination'],spec['plate_profile'],spec.get('roundtrip',False),**options)
            near(fresh['start'],spec['start'],.05)
            if (fresh['holder_preparation'] or not accepted(fresh['axes']['E2']) or abs(fresh['axes']['E1']-28)>.07
                    or any(abs(fresh['joints'][k]-spec['joints'][k])>.05 for k in spec['joints'])
                    or any(abs(fresh['axes'][k]-data['final_native']['external_axes'][k])>.05 for k in fresh['axes'])):
                raise TransferError('Prepared HOME setup changed; no retrieval.')
            if any(fresh[k]!=spec[k] for k in spec if k not in ('start','joints','axes','holder_preparation')):
                raise TransferError('Plate or accepted route changed after holder preparation.')
        else:
            if prior is not None:raise TransferError('Unbound retrieval predecessor.')
            self.verify(spec)
        module,_,_=hotel(spec['slot'])
        if run.stopped():raise TransferError('Stopped before empty jaw preparation.')
        if spec.get('plate_id'):
            self.registry().record_run(spec['plate_id'],run.run_id,'handling','Lacry composed hotel retrieval')
        self.require(self.backend.s.move_gripper(7,5))
        if run.stopped():raise TransferError('Stopped before hotel retrieval.')
        cfg=self.backend.params()
        options={'restore_holder_for_handoff':True} if spec['slot']==1 and spec.get('continuation') else {}
        return module.execute(run,self.backend.s,cfg,module.preview(self.backend.s,cfg),**options)

    @staticmethod
    def require(result):
        if (not isinstance(result,dict) or result.get('ok') is not True or
                result.get('recovered') or result.get('gripper_warning')):
            raise TransferError('Workflow step failed or uncertain; nothing was retried: '+str(result))
        return result
