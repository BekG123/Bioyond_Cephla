"""Complete one accepted handling cycle from the verified Squid overhead point."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
import execute_continuous_squid_return_20261103 as travel
import release_empty_home_20261103 as release
import pickup_squid_home_20261103 as pickup
from full_calibration_handling_20261103 import invoke
from squid_adapter import native_command, squid_process
from capture_squid_approach_20261103 import FOLDER, sha
from proof_lift_plate import api, near, write
from prepare_squid_destination import validate

SOURCE=FOLDER/'closed_claw_roundtrip_plan_20261103.json'
SHA='4eb1eaef27adacfd0116b3376bc6765896aba0dbd0c05ac7429e4ff857352c81'
PARENT=FOLDER/'loaded_trial_1de0fe5f61464570ae5f2dcb15089fe0.json'
PARENT_SHA='fbf226b80ac3f3f595876099da49c1606f98d9e14a0a5958d815c07b7d3fcbdb'
AUTH=('Operator confirmed prior calibration and overhead transfer retained plate level and secure, '
      'then requested unchanged accepted drop-off, empty Home, Squid pickup and loaded Home. '
      'Existing clearance and E-stop supervision retained; no inter-step chat approval, '
      'no imaging, stage movement, retries, fault reset or controller startup authorized.')

SQUID_SOFTWARE=Path('C:/Users/Cephla/Desktop/squid-latest/software')
SQUID_FILES={
    'configuration_HCS_v2.ini':'f6c3ee6896124e99126c57bdfdf09022119e603b8948d32cf0b184ccb3f157ae',
    'control/_def.py':'f6e4f8423684dc7017829aa786ebfa03659fe7d8572a9abb40c8b3d6e881b482',
    'squid/stage/utils.py':'2d3fd2cfba8650bc20157014a7b34806dfd8d1eb1953bcfabe0c480eb28ee42a',
}

def check_loading_position(position):
    # This configuration has objective focus Z, no sample Z lift. Native loading
    # retracts the objective to 0.100 mm; old 0.064 mm is not a holder height.
    for key in ('x_mm','y_mm','z_mm'):
        if type(position.get(key)) not in (float,int) or not math.isfinite(position[key]):
            raise RuntimeError('Squid position feedback unavailable')
    if any(abs(position[key]-.5000625)>.020 for key in ('x_mm','y_mm')):
        raise RuntimeError('Squid holder XY differs from the taught loading position')
    if not 0 <= position['z_mm'] <= .101:
        raise RuntimeError('Squid objective is not in its retracted loading range')

def stage_ready():
    owner=squid_process()
    if (owner['pid']!=1096 or owner['stage_simulated'] is not False
        or Path(owner['software'])!=SQUID_SOFTWARE):
        raise RuntimeError('Squid session changed; review its loading configuration')
    if any(sha(SQUID_SOFTWARE/name)!=digest for name,digest in SQUID_FILES.items()):
        raise RuntimeError('Reviewed objective-focus/no-lift configuration changed')
    acquisition=native_command('get_acquisition_status')
    if acquisition.get('in_progress') is not False or acquisition.get('status')!='idle':
        raise RuntimeError('Squid must remain idle for plate handling')
    position=native_command('get_position')
    check_loading_position(position)
    return dict(owner=owner,acquisition=acquisition,position=position,
        policy='Taught holder XY within 0.020 mm; objective retracted at Z <= 0.101 mm; no sample lift',
        operator_context='Operator confirmed holder at loading and explained saved focus Z is not holder height',
        reviewed_files=SQUID_FILES)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if sha(SOURCE)!=SHA or sha(PARENT)!=PARENT_SHA:
        raise RuntimeError('Accepted route or current overhead receipt changed')
    parent=json.loads(PARENT.read_bytes())
    if parent['status']!='loaded_above_squid_awaiting_operator_teaching':
        raise RuntimeError('Current overhead completion required')
    plan=json.loads(SOURCE.read_bytes());route=plan['routes']['from_capture']
    state=api('state');r=state['robot'];seq=api('seq')
    if (not r.get('connected') or not r.get('ok') or r.get('errors') or not r.get('enabled')
        or r['program_state']['state']!='running' or r['control_mode']['mode']!='auto'
        or seq['active'] or state['sequence']['active']):
        raise RuntimeError('Healthy idle running Auto required; no recovery')
    if api('researcher/api/status')['hand_guiding']['state']!='off':
        raise RuntimeError('Hand guiding must be off')
    near(r['pose_mm'],route[3],.05)
    near(r['pose_mm'],parent['final_robot']['pose_mm'],.05)
    if abs(r['external_axes']['E1']-parent['final_robot']['external_axes']['E1'])>.1:
        raise RuntimeError('Grip changed after accepted overhead arrival')
    env={k:[state['envelope'][k]['min'],state['envelope'][k]['max']] for k in ('X','Y','Z')}
    if not state['envelope']['enabled'] or env!=plan['envelope'] or api('robot_params')!=plan['cfg']:
        raise RuntimeError('Reviewed settings changed')
    # Current overhead -> seat -> empty Home -> pickup -> loaded Home.
    geometry=[r['pose_mm'],*route[4:],*route[1:]]
    checked=validate(geometry,r['joints'],plan['cfg'],env)
    print(json.dumps(dict(validated=True,execute=args.execute,seat=route[4],
        release_e1=7,pickup_e1=3.9,final_home=route[-1],
        stage_check='Required before execution and each instrument interaction')),flush=True)
    if not args.execute:return
    squid=stage_ready()
    out=FOLDER/('finish_handling_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir();drop=out/'dropoff';drop.mkdir();pick=out/'pickup';pick.mkdir()
    record=dict(status='started',at=time.time(),authorization=AUTH,source_sha256=SHA,
        overhead_receipt=str(PARENT),overhead_sha256=PARENT_SHA,initial_state=state,
        initial_squid=squid,validation=checked,events=[],automatic_retries=False)
    report=out/'run.json'
    def phase(name,**details):
        record['phase']=name;record['events'].append(dict(at=time.time(),phase=name,**details))
        write(report,record);print(json.dumps(dict(phase=name,**details)),flush=True)
    try:
        descent=deepcopy(plan)
        descent.update(routes={'from_capture':route[3:5]},leg_speeds=[5],
            completion_status='at_squid_awaiting_supported_plate_confirmation',operator_intent=AUTH)
        travel.PLAN=drop/'dropoff_approach_plan_20261103.json'
        travel.OUTPUT=drop/'dropoff_approach_trial_20261103.json'
        write(travel.PLAN,descent);travel.SHA=sha(travel.PLAN)
        prior_argv=__import__('sys').argv[:]
        try:
            __import__('sys').argv=[travel.__file__]
            travel.main(expected_speeds=(5,),vertical_legs=(0,))
            phase('remaining_descent_started')
            __import__('sys').argv=[travel.__file__,'--execute']
            travel.main(expected_speeds=(5,),vertical_legs=(0,))
        finally:__import__('sys').argv=prior_argv
        stage_ready();phase('release_and_empty_home_started')
        invoke(release,['--execute'],drop,AUTH)
        release_record=drop/'release_empty_home_20261103.json'
        if json.loads(release_record.read_bytes())['status']!='release_and_empty_home_completed_pending_operator_assessment':
            raise RuntimeError('Release and empty Home completion missing')
        near(api('state')['robot']['pose_mm'],route[0],.1)
        stage_ready();phase('pickup_and_loaded_home_started')
        invoke(pickup,[],pick,AUTH)
        invoke(pickup,['--execute'],pick,AUTH)
        picked=pick/'pickup_home_trial_20261103.json'
        if json.loads(picked.read_bytes())['status']!='pickup_and_home_completed_pending_operator_assessment':
            raise RuntimeError('Pickup and loaded Home completion missing')
        final=api('state');near(final['robot']['pose_mm'],route[0],.1)
        record.update(status='handling_completed_pending_operator_assessment',final_state=final,
            release_sha256=sha(release_record),pickup_sha256=sha(picked))
        phase('loaded_home_completed')
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        try:record['stop_response']=api('program',dict(action='stop'))
        except Exception as stop_error:record['stop_error']=str(stop_error)
        raise
    finally:
        record['finished_at']=time.time();write(report,record)
        print(json.dumps(dict(status=record['status'],report=str(report))),flush=True)

if __name__=='__main__':main()
