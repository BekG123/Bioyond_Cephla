"""One explicitly approved 20 mm camera-view lift; stops at Z268.02."""
import argparse
import json
import time
from pathlib import Path
from urllib.request import Request,urlopen
from autonomy import check_path
ROOT=Path(__file__).resolve().parent.parent
def call(path,body=None):
    request=Request('http://127.0.0.1:5002'+path,data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=45) as response:return json.load(response)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute-confirmed',action='store_true')
    args=parser.parse_args();state=call('/state');robot=state['robot']
    if state['sequence']['active'] or not robot.get('connected') or not robot.get('ok') or robot.get('errors'):
        raise RuntimeError('Require idle, connected, fault-free arm.')
    if robot['control_mode']['mode']!='auto' or not robot['enabled'] or robot['program_state']['state']!='running':
        raise RuntimeError('Controller not already ready; no mode/start/reset actions permitted.')
    start=robot['pose_mm'];expected=dict(X=283.678,Y=50.136,Z=248.02,Rz=-3.88)
    if any(abs(start[k]-v)>.05 for k,v in expected.items()):raise RuntimeError('Arm differs from approved start.')
    target={**expected,'Z':268.02}
    params=json.loads((ROOT/'operator_ui/robot_params.json').read_text())
    envelope={k:(state['envelope'][k]['min'],state['envelope'][k]['max']) for k in ('X','Y','Z')}
    check_path(start,target,robot['joints'],params,envelope)
    record=dict(timestamp=time.time(),before=state,target=target,speed=5,operator_clearance_confirmed=args.execute_confirmed)
    if not args.execute_confirmed:print(json.dumps(record,indent=2));return
    path=ROOT/'operator_ui/reports/projected_disk_pilot/wider_view_lift_20261026.json'
    # Reserve the one-attempt record before any physical command.
    with path.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    result=call('/move',dict(x=target['X'],y=target['Y'],z=target['Z'],rz=target['Rz'],speed=5,interpolation='linear'))
    record.update(response=result,after=call('/state'))
    path.write_text(json.dumps(record,indent=2),encoding='utf-8')
    if not result.get('ok') or result.get('recovered'):raise RuntimeError('Lift not verified; no retry. See '+str(path))
    after=record['after']['robot']
    if not after.get('ok') or after.get('errors') or any(abs(after['pose_mm'][k]-v)>.1 for k,v in target.items()):
        raise RuntimeError('Lift arrival/state mismatch; no retry.')
    if abs(after['external_axes']['E1']-robot['external_axes']['E1'])>.1:raise RuntimeError('Unexpected jaw position change.')
    print(json.dumps(dict(ok=True,final_pose=after['pose_mm'],e1=after['external_axes']['E1'],log=str(path)),indent=2))

if __name__=='__main__':main()
