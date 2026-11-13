"""Prepare a pose-aware native dry experiment; no starts on import.

The plate placement and per-well centers are distinct from a within-well offset.
Original vendor definitions and motion limits remain untouched.
"""
import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import numpy as np
import integrated_dry_mock_20261110 as mock
import offset_dry_mock_20261110 as offset
from three_machine_dry_run_20261110 import arm_home

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'tmp/prep-jog-audit'
PIN='fc5ae129c39ef645a2a11234dce97f933a317a9c'
OUT=offset.PARENT/'native_plate_pose'
sys.path.insert(0,str(SOURCE))
from pylabrobot.hamilton.prep.driver import prep_commands as C
from pylabrobot.hamilton.prep.driver.master import PrepDriver
from pylabrobot.hamilton.prep.driver.configuration import to_jsonable
from pylabrobot.hamilton.transport.tcp.tcp import HamiltonTCPClient
from pylabrobot.resources import Deck

READS={C.PrepGetIsInitialized,C.PrepGetPositions,C.PrepGetChannelBounds,
       C.PrepGetTipAndNeedleDefinitions,C.PrepGetTipDefinitionHeld,
       C.PrepGetDeckBounds,C.PrepGetDefaultTraverseHeight,C.PrepGetSafeSpeedsEnabled}

class ReadOnlyDriver(PrepDriver):
    async def setup(self,**kwargs):raise RuntimeError('Automatic initialization prohibited')
    async def stop(self,**kwargs):raise RuntimeError('Automatic motion on disconnect prohibited')
    async def send_command(self,command,**kwargs):
        if type(command) not in READS:raise RuntimeError('Read-only inspection')
        return await super().send_command(command,**kwargs)

async def probe():
    driver=ReadOnlyDriver(deck=Deck(name='pose_readonly',size_x=300,size_y=400,size_z=200),
        io=HamiltonTCPClient(host='192.168.100.102',port=2000,read_timeout=10,write_timeout=4))
    try:
        await driver._open()
        result={}
        for cls in sorted(READS,key=lambda c:c.__name__):
            result[cls.__name__]=to_jsonable(await driver.send_command(cls()))
        return result
    finally:await driver._close()

def prepare():
    if OUT.exists():raise RuntimeError('Native preparation already exists')
    if subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip()!=PIN:
        raise RuntimeError('Pinned driver changed')
    h=mock.HamiltonPrep();state=mock.ready(h);robot=arm_home()
    result=asyncio.run(probe())
    raw=[]
    for start in (0,1000,2000,3000):
        rows=h.call('GET',f'traces?offset={start}&limit=1000&sources=MNE')['items']
        for row in rows:
            if not '2026-11-10T07:56:50'<row['date']<'2026-11-10T07:58:51':continue
            try:message=json.loads(row['message'])
            except (ValueError,TypeError):continue
            if isinstance(message,list) and message and message[0] in ('PickUpTips','Aspirate','Dispense','DropTips'):
                raw.append(dict(date=row['date'],message=message))
        if not rows or rows[-1]['date']<'2026-11-10T07:56:50':break
    raw.sort(key=lambda v:v['date'])
    if [r['message'][0] for r in raw]!=['PickUpTips','Aspirate','Dispense','DropTips']*6:
        raise RuntimeError('Vendor-generated dry sequence is incomplete')
    targets=json.loads((offset.OUT/'measured_targets.json').read_bytes())
    mock.save(OUT/'preparation.json',dict(at=time.time(),operator_authorization=offset.AUTH,
        driver_pin=PIN,hamilton=state,arm=robot,native=result,vendor_simulated_commands=raw,
        measured_targets=targets,hardware_motion_sent=False))
    print(json.dumps(result,indent=2),flush=True)

def snake(name):
    return re.sub(r'(?<!^)(?=[A-Z])','_',name).lower()

def build_structure(cls,values):
    return cls(default_values=False,**{snake(k):v for k,v in values.items()})

def commands(preparation):
    """Bind a six-well plan to vendor-generated parameters and measured centers."""
    targets=np.array(preparation['measured_targets']['target_xy'],float)
    if targets.shape!=(6,2) or not np.isfinite(targets).all():raise ValueError('Invalid measured targets')
    nominal=np.array(preparation['measured_targets']['nominal_xy'],float)
    if np.linalg.norm(targets-nominal,axis=1).max()>12:raise ValueError('Outside reviewed placement range')
    definitions=preparation['native']['PrepGetTipAndNeedleDefinitions']['definitions']
    choices=[d for d in definitions if d['has_filter'] and not d['is_tool'] and not d['is_needle']
        and abs(d['length']-51.9)<.01 and abs(d['volume']-360)<.01 and d['tip_type']==2]
    if len(choices)!=1:raise ValueError('Expected one actual 300uL filtered tip definition')
    definition=choices[0]
    output=[];column=0
    for record in preparation['vendor_simulated_commands']:
        name,row=record['message'][:2];row=deepcopy(row)
        if name=='PickUpTips':
            column+=1;p=row['parameters'][0]
            if p['Channel']!='SingleChannel1' or len(row['parameters'])!=1:raise ValueError('Only channel1 commissioned here')
            if not np.allclose([p['XPosition'],p['YPosition'],p['ZPosition'],p['ZSeek']],
                [152.6+9*(column-1),266.53,58.97,70.97],atol=.01):raise ValueError('Tip site geometry changed')
            p['Channel']=1
            cmd=C.PrepPickUpTipsById(tip_positions=[build_structure(C.TipPositionParameters,p)],
                final_z=row['finalZ'],seek_speed=row['seekSpeed'],tip_definition_id=definition['id'],
                enable_tadm=False,dispenser_volume=0,dispenser_speed=250)
        elif name=='DropTips':
            p=row['parameters'][0];p['Channel']=1;p['DropType']=C.TipDropType.FixedHeight
            cmd=C.PrepDropTips(tip_positions=[build_structure(C.TipDropParameters,p)],
                final_z=row['finalZ'],seek_speed=row['seekSpeed'],tip_roll_off_distance=row['tipRollOffDistance'])
        else:
            if len(row)!=1 or row[0]['Channel']!='SingleChannel1':raise ValueError('Unexpected pipetting channel')
            p=row[0];common=build_structure(C.CommonParameters,p['Common']);no_lld=build_structure(C.NoLldParameters,p['NoLld'])
            if no_lld.bottom_search:raise ValueError('No searching in dry mock')
            kw=dict(default_values=False,channel=1,common=common,no_lld=no_lld,
                mix=C.MixParameters.default(),adc=C.AdcParameters.default())
            if name=='Aspirate':
                if not np.allclose([p['Aspirate']['XPosition'],p['Aspirate']['YPosition']],[15.4,263.98]):raise ValueError('Source moved')
                cmd=C.PrepAspirateNoLldMonitoring(aspirate_parameters=[C.AspirateParametersNoLldAndMonitoring(
                    **kw,aspirate=build_structure(C.AspirateParameters,p['Aspirate']),
                    aspirate_monitoring=C.AspirateMonitoringParameters.default())])
            else:
                p['Dispense'].update(XPosition=float(targets[column-1,0]),YPosition=float(targets[column-1,1]))
                cmd=C.PrepDispenseNoLld(dispense_parameters=[C.DispenseParametersNoLld(
                    **kw,dispense=build_structure(C.DispenseParameters,p['Dispense']),tadm=C.TadmParameters.default())])
        # Force wire serialization during planning, not on the first hardware run.
        cmd.build_parameters().build()
        output.append(dict(well=f'A{column}',operation=name,command=cmd))
    if column!=6:raise ValueError('Exactly six fresh tips required')
    return output

def validate_plan(preparation):
    rows=commands(preparation)
    bounds={b['channel']:b for b in preparation['native']['PrepGetChannelBounds']['bounds']}
    target=np.array(preparation['measured_targets']['target_xy'])
    nominal=np.array(preparation['measured_targets']['nominal_xy'])
    # Fit one rigid plate pose; the individual well centers must agree with it.
    direction=(target[-1]-target[0]);angle=np.arctan2(direction[1],direction[0])
    rotation=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    translation=target.mean(axis=0)-(rotation@nominal.mean(axis=0))
    predicted=(rotation@nominal.T).T+translation
    error=np.linalg.norm(predicted-target,axis=1)
    if error.max()>.2 or abs(np.degrees(angle))>2:raise ValueError('Measured targets do not form the accepted rigid plate')
    center=rotation@np.array([62.1,44.63])+translation
    corners=np.array([[-1,-1],[1,-1],[1,1],[-1,1]])*[127.63/2,85.47/2]
    corners=(rotation@corners.T).T+center
    clearance=bounds[1]['z_max']-51.9-.5
    if clearance<110:raise ValueError('Insufficient loaded traverse clearance')
    for row in rows:
        cmd=row['command'];op=row['operation']
        if op in ('Aspirate','Dispense'):
            p=getattr(cmd,'aspirate_parameters' if op=='Aspirate' else 'dispense_parameters')[0]
            xy=getattr(p,'aspirate' if op=='Aspirate' else 'dispense')
            x,y=xy.x_position,xy.y_position
            if not (p.common.z_minimum<p.no_lld.z_fluid<p.common.z_final<clearance):
                raise ValueError('Pipetting depth/exit order invalid')
            if op=='Dispense' and not np.allclose([p.common.z_minimum,p.no_lld.z_fluid,p.common.z_final],[6.41,8.41,29.19]):
                raise ValueError('Destination heights changed')
            if op=='Aspirate' and not np.allclose([p.common.z_minimum,p.no_lld.z_fluid,p.common.z_final],[4.7,5.7,29]):
                raise ValueError('Source heights changed')
        else:
            p=cmd.tip_positions[0];x,y=p.x_position,p.y_position
            if not bounds[1]['z_min']<=p.z_position<p.z_seek<147.6:raise ValueError('Tip stroke outside clear range')
        if not bounds[1]['x_min']<=x<=bounds[1]['x_max'] or not bounds[1]['y_min']<=y<=bounds[1]['y_max']:
            raise ValueError('Target exceeds live channel limits')
        # Inactive front channel is parked at Y0 at full available Z. All
        # proposed rear-channel approaches retain >20 mm separation.
        if y<20 or not bounds[2]['y_min']<=0<=bounds[2]['y_max']:raise ValueError('Channel separation invalid')
    return dict(status='offline_geometry_and_command_validation_passed',
        model='Native command serialization, measured well centers, rigid plate pose and current channel bounds; not a contact physics simulation',
        native_commands=24,plate_pose=dict(rotation_deg=float(np.degrees(angle)),
            center_native_xy=center.tolist(),corners_native_xy=corners.tolist(),max_rigid_fit_error_mm=float(error.max())),
        transfer_clearance_mm=clearance,channel_separation_min_mm=20,
        targets=target.tolist(),source_unchanged=True,tip_site=6,
        original_vendor_offset_limit_changed=False,hardware_motion_sent=False,
        preparation_sha256=mock.digest(preparation))

def simulate():
    data=json.loads((OUT/'preparation.json').read_bytes())
    result=validate_plan(data)
    mock.save(OUT/'geometry_validation.json',result)
    print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','compile','simulate'])
    args=parser.parse_args()
    if args.action=='prepare':prepare()
    elif args.action=='simulate':simulate()
    else:
        data=json.loads((OUT/'preparation.json').read_bytes());rows=commands(data)
        mock.save(OUT/'native_plan.json',dict(commands=[dict(well=r['well'],operation=r['operation'],
            type=type(r['command']).__name__,parameters=to_jsonable(r['command'])) for r in rows],
            hardware_execution_enabled=False,simulation_passed=False))
        print('24 native operations compiled; no physical execution enabled.')
