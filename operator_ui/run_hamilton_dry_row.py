"""Explicitly supervised, one-shot physical AIR-only trial of protocol 1004."""
import json
import sys
import time
from hamilton_prep import HamiltonPrep, digest
from simulate_hamilton_row import verify_result


def check_protocol(protocol):
    assert protocol['id'] == 1004 and protocol['name'].startswith('DRY RUN ')
    assert protocol['isValid'] and len(protocol['steps']) == 6
    positions = {p['position']: p for p in protocol['deck']['positions']}
    for site, labware in ((2, 117), (3, 115), (7, 273)):
        assert positions[site]['labwareGroup']['labware']['id'] == labware
        assert positions[site]['liquidVolume'] == 0
    assert positions[7]['labwareGroup']['reuseTipsBetweenSteps'] is False
    tip_group = positions[7]['labwareGroup']['id']
    for column, step in enumerate(protocol['steps'], 1):
        assert step['stepOrder'] == column and not step['disabled']
        assert step['channelSelection'] == 'TwoChannel' and step['tipLabwareGroupId'] == tip_group
        assert step['newTipsEachTransfer'] and step['tipDiscardLocation'] == 'DiscardToWaste'
        assert step['sources'] == [dict(position=2, addresses=[dict(row=1, column=1)])]
        assert step['destinations'] == [dict(position=3, addresses=[dict(row=1, column=column)])]
        assert not step['mixBeforeAspirate'] and not step['mixAfterDispense'] and not step['customizeLiquid']
        for key, height in (('aspirateSettings', 1), ('dispenseSettings', 2)):
            settings = step[key]
            assert settings['transferVolume'] == 10 and settings['pipettingHeight'] == height
            assert settings['pipettingHeightStartPoint'] == 'FromContainerBottom'
            assert not settings['followLiquid'] and not settings['enableMad'] and not settings['useOffset']
            assert settings['retractToWellTop']


def physical_ready(h):
    s = h.call('GET', 'service-software-api/sensor-status')
    assert s.get('isDoorClosed') is True and s.get('isEnclosurePresent') is True, 'Door/enclosure not closed'
    assert not h.call('GET', 'errors/check-for-pending-errors'), 'Pending instrument fault'


def main():
    if sys.argv[1:] != ['--confirmed-empty-wells-and-clearance']:
        raise SystemExit('Operator confirmation of empty wells, tip inventory, plate models and clearance is required.')
    h = HamiltonPrep()
    h.preflight(initialized=True)
    physical_ready(h)
    assert h.call('GET', 'service-software-api/has-tips') is False
    assert not any(x.get('status') == 'Blocking' for x in h.call('GET', 'maintenance'))
    # Recent channel procedure completed with operator-confirmed unloading.
    calibration = [json.loads(l) for l in (h.folder / 'dfeb61b5a70747f380727c7a00ff46b9.jsonl').read_text().splitlines()]
    assert any(e['kind'] == 'outcome' and e['data'].get('status') == 'completed' for e in calibration)
    protocol = h.call('GET', 'protocols/1004')
    check_protocol(protocol)
    with h.owned('physical_dry_run') as ticket:
        ticket.update(simulation=False, liquid=False, protocol_id=1004)
        folder = h.folder / ('dry_run_' + ticket['request_id'])
        folder.mkdir()
        (folder / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
        pointer = dict(request_id=ticket['request_id'], step_ids=[s['id'] for s in protocol['steps']])
        temp = h.folder / 'dry_run_viewer.tmp'
        temp.write_text(json.dumps(pointer))
        temp.replace(h.folder / 'dry_run_viewer.json')
        with h.events(h) as stream:
            baseline = {e['id'] for e in h.call('GET', 'errors?offset=0&limit=30').get('items', [])}
            previous = h.call('GET', 'protocol-run').get('runDatalId')
            sent, job, last = False, None, None
            try:
                assert digest(h.call('GET', 'protocols/1004')) == digest(protocol)
                h.write(ticket, 'POST', 'protocol-run/create', dict(protocolId=1004, simulate=False, recompile=False))
                deadline = time.monotonic() + 900
                while time.monotonic() < deadline:
                    h.consume(stream, ticket)
                    h.guard_errors(ticket, baseline)
                    run = h.call('GET', 'protocol-run')
                    state = h.call('GET', 'instruments/global-run-state')
                    key = (run.get('protocolRunState'), run.get('currentStep'), state)
                    if key != last:
                        print(json.dumps(dict(state=state, run=run)), flush=True)
                        h.journal(ticket, 'live_progress', dict(state=state, run=run))
                        last = key
                    if sent and job and not run['isRunInProgress'] and state == 'Idle':
                        result = h.call('GET', 'run-data/' + job)
                        verify_result(result, job, protocol['name'], 'PRPGD2427')
                        (folder / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
                        ticket.update(status='completed', job_id=job, result=result, liquid_transferred_ul=0)
                        h.journal(ticket, 'outcome', ticket)
                        print(json.dumps(dict(completed=True, dry_run=True, job_id=job, evidence=str(folder))), flush=True)
                        return
                    # Run identity clears before global state switches to Idle.
                    # Keep the captured job ID and await cleanup; do not abort
                    # a completed run because these snapshots arrive separately.
                    if sent and job and run.get('protocolId') == 0 and not run['isRunInProgress']:
                        time.sleep(.5)
                        continue
                    if run.get('protocolId') != 1004:
                        if not sent and run.get('protocolRunState') in (0, 10, 15):
                            time.sleep(1)
                            continue
                        raise RuntimeError('Run identity changed; refusing further commands.')
                    assert run.get('isSimulation') is False, 'Unexpected execution mode'
                    rid = run.get('runDatalId')
                    if rid:
                        assert rid != previous and (job is None or job == rid)
                        job = rid
                        ticket['job_id'] = rid
                    if run['protocolRunState'] == 20 and not sent:
                        instructions = h.call('GET', 'protocol-run/load-instructions')
                        (folder / 'load_instructions.json').write_text(json.dumps(instructions, indent=2))
                        assert sum(i.get('count', 0) for i in instructions if i.get('deckPosition') == 7) == 6
                        assert {i['deckPosition'] for i in instructions} == {2, 3, 7}
                        physical_ready(h)
                        body = dict(protocolId=1004, simulate=False, loadCompleteAction='Run',
                            residualTips=[dict(deckPosition=7, residualTipData=dict(useAllAddresses=False,
                                addresses=[dict(row=1, column=c) for c in range(1, 7)]))],
                            barcodes=[], liquidVolumes=[])
                        sent = True
                        h.write(ticket, 'PUT', 'protocol-run/load-complete', body)
                    time.sleep(1)
                raise RuntimeError('Dry run timed out; no retry was sent.')
            except BaseException:
                h.finish_abort(stream, ticket)
                raise


if __name__ == '__main__':
    main()
