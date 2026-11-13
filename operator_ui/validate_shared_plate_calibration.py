"""Replay a saved Cellvis observation through shared calibration and real IK.

Offline only: this module never connects to the camera, Flask or controller.
Input is a cellvis24_workflow run.json containing a vision step. The output
is a candidate report, never a reusable grip/station-handling receipt.
"""
import argparse
import hashlib
import json
from pathlib import Path

from cellvis24_calibration import (REFERENCE, ACCEPTED_SEQUENCE, projected_solution,
                                 projected_trial_steps, implementation_binding, evaluate)
from cellvis24_squid_route import geometry
from cellvis24_workflow import validate_steps


def replay(path):
    raw=path.read_bytes();record=json.loads(raw)
    measurements=next(s['measurement'] for s in record['steps'] if s['kind']=='vision')
    samples=[b['measurement'] for b in measurements['bursts']]
    solution=projected_solution(samples)
    steps=projected_trial_steps(solution);g=geometry()
    start=dict(pose_mm=record['plan']['start'],joints=record['plan']['joints'])
    final=validate_steps(steps,start,g['cfg'],g['envelope'])
    return dict(motion_started=False,hardware_accessed=False,ik_checked=True,
                source=str(path.resolve()),source_sha256=hashlib.sha256(raw).hexdigest(),
                camera_reference_sha256=hashlib.sha256(REFERENCE.read_bytes()).hexdigest(),
                taught_sequence_sha256=hashlib.sha256(ACCEPTED_SEQUENCE.read_bytes()).hexdigest(),
                implementation=implementation_binding(),
                old_fixed_reference_assessment=evaluate(samples),solution=solution,
                steps=steps,final=final,physical_acceptance='pending',grip_authorized=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    result=replay(args.record)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        # Do not overwrite trial evidence accidentally.
        with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2,allow_nan=False)
    print(json.dumps(dict(motion_started=False,ik_checked=result['ik_checked'],
                         solution=result['solution'],output=str(args.output) if args.output else None),indent=2))


if __name__=='__main__':main()
