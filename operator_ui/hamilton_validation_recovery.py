"""Narrow validation-timeout recovery; never replay a Hamilton write."""
from copy import deepcopy
import json
from pathlib import Path
import re
import time

from hamilton_prep import digest
from researcher_teaching import TeachingError
from run_record_io import write_run_record


def is_timeout(error):
    seen=set()
    while isinstance(error,BaseException) and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error,TimeoutError):return True
        error=getattr(error,'__cause__',None) or getattr(error,'reason',None)
    return False


def inspect(agent,run_id):
    """Prove this specific stopped boundary using receipts and native readback."""
    from composed_cellvis_registration import sha
    from composed_instrument_chain import at_home
    from cellvis24_workflow import RUNS,evidence
    from labfacade.approval import plan_hash
    if not isinstance(run_id,str) or not re.fullmatch('[0-9a-f]{32}',run_id):
        raise TeachingError('Use the stopped composed workflow ID.')
    runner=agent.get_runner()
    if runner.active or getattr(runner,'reserved',False) or agent.lab_api.active or agent.review:
        raise TeachingError('Finish the active operation before reconciling validation.')
    owner=agent.workflow_composition;path=owner.folder/(run_id+'.json')
    outer=json.loads(path.read_bytes());spec=outer['plan']['composition']
    hold=owner.folder/'unresolved.json'
    if not hold.exists() or Path(json.loads(hold.read_bytes())['record']).resolve()!=path.resolve():
        raise TeachingError('The unresolved transfer does not match this run.')
    if outer.get('status')!='stopped_or_uncertain' or len(outer.get('steps',[]))<2:
        raise TeachingError('This is not an unresolved instrument phase after completed handling.')
    failed=outer['steps'][-1];last=outer['steps'][-2]
    if (failed['step']!='instrument_hamilton_run' or failed.get('status')!='dispatching' or
            last.get('status')!='completed' or last['step']!='instrument_hamilton_deliver' or
            any(s.get('status')!='completed' for s in outer['steps'][:-1])):
        raise TeachingError('Only validation before the first Hamilton job can be reconciled here.')
    prepared=spec['instrument_chain']['hamilton']
    if prepared.get('mode')!='simulate_execute':raise TeachingError('No approved Hamilton draft binding.')
    author=agent.protocol_authoring;record=author.read(prepared['draft_id']);pid=record.get('protocol_id')
    if record.get('status')!='failed_or_uncertain' or type(pid) is not int:
        raise TeachingError('The draft is not an interrupted native creation.')
    if any(k in record for k in ('simulation_job_id','simulation_result','physical_ticket','execution_binding')):
        raise TeachingError('A simulation or physical run may have started; validation-only recovery is not applicable.')
    h=author.h;marker=h.folder/'active.json';ticket=json.loads(marker.read_bytes())
    if ticket.get('action')!='experiment_simulation' or ticket.get('status') not in ('failed_or_uncertain','uncertain'):
        raise TeachingError('Hamilton has a different unresolved operation.')
    journal=h.folder/(ticket['request_id']+'.jsonl');rows=[json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
    requests=[r['data'] for r in rows if r.get('kind')=='request']
    wanted=dict(method='GET',path=f'protocols/validate/{pid}',body=None)
    if not requests or requests[-1]!=wanted or sum(r==wanted for r in requests)!=1:
        raise TeachingError('The last uncertain request was not one native validation request.')
    allowed={('POST','protocols'),('POST',f'protocols/{pid}/step'),('GET',f'protocols/validate/{pid}')}
    if any((r.get('method'),r.get('path')) not in allowed for r in requests):
        raise TeachingError('The journal contains a request outside protocol creation/validation.')
    if 'timed out' not in ticket.get('error','').lower() and 'timeout' not in ticket.get('error','').lower():
        raise TeachingError('The recorded error is not a validation timeout.')
    predecessor=last['result'];receipt_path=Path(predecessor['record']);receipt=json.loads(receipt_path.read_bytes())
    if (sha(receipt_path)!=predecessor.get('sha256') or receipt.get('status')!='completed' or
            receipt.get('binding')!=plan_hash(spec) or receipt.get('step')!=last['step']):
        raise TeachingError('The completed Hamilton delivery receipt changed.')
    context=receipt['context'];plate_id=context['plate_id']
    if (context.get('plate_location')!='Hamilton' or record.get('plate_id')!=plate_id or
            record.get('experiment_plan_id')!=receipt.get('run_id')):
        raise TeachingError('The draft and delivery plate identities disagree.')
    review=prepared['protocol_review']
    if (any(review.get(k)!=record['spec'].get(k) for k in ('name','deck','tip_site','tip_wells','initial_volumes','pipetting')) or
            review.get('dilution_table')!=record['compiled']['summary']):
        raise TeachingError('Draft settings differ from the approved protocol review.')
    motion_path=Path(context['motion_record']).resolve();motion=json.loads(motion_path.read_bytes())
    if (motion_path.parent.parent!=RUNS.resolve() or sha(motion_path)!=context.get('motion_sha256') or
            motion.get('status')!='experiment_delivery_complete' or motion.get('payload')!='empty' or
            motion['plan']!=context['motion'] or motion['plan']['acceptance_sha256']!=evidence() or
            motion['plan']['steps']!=next(g['delivery'] for g in spec['instrument_chain']['groups'] if g['station']=='Hamilton') or
            len(motion['steps'])!=len(motion['plan']['steps']) or
            any(s.get('status')!='completed' for s in motion['steps'])):
        raise TeachingError('The delivered-plate motion checkpoint is not verified.')
    if any(p.resolve()!=motion_path and p.stat().st_mtime_ns>=motion_path.stat().st_mtime_ns for p in RUNS.glob('*/run.json')):
        raise TeachingError('Later motion supersedes the Hamilton delivery checkpoint.')
    registry=owner.adapter.registry();plate=registry.get(plate_id)
    def check():
        if agent.get_runner().active:raise TeachingError('Another workflow started during reconciliation.')
        at_home(agent.backend,context)
        state=h.status(fresh=True)
        if (not state.get('connected') or state.get('global_state')!='Idle' or not state.get('parked') or
                state.get('run',{}).get('isRunInProgress') is not False or state.get('pending_errors')):
            raise TeachingError('Hamilton must be idle, parked and free of errors for validation reconciliation.')
    check();native=author.validated_readback(record,check)
    if native.get('lastRunDateTime') not in (None,'','0001-01-01T00:00:00'):
        raise TeachingError('Hamilton records a run of this method; validation-only recovery cannot assume unused inventory.')
    if digest(h.settings())!=prepared['settings_hash']:
        raise TeachingError('Hamilton settings changed since the approved draft binding.')
    operations=[c['capability']['operation'] for c in spec['instrument_chain']['request']['composition']['capabilities']]
    index=operations.index('hamilton_protocol')
    check()
    return dict(outer_path=path,outer=outer,outer_hash=sha(path),hold_path=hold,hold_hash=sha(hold),
        draft=record,draft_hash=digest(record),native=native,marker_path=marker,marker_hash=sha(marker),ticket=ticket,
        journal_path=journal,journal_hash=sha(journal),context=context,predecessor=predecessor,
        plate_id=plate_id,registry_revision=plate['revision'],remaining_operations=operations[index:])


def reconcile(agent,run_id):
    """Archive the failure, resolve only proven local holds, and expose a continuation.

    No hardware commands or approval are issued. A stopped run is not resumed;
    the next complete suffix is proposed through the normal workflow planner.
    """
    from composed_cellvis_registration import sha
    h=agent.protocol_authoring.h
    if not h.operation_lock.acquire(False):raise TeachingError('Hamilton is owned by another operation.')
    try:
        facts=inspect(agent,run_id)
        for path,key in ((facts['outer_path'],'outer_hash'),(facts['hold_path'],'hold_hash'),
                         (facts['marker_path'],'marker_hash'),(facts['journal_path'],'journal_hash')):
            if sha(path)!=facts[key]:raise TeachingError('Recovery evidence changed during readback.')
        if digest(agent.protocol_authoring.read(facts['draft']['draft_id']))!=facts['draft_hash']:
            raise TeachingError('Draft changed during readback.')
        folder=agent.workflow_composition.folder/'reconciliations';folder.mkdir(exist_ok=True)
        proof_path=folder/(run_id+'.json')
        proof=dict(kind='hamilton_validation_only',run_id=run_id,observed_at=time.time(),
            original_status=facts['outer']['status'],original_error=facts['outer'].get('error'),
            outer_sha256=facts['outer_hash'],draft_before=facts['draft'],ticket_before=facts['ticket'],
            journal=str(facts['journal_path']),journal_sha256=facts['journal_hash'],
            protocol_id=facts['native']['id'],protocol_hash=digest(facts['native']),
            delivery=facts['predecessor'],plate_id=facts['plate_id'],plate_location='Hamilton',
            remaining_operations=facts['remaining_operations'],no_instrument_run_dispatched=True)
        if proof_path.exists():raise TeachingError('A reconciliation receipt already exists; inspect its saved transaction rather than replacing it.')
        with proof_path.open('x',encoding='utf-8') as stream:json.dump(proof,stream)
        record=deepcopy(facts['draft'])
        record.update(status='created',protocol=facts['native'],protocol_hash=digest(facts['native']),
            validation_phase=dict(status='reconciled_after_stop',record=str(proof_path)),original_error=record.pop('error',''))
        agent.protocol_authoring.save(record)
        outer=deepcopy(facts['outer'])
        outer.update(status='reconciled_before_instrument_run',plate_id=facts['plate_id'],plate_destination='Hamilton',
            validation_reconciliation=dict(record=str(proof_path),sha256=sha(proof_path),observed_at=proof['observed_at']))
        write_run_record(facts['outer_path'],outer)
        registry=agent.workflow_composition.adapter.registry()
        with registry.db() as db:
            db.execute('BEGIN IMMEDIATE');registry._checked(db,facts['plate_id'],facts['registry_revision'])
            db.execute('UPDATE plates SET location=?,location_basis=?,revision=revision+1 WHERE plate_id=?',
                ('Hamilton','verified_workflow_receipt',facts['plate_id']))
            registry._event(db,facts['plate_id'],'validation_reconciliation',str(proof_path),
                dict(location='Hamilton',instrument_run_started=False,operator_acceptance=False))
        # Exact-match deletion only, after durable proof and custody restoration.
        if sha(facts['marker_path'])!=facts['marker_hash'] or sha(facts['hold_path'])!=facts['hold_hash']:
            raise TeachingError('An unresolved hold changed; it was not removed.')
        facts['marker_path'].unlink();facts['hold_path'].unlink()
        with h.lock:h.active=dict(facts['ticket'],status='completed',reconciliation=str(proof_path));h.prompt=None
        return dict(ok=True,reconciled=True,hardware_started=False,plate_id=facts['plate_id'],
            draft_id=record['draft_id'],remaining_operations=facts['remaining_operations'],record=str(proof_path),
            next='Use plan_workflow with these remaining_operations, plate_id and draft_id. Omit source_slot; transport and creation are already completed.')
    finally:h.operation_lock.release()
