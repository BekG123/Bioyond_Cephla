"""Apply the operator's Hamilton-specific floor scope to the exact offline path."""
import hashlib
import json
import time
from short_side_alignment_trial import FOLDER
from plan_short_side_hamilton import validate

source=FOLDER/'hamilton_short_side_ik_plan.json'
path=FOLDER/'hamilton_short_side_station_plan.json'
if path.exists():raise RuntimeError('Station plan exists; preserve before revising')
raw=source.read_bytes();plan=json.loads(raw)
station_env={k:(plan['envelope'][k]['min'],plan['envelope'][k]['max']) for k in ('X','Y','Z')}
station_env['Z']=(min(plan['taught_endpoint']['Z'],plan['candidates']['direct']['points'][-1]['Z']),station_env['Z'][1])
points=plan['candidates']['direct']['points']
forward=validate(plan['home'],points,plan['home_joints'],plan['config'],station_env,plan['measured_endpoint_joints'])
reverse=validate(plan['reverse']['start'],plan['reverse']['points'],plan['measured_endpoint_joints'],plan['config'],station_env,plan['home_joints'])
assert forward['workspace_valid'] and reverse['workspace_valid']
record=dict(status='hamilton_specific_ik_plan_ready_for_clearance_review',at=time.time(),
    parent_sha256=hashlib.sha256(raw).hexdigest(),parent_file=source.name,
    operator_clarification='Z70 floor applies to calibration-holder descent, not the Hamilton path.',
    route_scope='Only this pinned Home to taught Hamilton site-4 short-side endpoint and its exact reverse.',
    start=plan['home'],endpoint=plan['taught_endpoint'],station_envelope=station_env,
    global_envelope=plan['envelope'],global_limits_changed=False,config=plan['config'],
    routes=dict(forward=dict(start=plan['home'],points=points,validation=forward),
                reverse=dict(start=plan['reverse']['start'],points=plan['reverse']['points'],validation=reverse)),
    speed=137,queues_per_direction=1,move_l_commands_per_direction=1,completion_barriers=1,
    lua_queue_candidate=plan['lua_queue_candidate'],
    collision_clearance_verified=False,execution_enabled=False,live_test_performed=False,
    remaining_review='Physical swept clearance of the new diagonal arm, jaws and plate path before first motion.',
    existing_hamilton_path_replaced=False)
with path.open('x') as f:json.dump(record,f,indent=2,allow_nan=False)
print(json.dumps(dict(path=str(path),forward_ik_and_workspace_valid=True,reverse_ik_and_workspace_valid=True,
    speed=137,moves_per_direction=1,length_mm=forward['length_mm'],station_envelope=station_env),indent=2))
