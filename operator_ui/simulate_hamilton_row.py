"""One-shot native API simulation. No physical execution mode is implemented."""
import json
import sys
import time
from pathlib import Path

from hamilton_prep import HamiltonPrep


def verify_result(result, job, name, expected_serial='Simulation'):
    assert result['id'] == job and result['protocolName'] == name
    assert result['deviceSerialNumber'] == expected_serial
    assert result['runResult'] == 'Completed' and not result['errorMessages']
    assert len(result['runtimeSteps']) == 6
    for column, step in enumerate(result['runtimeSteps'], 1):
        assert step['stepNumber'] == column and len(step['pipetteActivities']) == 1
        activity = step['pipetteActivities'][0]
        assert len(activity['source']) == len(activity['target']) == 1
        source, target = activity['source'][0], activity['target'][0]
        assert source['deckPosition'] == 2 and source['well'] == 'A1'
        assert target['deckPosition'] == 3 and target['well'] == 'A' + str(column)
        assert float(source['volume']) == float(target['volume']) == 10
    assert len(result['stepOverviews']) == 6
    for overview in result['stepOverviews']:
        assert any(x['label'] == 'New Tips Each Transfer' and x['value'] == 'True'
                   for x in overview['stepOverviewItems'])


def main():
    if sys.argv[1:] != ['--simulate']:
        raise SystemExit('Use --simulate. Physical execution is not supported.')
    h = HamiltonPrep()
    h.preflight()
    protocol = h.call('GET', 'protocols/1003')
    assert protocol['name'].startswith('SIMULATION ')
    assert protocol['isValid'] and len(protocol['steps']) == 6
    for column, step in enumerate(protocol['steps'], 1):
        assert step['newTipsEachTransfer'] and step['tipDiscardLocation'] == 'DiscardToWaste'
        assert step['sources'] == [dict(position=2, addresses=[dict(row=1, column=1)])]
        assert step['destinations'] == [dict(position=3, addresses=[dict(row=1, column=column)])]
        assert step['aspirateSettings']['transferVolume'] == 10
        assert step['dispenseSettings']['transferVolume'] == 10
    with h.owned('protocol_simulation') as ticket:
        ticket.update(simulation=True, protocol_id=1003)
        folder = h.folder / ('simulation_' + ticket['request_id'])
        folder.mkdir()
        (folder / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
        with h.events(h) as stream:
            baseline = {e['id'] for e in h.call('GET', 'errors?offset=0&limit=30').get('items', [])}
            previous = h.call('GET', 'protocol-run').get('runDatalId')
            sent = False
            job = None
            last = None
            deadline = time.monotonic() + 900
            try:
                h.write(ticket, 'POST', 'protocol-run/create', dict(protocolId=1003, simulate=True, recompile=False))
                while time.monotonic() < deadline:
                    h.consume(stream, ticket)
                    h.guard_errors(ticket, baseline)
                    run = h.call('GET', 'protocol-run')
                    state = h.call('GET', 'instruments/global-run-state')
                    key = (run.get('protocolRunState'), run.get('currentStep'), state, run.get('isSimulation'))
                    if key != last:
                        print(json.dumps(dict(state=state, run=run)), flush=True)
                        h.journal(ticket, 'simulation_progress', dict(state=state, run=run))
                        last = key
                    # Completion resets ProtocolId to zero; validate the captured
                    # run ID's report before checking the active-run identity.
                    if sent and job and not run['isRunInProgress'] and state == 'Idle':
                        result = h.call('GET', 'run-data/' + str(job))
                        verify_result(result, job, protocol['name'])
                        (folder / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
                        ticket.update(status='completed', result=result)
                        h.journal(ticket, 'outcome', ticket)
                        print(json.dumps(dict(completed=True, job_id=job, evidence=str(folder))), flush=True)
                        return
                    if sent and job and run.get('protocolId') == 0 and not run['isRunInProgress']:
                        time.sleep(.5)
                        continue
                    if run.get('protocolId') != 1003:
                        if not sent and run.get('protocolRunState') in (0, 10, 15):
                            time.sleep(1)
                            continue
                        raise RuntimeError('Run identity changed; refusing further commands.')
                    if run.get('isSimulation') is not True:
                        raise RuntimeError('Hamilton did not confirm simulation; refusing loading.')
                    run_id = run.get('runDatalId')
                    if run_id:
                        assert run_id != previous and (job is None or run_id == job)
                        job = run_id
                        ticket['job_id'] = job
                    # This server uses spaced enum values: Loading=20, Running=25.
                    # The OpenAPI enum list omits those numerical assignments.
                    if run['protocolRunState'] == 20 and not sent:
                        instructions = h.call('GET', 'protocol-run/load-instructions')
                        (folder / 'load_instructions.json').write_text(json.dumps(instructions, indent=2), encoding='utf-8')
                        print(json.dumps(dict(load_instructions=instructions)), flush=True)
                        tips = [i for i in instructions if i.get('deckPosition') == 7]
                        assert tips and sum(i.get('count', 0) for i in tips) == 6, 'Unexpected tip requirement'
                        body = dict(protocolId=1003, simulate=True, loadCompleteAction='Run',
                            residualTips=[dict(deckPosition=7, residualTipData=dict(useAllAddresses=False,
                                addresses=[dict(row=1, column=c) for c in range(1, 7)]))],
                            barcodes=[], liquidVolumes=[dict(deckPosition=2, positionOnSite=0, row=1, column=1, volume=1000)])
                        sent = True
                        h.write(ticket, 'PUT', 'protocol-run/load-complete', body)
                    time.sleep(1)
                raise RuntimeError('Simulation timed out; no repeat was sent.')
            except BaseException:
                h.finish_abort(stream, ticket)
                raise


if __name__ == '__main__':
    main()
