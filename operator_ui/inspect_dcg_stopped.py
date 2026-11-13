"""Read-only inspection after the DCG placement fault; never resets or moves."""
import asyncio
import json
from pathlib import Path
import inspect_hamilton_transfer_20261108 as inspection
from hamilton_prep import HamiltonPrep

if __name__ == '__main__':
    h = HamiltonPrep()
    state = h.status(fresh=True)
    if state.get('serial') != inspection.SERIAL:
        raise RuntimeError('Unexpected Hamilton identity')
    report = dict(motion_sent=False, rest_state=state,
                  purpose='Read-only inspection after placement fault')
    inspection.QUERIES = ('PrepGetIsInitialized', 'PrepGetPositions',
                         'PrepGetPlateHeld', 'PrepGetTipDefinitionHeld')
    path = Path(__file__).resolve().parent / 'reports/hamilton_api/dcg_stopped_1d9c35bc.json'
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    try:
        asyncio.run(inspection.inspect(report))
    finally:
        path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report['queries'], indent=2))
