"""One authorized Home/Squid/Home round trip retaining current claws."""
from copy import deepcopy
import json
import execute_continuous_squid_return_20261103 as runner
from capture_squid_approach_20261103 import FOLDER, sha, save

FORWARD=FOLDER/'destination_final_z266p81_20261103.json'
REVERSE=FOLDER/'loaded_return_continuous_lift_z266p81_20261103.json'
PLAN=FOLDER/'closed_claw_roundtrip_plan_20261103.json'
OUTPUT=FOLDER/'closed_claw_roundtrip_trial_20261103.json'


def main():
    if sha(FORWARD)!='ac004fd846bf2333a29f29374b7091b7c042cb6cf31d53ca09c45432412a84b8' or sha(REVERSE)!='269694264565a4aef4d9b53a586d80925aa222df2aca7f3fa3d6f1aa84454fb7':
        raise RuntimeError('Saved route changed')
    forward=json.loads(FORWARD.read_bytes());reverse=json.loads(REVERSE.read_bytes())
    route=deepcopy(forward['routes']['forward'])
    back=reverse['routes']['nominal']
    assert route[-1]==back[0] and route[0]==back[-1]
    assert forward['cfg']==reverse['cfg'] and forward['envelope']==reverse['envelope']
    plan=dict(routes={'from_capture':route+deepcopy(back[1:])},cfg=forward['cfg'],envelope=forward['envelope'],
        leg_speeds=[137,137,137,5,5,137,137,137],forward=str(FORWARD),forward_sha256=sha(FORWARD),
        reverse=str(REVERSE),reverse_sha256=sha(REVERSE),gripper_commands=[],
        completion_status='closed_claw_roundtrip_completed_pending_operator_assessment',
        operator_intent='Operator confirmed previous loaded return secure and level; requested Home to Squid then same return without release.')
    if PLAN.exists():
        if json.loads(PLAN.read_bytes())!=plan:raise RuntimeError('Roundtrip plan changed')
    else:save(PLAN,plan)
    runner.PLAN=PLAN;runner.SHA=sha(PLAN);runner.OUTPUT=OUTPUT
    runner.main(expected_speeds=tuple(plan['leg_speeds']),vertical_legs=(0,3,4,7))


if __name__=='__main__':main()
