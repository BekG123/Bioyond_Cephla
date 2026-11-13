"""Offline revision02 from a stationary taught after-turn pose. No robot client."""
import argparse
import hashlib
import json
import math
import time
from pathlib import Path

from hamilton_empty_clearance import IDLE, IDLE_JOINTS, SPEEDS, points, reference
from plan_short_side_hamilton import validate
from trajectory_queue import checksum


def build(capture):
    raw=Path(capture).read_bytes();taught=json.loads(raw);parent=reference()
    turn={k:math.floor(v*100+.5)/100 for k,v in taught['target'].items()}
    old=points()
    # Replace the failed turning section, not merely insert a point after it.
    ready=dict(turn,Z=old[2]['Z'],Rz=old[2]['Rz'])
    forward=[old[0],turn,ready]+old[3:]
    expected=parent['routes']['forward']['validation']['endpoint_joints']
    check=validate(IDLE,forward,IDLE_JOINTS,parent['config'],parent['station_envelope'],expected)
    taught_check=validate(IDLE,forward[:2],IDLE_JOINTS,parent['config'],parent['station_envelope'],taught['joints'])
    reverse=list(reversed([IDLE]+forward))[1:]
    back=validate(forward[-1],reverse,check['endpoint_joints'],parent['config'],parent['station_envelope'],IDLE_JOINTS)
    for result in (check,taught_check,back):
        if not result['workspace_valid']:raise ValueError('Candidate exceeds station envelope')
    if forward[-1]!=old[-1]:raise ValueError('Hamilton endpoint changed')
    return dict(revision='02',created_at=time.time(),status='offline_ik_valid_pending_physical_review',
        capture_file=str(capture),capture_sha256=hashlib.sha256(raw).hexdigest(),
        parent_failed_run='970ff3fa6bcf4333a0f59a8943ab6781.json',
        previous_points=old,taught_after_turn=turn,config=parent['config'],
        station_envelope=parent['station_envelope'],global_envelope=parent['global_envelope'],
        routes=dict(forward=dict(start=IDLE,points=forward,segment_speeds=SPEEDS,validation=check,checksum=checksum(forward,SPEEDS)),
                    reverse=dict(start=forward[-1],points=reverse,segment_speeds=list(reversed(SPEEDS)),validation=back)),
        taught_waypoint_joint_check=taught_check['endpoint_joint_error'],
        changed='Move turn through newly taught pose and complete wrist rotation there before crossing to unchanged Hamilton overhead point.',
        final_destination_unchanged=True,global_limits_changed=False,
        payload='empty only',execution_enabled=False,live_test_performed=False,
        collision_clearance_verified=False,
        limitation='No rack geometry model. IK verifies joints and reach, not obstacle clearance or loaded-plate clearance.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=build(args.capture)
    with args.output.open('x') as stream:json.dump(result,stream,indent=2)
    print(json.dumps(dict(file=str(args.output),points=result['routes']['forward']['points'],
        speeds=SPEEDS,forward_ik=True,reverse_ik=True,endpoint_unchanged=True,
        joint_ranges=result['routes']['forward']['validation']['joint_ranges']),indent=2))


if __name__=='__main__':main()
