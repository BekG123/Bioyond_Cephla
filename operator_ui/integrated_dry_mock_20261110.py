"""Prepare and simulate the six-transfer dry mock on the current Hamilton.

No real pipetting or arm motion is exposed by this preparation tool.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from hamilton_prep import HamiltonPrep, digest

ROOT = Path(__file__).resolve().parent
OUT = ROOT/'reports/integrated_dry_mock_20261110'
OLD = ROOT/'reports/hamilton_api/dry_run_60910d1cfa244d2ab20f38ce4b07636a'
LABWARE = {2:(128,'P24w3600dnptmHAM',4,6),4:(166,'P48w800kmmtjFAL',6,8),7:(8,'235903',8,12)}
TIP_SITE = 7

def configure_tip_site(site):
    global TIP_SITE, LABWARE, OUT
    if site not in (6,7):raise ValueError('This reviewed mock supports tip site 6 or 7 only')
    TIP_SITE=site
    LABWARE={2:(128,'P24w3600dnptmHAM',4,6),4:(166,'P48w800kmmtjFAL',6,8),site:(8,'235903',8,12)}
    OUT=ROOT/('reports/integrated_dry_mock_20261110' if site==7 else 'reports/integrated_dry_mock_site6_20261110')

def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x',encoding='utf-8') as f:
        json.dump(data,f,indent=2,allow_nan=False)

def ready(h):
    s=h.status(fresh=True)
    if not (s.get('connected') and s.get('initialized') and s.get('serial')=='PRPGJ2494'
            and s.get('global_state')=='Idle' and s.get('parked') is True
            and not s['run'].get('isRunInProgress') and not s.get('pending_errors')):
        raise RuntimeError('Hamilton must be initialized, idle, parked and fault free')
    if h.call('GET','service-software-api/has-tips') is not False:
        raise RuntimeError('Hamilton channels must be empty')
    v=h.call('GET','verification/status')
    if any(v.get(k) for k in ('isWorkflowInProgress','isRunInProgress','isServiceRoutineInProgress')):
        raise RuntimeError('Hamilton service procedure active')
    return s

def strip_ids(value):
    if isinstance(value,dict):return {k:strip_ids(v) for k,v in value.items() if k!='id'}
    if isinstance(value,list):return [strip_ids(v) for v in value]
    return value

def steps(old, tip_group):
    result=[]
    for i, source in enumerate(old['steps'],1):
        row=strip_ids(deepcopy(source))
        row.update(name=f'DRY AIR source A1 to 48-well A{i}, 10uL',stepOrder=i,
                   tipLabwareGroupId=tip_group,makeNameUnique=False)
        row['destinations']=[dict(position=4,addresses=[dict(row=1,column=i)])]
        result.append(row)
    return result

def check(p, dispense_offsets=None):
    assert p['name'].startswith('DRY MOCK 48 WELL ') and p['isValid'] is True
    assert len(p['steps'])==6
    deck={v['position']:v for v in p['deck']['positions']}
    for site,(lid,name,rows,cols) in LABWARE.items():
        w=deck[site]['labwareGroup']['labware']
        assert (w['id'],w['name'],w['rows'],w['columns'])==(lid,name,rows,cols)
        assert deck[site]['liquidVolume']==0
    for i,s in enumerate(p['steps'],1):
        assert s['stepType']=='TransferSamplesStep' and s['stepOrder']==i and not s['disabled']
        assert s['sources']==[dict(position=2,addresses=[dict(row=1,column=1)])]
        assert s['destinations']==[dict(position=4,addresses=[dict(row=1,column=i)])]
        assert s['newTipsEachTransfer'] and s['tipDiscardLocation']=='DiscardToWaste'
        assert s['tipLabwareGroupId']==deck[TIP_SITE]['labwareGroup']['id']
        assert not s['mixBeforeAspirate'] and not s['mixAfterDispense'] and not s['customizeLiquid']
        for key,height in (('aspirateSettings',1),('dispenseSettings',2)):
            v=s[key]
            assert v['transferVolume']==10 and v['pipettingHeight']==height
            assert v['pipettingHeightStartPoint']=='FromContainerBottom'
            assert not v['followLiquid'] and not v['enableMad']
            if key=='dispenseSettings' and dispense_offsets is not None:
                assert v['useOffset'] is True
                assert v['offset']==dispense_offsets[i-1]
            else:
                assert not v['useOffset']
    return p

def prepare():
    if (OUT/'preparation.json').exists():raise RuntimeError('Preparation exists; preserve it, no duplicate create')
    h=HamiltonPrep();state=ready(h)
    old=json.loads((OLD/'protocol.json').read_bytes())
    outcome=json.loads((OLD/'result.json').read_bytes())
    assert outcome['runResult']=='Completed' and not outcome['errorMessages']
    definitions={}
    for site,(lid,name,rows,cols) in LABWARE.items():
        v=h.call('GET',f'labware/{lid}')
        assert (v['name'],v['rows'],v['columns'])==(name,rows,cols)
        definitions[site]=v
    deck=[]
    for site in range(1,9):
        group=None
        if site in LABWARE:
            group=dict(labwareId=LABWARE[site][0],groupName={2:'EMPTY Cellvis source',4:'Transported EMPTY Falcon 48 well',TIP_SITE:'Six fresh 300uL tips'}[site],
                       reuseTipsBetweenSteps=False,liquidName='',liquidType='Water',liquidVolumeOptions='CalculateForMe')
        deck.append(dict(position=site,positionName=f'Site {site}',labwarePositions=[],labwareGroup=group,liquidVolume=0))
    name=f'DRY MOCK 48 WELL Site2 A1 to Site4 A1-A6 tips{TIP_SITE} '+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    body=dict(name=name,makeNameUnique=False,skipValidation=False,deck=dict(positions=deck))
    save(OUT/'preparation.json',dict(initial_state=state,labware=definitions,protocol_request=body,
        prior_success=str(OLD/'result.json'),prior_protocol_sha256=digest(old),
        operator_authorization=f'Dry mock; transported 48-well at site4; empty Cellvis source site2 and six fresh 300uL tips site{TIP_SITE} A1-A6 confirmed. Five real brightfield frames at previous saved single site approved.',
        hardware_motion_sent=False))
    created=h.call('POST','protocols',body);save(OUT/'created.json',created)
    found=[p for p in h.call('GET','protocols') if p['name']==name]
    assert len(found)==1
    pid=found[0]['id'];save(OUT/'identity.json',found[0])
    p=h.call('GET',f'protocols/{pid}')
    tips=next(x['labwareGroup']['id'] for x in p['deck']['positions'] if x['position']==TIP_SITE)
    for i,row in enumerate(steps(old,tips),1):
        save(OUT/f'step_{i}_request.json',row)
        save(OUT/f'step_{i}_response.json',h.call('POST',f'protocols/{pid}/step',row))
    validation=h.call('GET',f'protocols/validate/{pid}');save(OUT/'validation.json',validation)
    p=h.call('GET',f'protocols/{pid}');save(OUT/'protocol.json',p);check(p)
    print(json.dumps(dict(prepared=True,protocol_id=pid,protocol_hash=digest(p),hardware_motion=False)),flush=True)

def reconcile_old_marker(h):
    """Archive the reviewed old failed DCG run, without claiming it succeeded."""
    marker=h.folder/'active.json'
    if not marker.exists():return
    old=json.loads(marker.read_bytes())
    if old.get('request_id')!='dcg48_repeat_683af88d0e764de8b7a8617903ffd172' or old.get('status')!='failed_or_uncertain':
        raise RuntimeError('Unexpected Hamilton ownership marker; no changes')
    park=h.folder/'bare_park_2f758a1fda124a25a9b47a503d1f5d21.jsonl'
    rows=[json.loads(l) for l in park.read_text().splitlines()]
    result=next(r for r in reversed(rows) if r['kind']=='park_result')['data']
    assert result['status']=='parked' and result['tool']['id']==0 and not result['tool']['is_tool']
    state=ready(h)
    evidence=dict(status='failed_run_resolved_by_subsequent_empty_tool_park',original_run_remains_failed=True,
        original_marker=old,original_sha256=hashlib.sha256(marker.read_bytes()).hexdigest(),
        recovery_park=str(park),recovery_sha256=hashlib.sha256(park.read_bytes()).hexdigest(),
        live_state=state,live_has_tips=False,checked_at=time.time(),hardware_commands_sent=False)
    save(OUT/'old_dcg_recovery_review.json',evidence)
    archive=h.folder/'active_dcg48_repeat_683af88d0e764de8b7a8617903ffd172_reviewed_20261110.json'
    if archive.exists():raise RuntimeError('Recovery archive already exists')
    marker.rename(archive)

def seal():
    """Read back an already-created method after the validation GET timed out."""
    h=HamiltonPrep();ready(h)
    identity=json.loads((OUT/'identity.json').read_bytes())
    p=h.call('GET',f"protocols/{identity['id']}")
    assert p['name']==identity['name']
    check(p)
    save(OUT/'protocol.json',p)
    save(OUT/'validation_readback.json',dict(isValid=True,source='Fresh protocol GET after timed-out validation GET',
        step_count=len(p['steps']),protocol_sha256=digest(p),hardware_motion_sent=False))
    print(json.dumps(dict(protocol_id=p['id'],isValid=True,protocol_hash=digest(p))))

def verify_result(result, job, protocol):
    assert result['id']==job and result['protocolName']==protocol['name']
    assert result['deviceSerialNumber']=='Simulation'
    assert result['runResult']=='Completed' and not result['errorMessages']
    assert len(result['runtimeSteps'])==6
    for i,row in enumerate(result['runtimeSteps'],1):
        assert row['stepNumber']==i and len(row['pipetteActivities'])==1
        activity=row['pipetteActivities'][0]
        assert len(activity['source'])==len(activity['target'])==1
        source,target=activity['source'][0],activity['target'][0]
        assert (source['deckPosition'],source['well'])==(2,'A1')
        assert (target['deckPosition'],target['well'])==(4,f'A{i}')
        assert float(source['volume'])==float(target['volume'])==10

def simulate(protocol_check=check):
    folder=OUT/'simulation'
    if folder.exists():raise RuntimeError('Simulation already attempted; no replay')
    h=HamiltonPrep();ready(h);reconcile_old_marker(h)
    p=protocol_check(json.loads((OUT/'protocol.json').read_bytes()));pid=p['id']
    assert digest(h.call('GET',f'protocols/{pid}'))==digest(p)
    folder.mkdir()
    with h.owned('integrated_dry_mock_simulation') as ticket:
        ticket.update(simulation=True,protocol_id=pid)
        with h.events(h) as stream:
            baseline={e['id'] for e in h.call('GET','errors?offset=0&limit=30').get('items',[])}
            previous=h.call('GET','protocol-run').get('runDatalId');job=None;sent=False;last=None;unloaded=False
            try:
                h.write(ticket,'POST','protocol-run/create',dict(protocolId=pid,simulate=True,recompile=False))
                deadline=time.monotonic()+900
                while time.monotonic()<deadline:
                    h.consume(stream,ticket);h.guard_errors(ticket,baseline)
                    run=h.call('GET','protocol-run');state=h.call('GET','instruments/global-run-state')
                    key=(state,run.get('protocolRunState'),run.get('currentStep'))
                    if key!=last:print(json.dumps(dict(state=state,run=run)),flush=True);last=key
                    if sent and job and not run['isRunInProgress'] and state=='Idle':
                        result=h.call('GET','run-data/'+job);verify_result(result,job,p)
                        save(folder/'result.json',result);ticket.update(status='completed',job_id=job)
                        h.journal(ticket,'outcome',ticket)
                        print(json.dumps(dict(simulated=True,success=True,job=job)),flush=True);return
                    if sent and job and not unloaded and ticket.get('native_finished') and not run['isRunInProgress']:
                        result=h.call('GET','run-data/'+job);verify_result(result,job,p)
                        assert run['isSimulation'] is True
                        save(folder/'cleanup_request.json',dict(job=job,run=run,result=result,simulation_only=True))
                        unloaded=True
                        response=h.write(ticket,'PUT','protocol-run/cleanup-unloading')
                        save(folder/'cleanup_response.json',response)
                    if sent and job and not run['isRunInProgress'] and run.get('protocolId')==0:
                        time.sleep(.5);continue
                    if run.get('protocolId')!=pid:
                        if not sent and run.get('protocolRunState') in (0,10,15):time.sleep(1);continue
                        raise RuntimeError('Simulation run identity changed')
                    assert run['isSimulation'] is True
                    if run.get('runDatalId'):
                        rid=run['runDatalId'];assert rid!=previous and (job is None or rid==job);job=rid
                    if run['protocolRunState']==20 and not sent:
                        instructions=h.call('GET','protocol-run/load-instructions');save(folder/'load_instructions.json',instructions)
                        assert {x['deckPosition'] for x in instructions}=={2,4,TIP_SITE}
                        assert sum(x.get('count',0) for x in instructions if x['deckPosition']==TIP_SITE)==6
                        body=dict(protocolId=pid,simulate=True,loadCompleteAction='Run',
                            residualTips=[dict(deckPosition=TIP_SITE,residualTipData=dict(useAllAddresses=False,addresses=[dict(row=1,column=c) for c in range(1,7)]))],
                            barcodes=[],liquidVolumes=[])
                        save(folder/'load_complete.json',body);sent=True
                        h.write(ticket,'PUT','protocol-run/load-complete',body)
                    time.sleep(1)
                raise RuntimeError('Simulation timed out')
            except BaseException:
                h.finish_abort(stream,ticket)
                raise

def finish_simulation():
    """Finish the simulator's explicit post-unload handshake, no physical unload."""
    h=HamiltonPrep();p=check(json.loads((OUT/'protocol.json').read_bytes()))
    marker=json.loads((h.folder/'active.json').read_bytes())
    assert marker['action']=='integrated_dry_mock_simulation'
    journal=[json.loads(l) for l in (h.folder/(marker['request_id']+'.jsonl')).read_text().splitlines()]
    events=[r['data']['event'] for r in journal if r['kind']=='event' and r['data']['channel']=='instinctevents']
    assert any(e['code'].lower()=='finished' for e in events)
    reports=[json.loads(e['data']) for e in events if e['code']=='reportGenerated']
    assert len(reports)==1
    job=reports[0]['RunReportId'];result=h.call('GET','run-data/'+job);verify_result(result,job,p)
    run=h.call('GET','protocol-run')
    assert run['isSimulation'] is True and not run['isRunInProgress'] and run['protocolId']==0
    path=OUT/'simulation/cleanup_request.json'
    save(path,dict(job=job,run=run,result=result,simulation_only=True))
    response=h.write(marker,'PUT','protocol-run/cleanup-unloading')
    save(OUT/'simulation/cleanup_response.json',response)
    print(json.dumps(dict(simulator_cleanup=response,hardware_motion=False)))

def restore_connection(protocol_check=check):
    h=HamiltonPrep();p=protocol_check(json.loads((OUT/'protocol.json').read_bytes()))
    result=json.loads((OUT/'simulation/result.json').read_bytes());verify_result(result,result['id'],p)
    assert not (h.folder/'active.json').exists()
    run=h.call('GET','protocol-run');assert not run['isRunInProgress']
    assert h.call('GET','instruments/global-run-state')=='Idle'
    config=h.call('GET','instruments')
    assert not config.get('isFakeInstrument')
    save(OUT/'simulation/reconnect_request.json',dict(config=config,run=run,hardware_start=False))
    response=h.call('PUT','instruments/connect-to-instrument')
    save(OUT/'simulation/reconnect_response.json',response)
    save(OUT/'simulation/restored_physical_state.json',ready(h))
    print('Physical Hamilton transport restored; no initialization sent.',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','seal','simulate','finish-simulation','restore-connection'])
    parser.add_argument('--tip-site',type=int,choices=[6,7],default=7)
    args=parser.parse_args()
    configure_tip_site(args.tip_site)
    {'prepare':prepare,'seal':seal,'simulate':simulate,'finish-simulation':finish_simulation,'restore-connection':restore_connection}[args.action]()
