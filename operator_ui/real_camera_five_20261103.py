"""One authorized drop-off, five real frames, verified loading return, pickup.

Default prepares immutable experiment inputs without moving hardware.
--execute performs the single attempt; receipts prevent automatic replay.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time
import yaml

from proof_lift_plate import api, near, write
from squid_adapter import SquidAdapter, native_command
from squid_execution import SquidExecution, digest, at_position
from squid_bridge.imaging_lifecycle import imaging_target
import dropoff_approach_20261103 as approach
import release_empty_home_20261103 as release
import pickup_squid_home_20261103 as pickup

ROOT = Path(__file__).resolve().parent
OUT = ROOT/'reports/squid_48well_approach/real_camera_five_20261103'
LOADING = dict(x_mm=0.5000625, y_mm=0.5000625, z_mm=0.063984375)
HOME = dict(X=289.97, Y=62.63, Z=248.02, Rz=-3.88)
AUTH = ('Operator requested one drop-off, five actual-camera imaging passes, then pickup/Home; '
        'confirmed loading position and clearance; delegated imaging-location selection. '
        '48-well plate retained; 24-well GUI format is not used for well-grid navigation. '
        'No autofocus; retracted Z retained, optical focus not claimed.')


def arm_home():
    state = api('state')
    if not state['robot'].get('connected'):
        api('connect', {'ip':'192.168.201.220'})
        state = api('state')
    r = state['robot']
    if (not r.get('ok') or r.get('errors') or not r.get('enabled')
            or r['control_mode']['mode'] != 'auto'
            or r['program_state']['state'] != 'running' or state['sequence']['active']):
        raise RuntimeError('Arm must be healthy, idle and already running; no reset/recovery.')
    near(r['pose_mm'], HOME, .1)
    return state


def prepare():
    if (OUT/'plan.json').exists():
        raise RuntimeError('Prepared already; inspect existing plan rather than overwrite it.')
    arm_home()
    adapter = SquidAdapter(background=False)
    state = adapter.connect()
    if state['simulation'] or state.get('stage_simulated') is not False or state['status'] not in ('idle','historical','completed'):
        raise RuntimeError('Idle physical camera and stage required.')
    bridge = native_command('get_stage_reference')
    if bridge.get('imaging_lifecycle_version') != 1 or bridge['controller_serial'] != '12769210':
        raise RuntimeError('Verified lifecycle bridge/controller required.')
    OUT.mkdir(parents=True, exist_ok=True)
    reference_path = ROOT/'squid_stage_reference.json'
    old_reference = json.loads(reference_path.read_text())
    write(OUT/'previous_stage_reference.json', old_reference)
    reference = dict(schema_version=1, controller_serial='12769210', stage_simulated=False,
        dropoff=LOADING, operator_confirmed=True, accepted_for_robot_loading=True,
        stage_return_verified=False, units='Squid stage millimeters, not robot TCP',
        operator_acceptance='2026-11-03: operator confirmed current loading position matches successful robot drop-off and stage clearance.',
        source='Live get_position before restarting Squid; current session confirmation.',
        previous_reference_sha256=bridge['reference_hash'],
        previous_reference_archive=str(OUT/'previous_stage_reference.json'))
    write(reference_path, reference)
    bridge = native_command('get_stage_reference')
    at_position(bridge['dropoff'], LOADING)
    # Use legacy YAML structure only, replacing optics, position, count and plate metadata.
    legacy = json.loads((ROOT/'squid_protocols.selection.json').read_text())
    settings = yaml.safe_load(legacy['plan']['profile']['captured_yaml'])
    settings['objective'] = dict(name='10x', camera_binning=[1,1])
    settings['sample'] = dict(wellplate_format='24 well plate')
    settings['plate'] = dict(num_rows=4, num_cols=6)
    settings['acquisition']['xy_mode'] = 'Manual'
    settings['flexible_scan']['positions'] = [dict(name='single_test_site',
        center_mm=[24.55,23.01], fovs=[[24.55,23.01,LOADING['z_mm']]])]
    settings['z_stack'].update(nz=1,z_range_mm=[LOADING['z_mm'],LOADING['z_mm']])
    settings['time_series'] = dict(delta_t_s=2.0, nt=5)
    settings['autofocus'] = dict(contrast_af=False,laser_af=False)
    settings['channels'][0]['camera_settings'].update(pixel_format='MONO8')
    text = yaml.safe_dump(settings,sort_keys=True)
    (OUT/'requested_acquisition.yaml').write_text(text,encoding='utf-8')
    profile = dict(label='Five real-camera frames at one explicit site',simulation=False,
        stage_simulated=False,camera_simulated=False,stage_controller_serial='12769210',
        command='run_acquisition_from_yaml',params={'yaml_path':str(OUT/'requested_acquisition.yaml')},
        timeout_s=180,loading_command='return_to_recorded_dropoff',loading_position=LOADING,
        return_waypoints=[])
    write(OUT/'protocol.json',dict(default='real_five',profiles={'real_five':profile}))
    execution = SquidExecution(adapter,config=OUT/'protocol.json')
    configured = execution.profile()
    profile = deepcopy(configured)
    profile.update(captured_yaml=text,params={'settings_sha256':hashlib.sha256(text.encode()).hexdigest()},
        loading_reference_hash=bridge['reference_hash'],imaging_lifecycle_version=1,
        scan_entry=imaging_target(text,bridge['scan_limits']),
        selected_settings=dict(fovs=1,nz=1,nt=5,total_images=5,channels=['BF LED matrix full']))
    plan = dict(profile=profile,profile_hash=digest(profile),configured_hash=digest(configured),
        session=state['session'],loading_position=LOADING,simulation=False,stage_simulated=False)
    write(OUT/'plan.json',plan)
    write(OUT/'preflight.json',dict(authorization=AUTH,robot=arm_home(),squid=state,
        bridge=bridge,plan_sha256=digest(plan),hardware_motion_started=False))
    print(json.dumps(dict(prepared=True,plan=str(OUT/'plan.json'),site=profile['scan_entry'])),flush=True)


def execute():
    record_path = OUT/'run.json'
    if record_path.exists():
        raise RuntimeError('Already attempted; no automatic replay.')
    plan=json.loads((OUT/'plan.json').read_text())
    preflight=json.loads((OUT/'preflight.json').read_text())
    if digest(plan)!=preflight['plan_sha256']:
        raise RuntimeError('Prepared plan changed.')
    adapter=SquidAdapter(background=False)
    adapter.connect()
    execution=SquidExecution(adapter,config=OUT/'protocol.json')
    execution.verify(plan,check_position=False,check_selection=False)
    state=arm_home()
    if abs(state['robot']['external_axes']['E1']-3.9)>.15:
        raise RuntimeError('Unexpected initial grip; no movement.')
    record=dict(status='running',phase='prepare_loading',started_at=time.time(),authorization=AUTH)
    write(record_path,record)
    def phase(name):
        record['phase']=name
        write(record_path,record)
        print(name,flush=True)
    def stopped():
        arm_home()
        return False
    def save_ticket(ticket):
        write(OUT/'imaging_ticket.json',ticket)
    original=sys.argv[:]
    try:
        execution.prepare_loading(plan,stopped,arm_home)
        for _ in range(3):
            at_position(native_command('get_position'),LOADING)
            time.sleep(.25)
        record['loading_verified']=native_command('get_position')
        phase('validate_robot_route')
        sys.argv=[__file__]
        approach.main(OUT)
        phase('dropoff')
        execution.verify(plan,check_selection=False)
        sys.argv=[__file__,'--execute']
        approach.main(OUT)
        release.main(OUT,authorization=AUTH)
        phase('scan_entry')
        execution.prepare_imaging(plan,stopped,arm_home)
        phase('five_real_images')
        ticket=execution.start(plan,OUT,save_ticket,stopped)
        if ticket['response'].get('total_images')!=5:
            execution.abort_owned(plan,ticket,save_ticket)
            raise RuntimeError('Acquisition did not acknowledge exactly five images.')
        execution.wait(plan,ticket,save_ticket,stopped,lambda state: None)
        phase('restore_loading')
        execution.restore_loading(plan,ticket,save_ticket,stopped,arm_home)
        for _ in range(3):
            at_position(native_command('get_position'),LOADING)
            time.sleep(.25)
        phase('pickup_and_home')
        execution.verify(plan,check_selection=False)
        pickup.main(OUT,authorization=AUTH)
        record.update(status='completed_pending_operator_assessment',final_robot=arm_home(),
            final_squid=native_command('get_position'),imaging_run_id=ticket['run_id'])
    except Exception as error:
        record.update(status='stopped_or_failed',error=str(error))
        raise
    finally:
        sys.argv=original
        record['finished_at']=time.time()
        write(record_path,record)
        print(json.dumps(record),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    execute() if args.execute else prepare()
