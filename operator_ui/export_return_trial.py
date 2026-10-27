"""Snapshot the latest completed recorded traversal without stopping logging."""
import argparse
from datetime import datetime
import json
import re
from pathlib import Path
import urllib.request


def export(folder):
    folder=Path(folder)
    with urllib.request.urlopen('http://127.0.0.1:5002/seq',timeout=5) as response:
        sequence=json.load(response)
    if sequence.get('active') or sequence.get('name')!='recorded_return':
        raise ValueError('Wait until the recorded traversal has finished.')
    pending=[]
    completed=None
    source=folder/'samples.jsonl'
    with source.open('rb') as stream:
        size=source.stat().st_size
        while stream.tell()<size:
            line=stream.readline(size-stream.tell())
            if not line.endswith(b'\n'):
                break
            row=json.loads(line)
            run=row.get('sequence') or {}
            if run.get('name')=='recorded_return' and run.get('active'):
                pending.append(row)
            elif pending:
                pending.append(row)
                completed=pending
                pending=[]
    if not completed:
        raise ValueError('No completed traversal found in this recording.')
    first,last=completed[0],completed[-1]
    target=sequence.get('result',{}).get('endpoint')
    end=last['robot']['pose_mm']
    speed=(sequence.get('result') or {}).get('speed')
    if speed is None:
        for entry in sequence.get('log',[]):
            match=re.search(r'speed: ([0-9.]+) mm/s',entry.get('msg',''))
            if match: speed=float(match.group(1)); break
    result=dict(schema='cephla.recorded-path-trial.v1',speed=speed,
        first_sample=first['index'],last_sample=last['index'],samples=len(completed),
        started_at=first['requested_at'],ended_at=last['received_at'],
        observed_duration_s=(datetime.fromisoformat(last['received_at'])-datetime.fromisoformat(first['requested_at'])).total_seconds(),
        invalid_samples=sum(not r['valid'] for r in completed),
        max_gap_s=max(b['elapsed_s']-a['elapsed_s'] for a,b in zip(completed,completed[1:])),
        target=target,measured_endpoint=end,
        endpoint_error={k:end[k]-target[k] for k in ('X','Y','Z','Rz')} if target else None,
        sequence=sequence,
        trajectory=[dict(index=r['index'],at=r['received_at'],valid=r['valid'],
            pose_mm=r['robot'].get('pose_mm'),joints=r['robot'].get('joints'),
            external_axes=r['robot'].get('external_axes'),errors=r['robot'].get('errors')) for r in completed],
        notes=['No collision or contact clearance is inferred from controller telemetry.',
               'Continuous recording remains active; this file preserves one completed traversal.'])
    path=folder/f"trial_{first['index']}_{last['index']}.json"
    path.write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    return {k:v for k,v in result.items() if k not in ('trajectory','sequence')} | dict(path=str(path.resolve()),result=sequence.get('result'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder')
    print(json.dumps(export(parser.parse_args().folder),indent=2))
