"""Second and final two-sided registration pass, then authorized station handling.

Retries only completed scanner no-read outcomes. Hardware faults, timeouts,
uncertain commands and registration errors stop; they are never retried.
Uses the accepted unchanged Cellvis setup and standing operator supervision.
Calibration runs once before registration. A retry reuses its checked pickup
geometry; missing or stale evidence stops rather than launching calibration.
"""
import argparse
import json
import time
from pathlib import Path
from run_record_io import write_run_record
from cellvis24_scanner_return import sha
from run_dna_plate_registration import scan_until_decoded

MAX_PASSES=2


def scan_register():
    from plate_registry import PlateRegistry
    try:scan,receipt,count=scan_until_decoded(5,1.)
    except RuntimeError as e:
        if str(e)=='No read after 5 triggers; plate still held at the scanner.':
            return dict(status='no_read',triggers=5)
        raise
    saved=scan.get('plate_registry',{})
    if saved.get('saved') is not True:raise RuntimeError('Decoded barcode was not saved to registry.')
    plate=PlateRegistry().update(saved['plate_id'],saved['revision'],dict(experiment='DNA reagents'),
        'User-stated intended purpose, not measured contents; scanner receipt '+str(receipt))
    return dict(status='registered',triggers=count,plate_id=plate['plate_id'],receipt=str(receipt))


class Live:
    # Operator accepted the lower height after first-trigger decode; retain
    # explicit None for historical nominal-height workflows and receipts.
    def __init__(self,scanner_z=163.76):
        if scanner_z not in (None,189.16,163.76):raise ValueError('Unknown scanner height.')
        self.scanner_z=scanner_z

    def original_scanner(self,source):
        return self.pickup_scanner(source,1.77)

    def original_home(self,source):
        return self.opposite_home(source)

    def opposite_scanner(self,source):
        return self.pickup_scanner(source,181.77)

    def pickup_scanner(self,source,target):
        from run_cellvis24_scanner_hamilton import reconnect,api,dispatch
        from barcode_opposite_pickup import run
        reconnect()
        p=api('developer/api/barcode-opposite-trial/preview',{'source':str(source),'target':target})['plan']
        trial=dispatch('developer/api/barcode-opposite-trial/start',dict(plan=p,plate_seated=True,
            empty_gripper=True,rotation_and_approach_clear=True,estop_supervised=True),'barcode_opposite_trial',180)
        pickup=run(trial['record'],alignment_confirmed=True)
        scan=self.transport(pickup,'scanner')
        return str(pickup),dict(trial=trial,pickup=str(pickup),scanner=scan,
            observation_basis='Previously accepted unchanged pickup setup; no fresh visual observation claimed.')

    def transport(self,source,phase):
        from run_cellvis24_scanner_hamilton import reconnect,api,dispatch
        reconnect()
        request=dict(source=str(source),phase=phase)
        if phase=='scanner' and self.scanner_z is not None:request['scanner_z']=self.scanner_z
        p=api('developer/api/barcode-opposite-transport/preview',request)['plan']
        b=dict(plan=p,retention_confirmed=True,route_clear=True,estop_supervised=True)
        if phase=='release_restore':b['plate_supported']=True
        return dispatch('developer/api/barcode-opposite-transport/start',b,'barcode_opposite_transport',180)

    def opposite_home(self,source):
        home=self.transport(source,'return_home');release=self.transport(source,'release_restore')
        return release['record'],dict(home=home,release=release)

    def stations(self,source,plate_id):
        from run_cellvis24_scanner_hamilton import reconnect,api,dispatch
        from plate_registry import PlateRegistry
        reconnect()
        p=api('developer/api/cellvis24-workflow/preview',dict(stations=['hamilton','squid'],cycles=1,
            source=str(source),full_calibration=False,recorded_hamilton_variant='opposite3'))['plan']
        result=dispatch('developer/api/cellvis24-workflow/start',dict(plan=p,ready=True,path_clear=True,
            setup_confirmed=True,recorded_clearance_confirmed=True),'cellvis24_workflow',600)
        PlateRegistry().record_run(plate_id,str(result['record']),'completed','retry_dna_registration')
        return result


def run_second_pass(prior_summary,live=None,scan=scan_register,resume_before_scan=None):
    prior_summary=Path(prior_summary).resolve();prior=json.loads(prior_summary.read_bytes())
    if (prior.get('status')!='both_sides_no_read_plate_released_HOME_holder_restored' or
        prior.get('registration_complete') is not False or prior.get('scan_triggers_per_side')!=5):
        raise RuntimeError('Completed first no-read pass with released/restored HOME required.')
    for filename,digest in prior['sources'].items():
        if sha(Path(filename))!=digest:raise RuntimeError('Prior pass evidence changed.')
    # The previous pass must really have tried both sides, including the second
    # scanner record; a motion/transport error is never a retryable no-read.
    side=json.loads(prior_summary.with_name('registration.json').read_bytes())
    if side.get('status')!='no_read' or side.get('max_triggers')!=5:
        raise RuntimeError('Second-side normal no-read evidence required.')
    output=prior_summary.with_name('registration_pass_2.json')
    resumed=None
    if resume_before_scan is not None:
        # Explicit operator-requested continuation of the reviewed wrapper bug,
        # not a retry of a gripper, transport, or scanner command.
        failed=json.loads(output.read_bytes());evidence=Path(resume_before_scan).resolve()
        failure=json.loads(evidence.read_bytes());steps=failure.get('steps',[])
        if (failed.get('status')!='stopped_or_uncertain' or failed.get('steps')!=[] or
            failed.get('registration_complete') or failed.get('station_sequence_started') or
            failure.get('status')!='stopped_or_uncertain' or
            failure.get('error')!='Stationary plate observations disagree; no alignment.' or
            [(x.get('kind'),x.get('status')) for x in steps]!=[('queue','completed'),('vision','checking')] or
            not failed['at']<=failure['at']<=failure['finished_at']<=failed['finished_at']):
            raise RuntimeError('Resume requires the reviewed calibration-only stop before pickup or scanning.')
        resumed=dict(stopped_pass=str(output),stopped_pass_sha256=sha(output),
                     calibration_failure=str(evidence),calibration_failure_sha256=sha(evidence),
                     authorization='User explicitly requested scanner workflow retry after review; no calibration.')
        output=prior_summary.with_name('registration_pass_2_resumed.json')
    record=dict(status='starting',at=time.time(),pass_number=2,max_passes=MAX_PASSES,
        prior=str(prior_summary),prior_sha256=sha(prior_summary),steps=[],
        purpose='DNA reagents',registration_complete=False,station_sequence_started=False,
        calibration_runs=0,calibration_policy='reuse_accepted_session_geometry_no_automatic_recalibration',
        no_read_retry_authorized=True,fault_retries=False,
        observation_basis='Standing authorization for unchanged previously accepted setup; no new inspection claimed.')
    if resumed:record['resumed_before_scanning']=resumed
    with output.open('x') as f:json.dump(record,f)
    def save():write_run_record(output,record)
    def log(phase,result):record['steps'].append(dict(phase=phase,result=result));save()
    live=live or Live()
    try:
        ident,result=live.original_scanner(prior_summary.with_name('release_restore.json'));log('original_scanner',result)
        registration=scan();log('original_scan',registration)
        source,result=live.original_home(ident);log('original_return_release',result)
        if registration['status']=='no_read':
            pickup,result=live.opposite_scanner(source);log('opposite_scanner',result)
            registration=scan();log('opposite_scan',registration)
            source,result=live.opposite_home(pickup);log('opposite_return_release_restore',result)
        if registration['status']=='registered':
            record.update(registration_complete=True,plate_id=registration['plate_id'],station_sequence_started=True);save()
            log('hamilton_squid_cycle',live.stations(source,registration['plate_id']))
            record['status']='registered_and_station_cycle_completed_operator_retention_pending'
        else:record['status']='two_pass_limit_reached_no_barcode_plate_released_HOME'
    except BaseException as e:
        record.update(status='stopped_or_uncertain',error=str(e));raise
    finally:
        record['finished_at']=time.time();save()
        print(json.dumps(dict(status=record['status'],record=str(output))),flush=True)
    return record


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prior-summary',required=True,type=Path)
    p.add_argument('--execute',action='store_true')
    p.add_argument('--resume-before-scan',type=Path,help='Explicitly reviewed calibration-only failure receipt; preserves the stopped attempt and resumes pass2 once.')
    a=p.parse_args()
    if a.execute:run_second_pass(a.prior_summary,resume_before_scan=a.resume_before_scan)
    else:print(json.dumps(dict(motion_started=False,pass_number=2,max_passes=2,triggers_per_side=5,calibration_runs=0,
        order=['original side','opposite side if no read','restore HOME','Hamilton/Squid only after registration'])))
