"""Fresh staged integration of accepted handling, dry dispensing and five images.

prepare only reads instruments and saves a plan. deliver performs the accepted
Hamilton drop-off, then stops for deck registration review before pipetting.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time
import cv2
import numpy as np
from proof_lift_plate import api, near, write
import integrated_dry_mock_20261110 as mock
import hamilton_squid_full_repeat03_20261109 as h
import station_handling_five_20261110 as handling
import queued_hamilton_squid_five_20261110 as checks
from squid_adapter import SquidAdapter,native_command
from squid_execution import SquidExecution,digest,at_position
from squid_bridge.imaging_lifecycle import imaging_target
from hamilton_plate_offset import FALCON48,detect_grid,check_rim

ROOT=Path(__file__).resolve().parent
OUT=mock.OUT/'workflow'
HOME=dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88)
AUTH=('Operator requested one three-machine physical dry mock using the accepted handling routes; '
      'empty Cellvis24 source at site2 A1, transported Falcon48 destination at site4 A1-A6, '
      'six fresh 300uL tips site7 A1-A6; five real brightfield images at prior saved single site. '
      'Standing route clearance, empty supporting holders, hands clear, E-stop supervision. '
      'No actual reagent, PCR chemistry or automatic motion retries.')

def held_home():
    s=arm_home()
    if mock.TIP_SITE==6:
        recovery=json.loads((mock.OUT/'recovery_home_retry01.json').read_bytes())
        assert recovery['status']=='completed'
        expected=recovery['final_robot']['external_axes']['E1']
        if abs(s['robot']['external_axes']['E1']-expected)>.05:
            raise RuntimeError('Jaw changed since operator-confirmed loaded Home recovery')
    else:checks.ready()
    return s

def arm_home():
    s=api('state')
    if not s['robot'].get('connected'):
        if s['sequence']['active']:raise RuntimeError('Disconnected during active motion')
        if not api('connect',dict(ip='192.168.201.220')).get('ok'):raise RuntimeError('Connect failed')
    s=api('state');r=s['robot']
    if (not r.get('ok') or r.get('errors') or not r.get('enabled') or s['sequence']['active']
        or r['program_state']['state']!='running' or r['control_mode']['mode']!='auto'):
        raise RuntimeError('Healthy running idle Auto required; no reset or startup')
    near(r['pose_mm'],HOME,.1)
    if api('researcher/api/status')['hand_guiding']['state']!='off':raise RuntimeError('Hand-guiding active')
    if api('researcher/api/lacry/state')['running']['active']:raise RuntimeError('Lacry workflow active')
    return s

def prepare():
    if OUT.exists():raise RuntimeError('Prepared already; preserve plan')
    state=held_home()
    adapter=SquidAdapter(background=False);squid=adapter.connect()
    if squid['simulation'] or squid['stage_simulated'] is not False or squid['status'] not in ('idle','historical','completed'):
        raise RuntimeError('Idle physical Squid required')
    bridge=native_command('get_stage_reference')
    if bridge['controller_serial']!='12769210' or bridge['imaging_lifecycle_version']!=1:raise RuntimeError('Squid identity/lifecycle mismatch')
    old=json.loads((ROOT/'reports/squid_48well_approach/real_camera_five_20261103/plan.json').read_bytes())
    at_position(bridge['dropoff'],old['loading_position'])
    text=old['profile']['captured_yaml']
    OUT.mkdir()
    (OUT/'requested_acquisition.yaml').write_text(text,encoding='utf-8')
    configured=deepcopy(old['profile'])
    for key in ('captured_yaml','loading_reference_hash','imaging_lifecycle_version','scan_entry','selected_settings','id','yaml_sha256'):
        configured.pop(key,None)
    configured['params']=dict(yaml_path=str(OUT/'requested_acquisition.yaml'))
    mock.save(OUT/'squid_protocol.json',dict(default='five_brightfield',profiles={'five_brightfield':configured}))
    engine=SquidExecution(adapter,config=OUT/'squid_protocol.json')
    configured=engine.profile();profile=deepcopy(configured)
    profile.update(captured_yaml=text,params=dict(settings_sha256=hashlib.sha256(text.encode()).hexdigest()),
        loading_reference_hash=bridge['reference_hash'],imaging_lifecycle_version=1,
        scan_entry=imaging_target(text,bridge['scan_limits']),selected_settings=old['profile']['selected_settings'])
    plan=dict(profile=profile,profile_hash=digest(profile),configured_hash=digest(configured),
        session=squid['session'],loading_position=bridge['dropoff'],simulation=False,stage_simulated=False)
    engine.verify(plan,check_position=False,check_selection=False)
    mock.save(OUT/'squid_plan.json',plan)
    mock.save(OUT/'preflight.json',dict(authorization=AUTH,initial_state=state,squid=squid,bridge=bridge,
        settings_source='Operator-approved previous five real brightfield frames at explicit XY; no grid navigation or autofocus',
        plan_sha256=digest(plan),hardware_motion_started=False))
    print(json.dumps(dict(prepared=True,squid_images=5,site=profile['scan_entry'],loading=bridge['dropoff'],motion=False)))

def deliver():
    receipt=OUT/'hamilton_delivery.json'
    if receipt.exists():raise RuntimeError('Delivery already attempted')
    p=mock.check(json.loads((mock.OUT/'protocol.json').read_bytes()))
    sim=json.loads((mock.OUT/'simulation/result.json').read_bytes());mock.verify_result(sim,sim['id'],p)
    state=held_home();h.hamilton_idle()
    accepted=json.loads((ROOT/'reports/squid_48well_approach/station_handling_five_20261110/operator_acceptance.json').read_bytes())
    assert accepted['completed_cycles']==[1,2,3,4,5]
    folder=OUT/'hamilton_dropoff';folder.mkdir()
    h.OUT=folder;h.TRIAL=f'integrated_dry_tips{mock.TIP_SITE}_delivery_20261110'
    record=dict(status='running',at=time.time(),authorization=AUTH,initial_state=state)
    write(receipt,record)
    try:
        arrival=h.travel_hamilton('forward');write(folder/'arrival.json',arrival)
        handling.handling('release',f'integrated_dry_tips{mock.TIP_SITE}_release_20261110',h.TRIAL,folder)
        final=arm_home();assert abs(final['robot']['external_axes']['E1']-7)<.15
        record.update(status='delivered_empty_Home_pending_well_registration',final_state=final,
            plate_location='Hamilton site4',pipetting_started=False)
    except Exception as e:
        record.update(status='failed_or_uncertain',error=str(e));raise
    finally:
        record['finished_at']=time.time();write(receipt,record)
    print(json.dumps(dict(status=record['status'],plate='Hamilton site4',arm='Home',claw=7)),flush=True)

def inspect_plate():
    receipt=json.loads((OUT/'hamilton_delivery.json').read_bytes())
    assert receipt['status']=='delivered_empty_Home_pending_well_registration'
    arm_home();hp=mock.HamiltonPrep();mock.ready(hp)
    # Capture distinct frames; do not equate rim fit with native pipetting registration.
    rows=[]
    for i in range(3):
        data=hp.call('GET','camera/position/4/15/20.19',binary=True)
        path=OUT/f'site4_after_delivery_{i}.png';path.write_bytes(data)
        gray=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_GRAYSCALE)
        try:
            grid=detect_grid(gray,FALCON48);rim=check_rim(gray,grid,FALCON48)
            rows.append(dict(offset_plate_axes_mm=grid['offset_plate_axes_mm'].tolist(),angle_crop_deg=grid['angle_crop_deg'],
                well_count=len(grid['centers']),rms_pixels=grid['rms_pixels'],rim=rim,image=str(path)))
        except Exception as error:rows.append(dict(error=str(error),image=str(path)))
        time.sleep(.3)
    mock.save(OUT/'site4_registration_review.json',dict(frames=rows,
        physical_pipetting_authorized_by_camera=False,
        note='Review camera/native coordinate registration and seating before tips enter wells. No offset auto-applied.'))
    print(json.dumps(rows),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','deliver','inspect'])
    parser.add_argument('--tip-site',type=int,choices=[6,7],default=7)
    args=parser.parse_args()
    mock.configure_tip_site(args.tip_site)
    OUT=mock.OUT/'workflow'
    AUTH=AUTH.replace('site7 A1-A6',f'site{args.tip_site} A1-A6')
    if args.tip_site==6:AUTH+=' After collision, operator confirmed securely held plate and clear Home route; loaded recovery completed with current opening preserved.'
    dict(prepare=prepare,deliver=deliver,inspect=inspect_plate)[args.action]()
