"""Offline revision: one continuous speed-5 clearance lift; no hardware access."""
from copy import deepcopy
import json
import math
from capture_squid_approach_20261103 import FOLDER, save, sha
from prepare_squid_destination import validate

SOURCE=FOLDER/'loaded_return_final_z266p81_20261103.json'
OUTPUT=FOLDER/'loaded_return_continuous_lift_z266p81_20261103.json'


def main():
    if OUTPUT.exists():raise RuntimeError('Revised plan already saved')
    if sha(SOURCE)!='78d4167fa4dd9472af1354b8ea88650a0d51520fca1fd74aad68fb8b1d1ae017':
        raise RuntimeError('Parent plan changed')
    parent=json.loads(SOURCE.read_bytes());record=deepcopy(parent)
    checks={}
    for name,old in parent['routes'].items():
        if len(old)!=6 or any(abs(old[0][k]-old[2][k])>1e-9 for k in ('X','Y','Rz')):
            raise RuntimeError('Expected two collinear vertical lift segments')
        route=[old[0],*old[2:]]
        assert route[1:]==old[2:] and route[0]==old[0]
        checked=validate(route,parent['source_state']['robot']['joints'],parent['cfg'],parent['envelope'])
        rounded=[{k:math.floor(v*100+.5)/100 for k,v in point.items()} for point in route]
        checked['quantized_final_joints']=validate(rounded,parent['source_state']['robot']['joints'],parent['cfg'],parent['envelope'])['final_joints']
        if any(abs(checked['final_joints'][k]-parent['validation'][name]['final_joints'][k])>.001 for k in checked['final_joints']):
            raise RuntimeError('Home joint solution changed')
        record['routes'][name]=route;checks[name]=checked
    record.update(parent=str(SOURCE),parent_sha256=sha(SOURCE),validation=checks,
        leg_speeds=[5,137,137,137],lift_mm=24.43,continuous_lift=True,
        operator_intent='Combine initial 5 mm lift and clearance rise into one continuous vertical command at speed 5; retain closed claws and remaining route.',
        status='offline_checked_continuous_lift_pending_supervised_trial',
        lift_command_count=1,execution_authorized=False,hardware_motion_commands_sent=False)
    assert len(record['leg_speeds'])==len(record['routes']['from_capture'])-1
    save(OUTPUT,record)
    print(json.dumps(dict(path=str(OUTPUT),sha256=sha(OUTPUT),route=record['routes']['nominal'],
        speeds=record['leg_speeds'],samples=checks['from_capture']['sample_count'])),flush=True)


if __name__=='__main__':main()
