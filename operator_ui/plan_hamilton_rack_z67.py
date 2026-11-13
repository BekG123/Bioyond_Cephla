"""Offline rack revision04: lower before Hamilton crossing, preserve destination."""
import hashlib
import json
import time

from hamilton_empty_clearance import FOLDER, IDLE, IDLE_JOINTS, reference
from hamilton_rack_clearance import reference03, PLAN
from plan_short_side_hamilton import validate
from trajectory_queue import checksum

OUTPUT = FOLDER/'rack_clearance_revision04_z67.json'


def build():
    previous,parent=reference03()
    old=previous['forward']['points']
    # Complete the taught turn, then lower at that XY before any crossing.
    low_turn=dict(old[2],Z=67.0)
    low_entry=dict(old[3],Z=67.0)
    points=old[:3]+[low_turn,low_entry]+old[4:]
    speeds=[40]*(len(points)-1)+[5]
    expected=parent['routes']['forward']['validation']['endpoint_joints']
    checked=validate(IDLE,points,IDLE_JOINTS,parent['config'],parent['station_envelope'],expected)
    reverse_points=list(reversed([IDLE]+points))[1:]
    reverse=validate(points[-1],reverse_points,checked['endpoint_joints'],parent['config'],parent['station_envelope'],IDLE_JOINTS)
    if not checked['workspace_valid'] or not reverse['workspace_valid']:
        raise ValueError('Station envelope check failed.')
    if points[-1]!=old[-1]:raise ValueError('Final destination changed.')
    return dict(revision='04_z67',created_at=time.time(),status='offline_checked_not_physically_tested',
        parent_file=str(PLAN),parent_sha256=hashlib.sha256(PLAN.read_bytes()).hexdigest(),
        failed_parent_run='rack03_77244d1f74b84cf098f1387d23923589.json',
        operator_request='Z67 mm level Hamilton approach; retain final destination.',
        config=parent['config'],global_envelope=parent['global_envelope'],station_envelope=parent['station_envelope'],
        forward=dict(start=IDLE,start_joints=IDLE_JOINTS,points=points,segment_speeds=speeds,
            checksum=checksum(points,speeds),validation=checked),
        reverse=dict(start=points[-1],points=reverse_points,segment_speeds=list(reversed(speeds)),validation=reverse),
        lowering_location=low_turn,level_crossing=[low_turn,low_entry],
        final_destination_unchanged=True,global_limits_changed=False,payload='empty only',
        motion_sent=False,execution_enabled=False,collision_clearance_verified=False,
        current_arm_recovery='Not included; contact state remains unconfirmed after the previous collision.',
        limitation='IK and joint checks do not establish rack clearance. The new vertical lowering segment and Z67 crossing require physical clearance review.')


if __name__=='__main__':
    plan=build()
    with OUTPUT.open('x') as stream:json.dump(plan,stream,indent=2)
    print(json.dumps(dict(file=str(OUTPUT),points=plan['forward']['points'],speeds=plan['forward']['segment_speeds'],
        forward_ik=True,reverse_ik=True,joint_ranges=plan['forward']['validation']['joint_ranges']),indent=2))
