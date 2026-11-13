"""Internal receipt adapter for registration inside the console's shared runner."""
import json
import time
from pathlib import Path
from autonomy import TransferError
from scope_step_trial import preflight
from home_hamilton_exchange import native
from run_record_io import write_run_record
from cellvis24_scanner_return import sha as file_sha


def sha(path):return file_sha(Path(path))


class PickupHost:
    """Limited transport for the unchanged pickup algorithm; no connect/start/reset."""
    def __init__(self,backend,run):self.backend=backend;self.run=run
    def check_owner(self):
        if self.run.stopped():raise TransferError('Composed transfer stopped.')
    def native(self):return native(self.backend.s)
    def call(self,path,body=None):
        # Stop remains available when cancellation has already been requested.
        if path=='program' and body=={'action':'stop'}:return self.backend.s.program('stop')
        self.check_owner();s=self.backend.s
        if path=='state':
            return dict(robot=s.status(),sequence=dict(active=True),envelope=dict(
                enabled=s.envelope_enabled,**{k:dict(min=v[0],max=v[1]) for k,v in s.envelope.items()}))
        if path=='robot_params':return self.backend.params()
        if path=='gripper' and body['action']=='move':return s.move_gripper(body['e1'],body['speed'])
        if path=='gripper' and body=={'action':'torque'}:return s.torque_report()
        if path=='move':return s.move_cartesian(**body)
        raise TransferError('Unsupported internal pickup command: '+path)


def delivery_steps(destination='Squid', roundtrip=False):
    from cellvis24_workflow import compile_steps
    if destination not in ('Squid','Hamilton') or type(roundtrip) is not bool:
        raise TransferError('Choose Squid or Hamilton and a boolean roundtrip option.')
    options={'recorded_hamilton_variant':'opposite3'} if destination=='Hamilton' else {}
    steps=compile_steps([destination.lower()],1,**options)
    cuts=[i for i,s in enumerate(steps) if s['label']=='Check destination before retrieval']
    if len(cuts)!=1 or not cuts[0] or steps[cuts[0]-1]['label']!='Empty HOME clearance':
        raise TransferError('Accepted station delivery checkpoint changed.')
    return steps if roundtrip else steps[:cuts[0]]


def register(run,backend,source,expected_plate_id,registry,*,present=None,scan=None,return_home=None):
    """At most five ordinary no-reads per side. Errors never count as no-reads."""
    import barcode_opposite_side_trial as trial
    import barcode_opposite_pickup as pickup
    import barcode_opposite_transport as transport
    from barcode_scanner_cli import scan_once
    from run_dna_plate_registration import ROOT
    from hotel_cellvis_handoff import validate_source
    source=Path(source).resolve();validate_source(source,json.loads(source.read_bytes()))
    output=source.with_name('registration.json')
    record=dict(status='running',source=str(source),source_sha256=sha(source),
                expected_plate_id=expected_plate_id,sides=[],automatic_retries=False)
    with output.open('x',encoding='utf-8') as stream:json.dump(record,stream)
    def save():write_run_record(output,record)
    def require(value):
        if value.get('ok') is not True or value.get('recovered') or value.get('gripper_warning'):
            raise TransferError('Registration phase uncertain; no retry: '+str(value))
        return value
    def stopped():
        if run.stopped():raise TransferError('Stopped during barcode registration.')
        preflight(backend.s)
    def default_present(current,angle):
        stopped();p=trial.plan(backend.s,backend.params(),current,angle,prepare_original=True)
        result=require(trial.execute(run,backend.s,backend.params(),p))
        held=pickup.run(result['record'],host=PickupHost(backend,run))
        stopped();p=transport.plan(backend.s,backend.params(),held,'scanner',scanner_z=163.76)
        require(transport.execute(run,backend.s,backend.params(),p))
        return held
    def default_return(held):
        for phase in ('return_home','release_restore'):
            stopped();p=transport.plan(backend.s,backend.params(),held,phase)
            result=require(transport.execute(run,backend.s,backend.params(),p))
        return result['record']
    present=present or default_present;return_home=return_home or default_return
    scan=scan or (lambda:scan_once('192.168.1.10',1024,'192.168.1.15',5.,ROOT/'operator_ui/reports/barcode_scanner'))
    current=source
    try:
        for angle in (1.77,181.77):
            stopped();side=dict(angle=angle,status='presenting',scans=[]);record['sides'].append(side);save()
            held=present(current,angle);side.update(pickup=str(held),status='scanning');save()
            decoded=None
            for index in range(5):
                stopped();value,receipt=scan()
                side['scans'].append(dict(receipt=str(receipt),sha256=sha(receipt),result=value));save()
                if value.get('stop_error') or value.get('result') not in ('decoded','no_read'):
                    raise TransferError('Scanner failed or uncertain; no retry: '+str(value.get('result')))
                if value['result']=='decoded':
                    saved=value.get('plate_registry',{})
                    if saved.get('saved') is not True or not saved.get('plate_id'):
                        raise TransferError('Barcode decoded but registration was not saved.')
                    decoded=saved['plate_id'];plate=registry.get(decoded)
                    record.update(plate_id=decoded,scan_receipt=str(receipt),scan_sha256=sha(receipt));save()
                    registry.record_run(decoded,output.parent.name,'handling',str(output))
                    if expected_plate_id is not None and decoded!=expected_plate_id:
                        raise TransferError('Scanned plate identity differs from the approved expected barcode; station handling blocked.')
                    profile=plate.get('metadata',{}).get('plate_type')
                    if profile and profile!='Cellvis P24-1.5H-N':
                        raise TransferError('Scanned plate profile conflicts with the approved Cellvis profile.')
                    break
                if index<4:time.sleep(1)
            stopped();current=return_home(held)
            side.update(status='decoded' if decoded else 'no_read',home_receipt=str(current));save()
            if decoded:
                record.update(status='registered_HOME_released',home_receipt=str(current),home_sha256=sha(current))
                return dict(ok=True,record=str(output),plate_id=decoded,home_receipt=str(current))
        raise TransferError('No barcode after five triggers on each side. Plate returned to HOME; station delivery blocked.')
    except BaseException as error:
        record.update(status='blocked_or_uncertain',error=str(error));raise
    finally:record['finished_at']=time.time();save()


def deliver(run,backend,prior,bound_steps,destination='Squid',roundtrip=False,*,station_check=None):
    from cellvis24_workflow import plan,execute_checked_steps,validate_steps
    p=Path(prior['record']);record=json.loads(p.read_bytes())
    if (record.get('status')!='registered_HOME_released' or record.get('plate_id')!=prior.get('plate_id')
            or record.get('home_receipt')!=prior.get('home_receipt')
            or sha(record['home_receipt'])!=record['home_sha256']
            or sha(record['scan_receipt'])!=record['scan_sha256']
            or not 0<=time.time()-record['finished_at']<=1800):
        raise TransferError('Fresh matching barcode registration and HOME release required.')
    scan=json.loads(Path(record['scan_receipt']).read_bytes())
    if (scan.get('result')!='decoded' or scan.get('plate_registry',{}).get('saved') is not True
            or scan['plate_registry'].get('plate_id')!=record['plate_id']):
        raise TransferError('Saved scan does not identify this plate.')
    if bound_steps!=delivery_steps(destination,roundtrip):raise TransferError('Station handling changed after approval.')
    options={'recorded_hamilton_variant':'opposite3'} if destination=='Hamilton' else {}
    checks={'station_check':station_check} if station_check is not None else {}
    fresh=plan(backend.s,backend.params(),[destination.lower()],1,source=record['home_receipt'],**options,**checks)
    fresh['steps']=bound_steps
    validate_steps(bound_steps,preflight(backend.s),backend.params(),backend.s.envelope)
    result=execute_checked_steps(run,backend.s,backend.params(),fresh,fresh,
        getattr(backend,'cam',None),ends_held=False,
        receipt_status='completed' if roundtrip else 'experiment_delivery_complete',**checks)
    return dict(result,plate_id=record['plate_id'],registration=str(p),
                plate_location='HOME' if roundtrip else destination)
