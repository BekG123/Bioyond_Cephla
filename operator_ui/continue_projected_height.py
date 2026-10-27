"""Continue this explicitly supervised height transfer; stop on any failed step.

Uses only the bounded Flask pilot, preserving its image/arrival checks. No
enable/reset/recovery or retry commands; no alignment/descent/gripper actions.
"""
import argparse,json,time
from urllib.request import Request,urlopen

def call(endpoint,body=None):
    request=Request('http://127.0.0.1:5002'+endpoint,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=10) as response:return json.load(response)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-confirmed',action='store_true')
    parser.add_argument('--expected-start-z',type=float,default=270.008)
    args=parser.parse_args()
    if not args.execute_confirmed:raise RuntimeError('Explicit supervised execution required.')
    state=call('/state');robot=state['robot']
    expected=dict(X=280.3,Y=29.255,Z=args.expected_start_z,Rz=-3.889)
    if (not robot.get('connected') or not robot.get('ok') or robot.get('errors')
            or state['sequence']['active'] or any(abs(robot['pose_mm'][k]-v)>.1 for k,v in expected.items())):
        raise RuntimeError('Not at the verified first height-step endpoint.')
    last=call('/seq')
    if (last.get('name')!='projected_height_pilot' or not last.get('result',{}).get('ok')
            or not last['result'].get('pilot_verified')):
        raise RuntimeError('First height step has no successful live response verification.')
    for n in range(12):
        state=call('/state');robot=state['robot']
        if (not robot.get('connected') or not robot.get('ok') or robot.get('errors')
                or state['sequence']['active']):raise RuntimeError('Controller/sequence state changed.')
        pose=robot['pose_mm']
        if any(abs(pose[k]-expected[k])>.1 for k in ('X','Y','Rz')):
            raise RuntimeError('XY/wrist changed; stopping continuation.')
        reply=call('/seq/projected_height_pilot',dict(confirm=True,cell_clear=True,
            empty_gripper=True,same_support=True,expected_start=pose,reference_target_z=289.129))
        if not reply.get('ok'):raise RuntimeError(str(reply))
        deadline=time.monotonic()+75
        while True:
            time.sleep(.5);seq=call('/seq')
            if seq.get('name')!='projected_height_pilot':raise RuntimeError('Sequence ownership changed.')
            if not seq['active']:break
            if time.monotonic()>deadline:
                # No further request is sent. The bounded server pilot owns
                # its current operation; this client never retries it.
                raise RuntimeError('Height pilot has not returned; inspect its status, no further moves sent.')
        r=seq.get('result') or {}
        print(json.dumps({k:r.get(k) for k in ('ok','error','motion_requested','height_reference_reached','final_pose','scale_response','log_file')}),flush=True)
        if not r.get('ok'):raise RuntimeError('Height step failed; stopped without retry.')
        expected=r['final_pose']
        if r.get('height_reference_reached') and not r.get('motion_requested'):
            print('Final stationary height-reference verification passed.',flush=True);return
    raise RuntimeError('Expected height transfer did not finish; no further motion sent.')

if __name__=='__main__':main()
