"""Simulation-only vendor gripper reference. No physical execution mode.

The virtual magnet at site 3 is not on the physical deck. Its destination Z
must never be used for the requested physical empty-site transfer.
"""
import argparse
from datetime import datetime, timezone
import json
import time
from pathlib import Path
from hamilton_prep import HamiltonPrep

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--simulate', action='store_true', required=True)
    p.add_argument('--resume', type=Path)
    p.add_argument('--labware-id', type=int, choices=(166,226), default=226)
    args = p.parse_args()
    h = HamiltonPrep()
    state = h.preflight(initialized=True)
    if state['serial'] != 'PRPGJ2494':
        raise RuntimeError('Unexpected instrument')
    if not state.get('parked') or h.call('GET','service-software-api/has-tips') is not False:
        raise RuntimeError('Parked, empty Hamilton required before simulator handoff')
    starting_config=h.call('GET','instruments')
    if starting_config.get('isFakeInstrument') or starting_config.get('endpoint')!='192.168.100.102':
        raise RuntimeError('Unexpected real instrument configuration')
    trace_start=datetime.now(timezone.utc)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = args.resume or h.folder / ('gripper_simulation_' + stamp)
    if not args.resume:
        folder.mkdir()
    def save(name, data):
        (folder / name).write_text(json.dumps(data, indent=2), encoding='utf-8')
    name = 'SIMULATION ONLY gripper reference virtual magnet ' + stamp
    deck = []
    for site in range(1, 9):
        group = None
        if site in (3, 4):
            group = dict(labwareId=39 if site == 3 else args.labware_id,
                groupName='VIRTUAL magnet' if site == 3 else f'Falcon labware {args.labware_id} reference',
                reuseTipsBetweenSteps=False, liquidName=f'Unused at site {site}',
                liquidType='Water', liquidVolumeOptions='SamePerContainer')
        deck.append(dict(position=site, positionName='Site ' + str(site),
                         labwarePositions=[], labwareGroup=group, liquidVolume=0))
    request = dict(name=name, makeNameUnique=False, skipValidation=False,
                   deck=dict(positions=deck))
    if args.resume:
        identity = json.loads((folder / 'identity.json').read_text())
        pid, name = identity['id'], identity['name']
        if not name.startswith('SIMULATION ONLY gripper reference virtual magnet '):
            raise RuntimeError('Not a simulation reference')
        protocol = h.call('GET', f'protocols/{pid}')
        if protocol['name'] != name or protocol.get('dateRun', '').startswith('2026'):
            raise RuntimeError('Changed or previously run protocol')
        if len(protocol['steps']) == 2:
            second = dict(protocol['steps'][1])
            save('removed_simulation_return_step.json', second)
            h.call('DELETE', f'protocols/{pid}/step/{second["id"]}')
    else:
        save('request.json', request)
        save('created.json', h.call('POST', 'protocols', request))
        matches = [v for v in h.call('GET', 'protocols') if v['name'] == name]
        if len(matches) != 1:
            raise RuntimeError('Protocol identity ambiguous')
        pid = matches[0]['id']
        save('identity.json', matches[0])
        for order, source, target in ((1, 4, 3),):
            h.call('POST', f'protocols/{pid}/step', dict(stepType='TransportStep',
                name=f'SIMULATION ONLY original plate {source} to {target}', stepOrder=order,
                disabled=False, makeNameUnique=False, startPosition=source, endPosition=target))
    valid = h.call('GET', f'protocols/validate/{pid}')
    save('validation.json', valid)
    protocol = h.call('GET', f'protocols/{pid}')
    save('protocol.json', protocol)
    source_group=next(v for v in protocol['deck']['positions'] if v['position']==4)['labwareGroup']
    if source_group['labwareId']!=args.labware_id:
        raise RuntimeError('Simulation source definition differs from requested labware')
    if not protocol['isValid']:
        raise RuntimeError('Vendor validation did not pass')
    print(json.dumps(dict(protocol_id=pid, validation=valid, folder=str(folder))), flush=True)
    with h.owned('gripper_reference_simulation') as ticket:
        ticket.update(simulation=True, protocol_id=pid)
        with h.events(h) as stream:
            baseline = {e['id'] for e in h.call('GET', 'errors?offset=0&limit=30').get('items', [])}
            previous = h.call('GET', 'protocol-run').get('runDatalId')
            sent = False
            job = None
            last = None
            unloaded=False
            next_result_check=0
            try:
                h.write(ticket, 'POST', 'protocol-run/create',
                        dict(protocolId=pid, simulate=True, recompile=False))
                deadline = time.monotonic() + 300
                while time.monotonic() < deadline:
                    h.consume(stream, ticket)
                    h.guard_errors(ticket, baseline)
                    run = h.call('GET', 'protocol-run')
                    state = h.call('GET', 'instruments/global-run-state')
                    key = (run.get('protocolRunState'), run.get('currentStep'), state)
                    if key != last:
                        print(json.dumps(dict(state=state, run=run)), flush=True)
                        h.journal(ticket, 'simulation_progress', dict(state=state, run=run))
                        last = key
                    if sent and job and not run['isRunInProgress'] and state == 'Idle':
                        result = h.call('GET', 'run-data/' + str(job))
                        save('result.json', result)
                        if (result['id'] != job or result['protocolName'] != name
                                or result['deviceSerialNumber'] != 'Simulation'
                                or result['runResult'] != 'Completed' or result['errorMessages']):
                            raise RuntimeError('Simulation completion not verified')
                        traces=h.call('GET','traces?offset=0&limit=2000&sources=MNE')
                        selected=[]
                        for row in traces.get('items',[]):
                            try:
                                when=datetime.fromisoformat(row['date'].replace('Z','+00:00'))
                                message=json.loads(row['message'])
                            except (ValueError,TypeError,KeyError): continue
                            if (when>=trace_start and isinstance(message,list) and message
                                    and message[0] in ('PickUpDCG','PickUpPlate','DropPlate','DropTool')):
                                selected.append(dict(date=row['date'],simulation=True,message=message))
                        save('simulation_gripper_commands.json',selected)
                        # Reconnect transport only; no initialization or physical method.
                        cfg=h.call('GET','instruments')
                        if cfg.get('endpoint')!=starting_config['endpoint'] or cfg.get('isFakeInstrument'):
                            raise RuntimeError('Real connection configuration changed')
                        h.write(ticket,'PUT','instruments/connect-to-instrument')
                        restored=h.status(fresh=True)
                        save('restored_real_state.json',restored)
                        if (restored.get('serial')!='PRPGJ2494' or not restored.get('connected')
                                or not restored.get('parked') or not restored.get('initialized')
                                or restored.get('pending_errors')):
                            raise RuntimeError('Real instrument reconnection not verified')
                        ticket.update(status='completed')
                        h.journal(ticket, 'outcome', dict(completed=True, job=job, folder=str(folder)))
                        print('SIMULATION COMPLETE ' + str(folder), flush=True)
                        return
                    if run.get('protocolId') != pid:
                        if (not sent and run.get('protocolRunState') in (0, 10, 15)) or (
                                sent and job and run.get('protocolId') == 0 and not run['isRunInProgress']):
                            time.sleep(.5)
                            continue
                        raise RuntimeError('Run identity changed')
                    if run.get('isSimulation') is not True:
                        raise RuntimeError('Simulation not confirmed; refusing loading')
                    rid = run.get('runDatalId')
                    if rid:
                        if rid == previous or (job is not None and job != rid):
                            raise RuntimeError('Unexpected run ID')
                        job = rid
                        ticket['job_id'] = job
                    if sent and job and not unloaded and time.monotonic()>=next_result_check:
                        next_result_check=time.monotonic()+3
                        result=h.call('GET','run-data/'+str(job))
                        if result.get('runResult')=='Completed':
                            if (result.get('id')!=job or result.get('protocolName')!=name
                                    or result.get('deviceSerialNumber')!='Simulation' or result.get('errorMessages')):
                                raise RuntimeError('Unloading is not a verified successful simulation')
                            save('result_before_unload.json',result)
                            unloaded=True
                            h.write(ticket,'PUT','protocol-run/cleanup-unloading')
                    if run['protocolRunState'] == 20 and not sent:
                        # No physical loading: the exact virtual deck is saved in
                        # protocol.json. This server's optional loading-display
                        # endpoint returns HTTP 500 for transport-only protocols.
                        save('simulation_load_ack.json', dict(protocol_id=pid,
                            simulation_verified=True, physical_loading_required=False))
                        # This acknowledgement belongs exclusively to the verified simulator.
                        sent = True
                        h.write(ticket, 'PUT', 'protocol-run/load-complete',
                                dict(protocolId=pid, simulate=True, loadCompleteAction='Run',
                                     residualTips=[], barcodes=[], liquidVolumes=[]))
                    time.sleep(.5)
                raise RuntimeError('Simulation timed out')
            except BaseException:
                h.finish_abort(stream, ticket)
                raise

if __name__ == '__main__':
    main()
