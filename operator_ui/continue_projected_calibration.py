"""Explicitly supervised bounded pilot continuation; stops on any failure.

No resets, enabling, recovery, automatic retries, alignment or grip commands.
Every move remains owned, checked and logged by the existing Flask pilot.
"""
import argparse,json,time
from urllib.request import Request,urlopen

def call(endpoint,body=None):
    req=Request('http://127.0.0.1:5002'+endpoint,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=10) as response:return json.load(response)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-confirmed',action='store_true')
    parser.add_argument('--phase',choices=['xy','height'],required=True)
    parser.add_argument('--height-reference',action='store_true')
    parser.add_argument('--expected-start',type=float,nargs=4,required=True,metavar=('X','Y','Z','RZ'))
    args=parser.parse_args()
    if not args.execute_confirmed:raise RuntimeError('Explicit supervised execution required.')
    expected=dict(zip(('X','Y','Z','Rz'),args.expected_start))
    name='projected_disk_pilot' if args.phase=='xy' else 'projected_height_pilot'
    for step in range(24 if args.phase=='xy' else 14):
        s=call('/state');r=s['robot']
        if not r.get('connected') or not r.get('ok') or r.get('errors') or s['sequence']['active']:
            raise RuntimeError('Healthy idle controller required; no automatic recovery.')
        pose=r['pose_mm']
        if any(abs(pose[k]-v)>.1 for k,v in expected.items()):raise RuntimeError('Start changed; no movement.')
        body=dict(confirm=True,cell_clear=True,empty_gripper=True,expected_start=pose)
        if args.phase=='xy':
            body.update(tracking_mode='height_referenced_grid' if args.height_reference else 'anchored_grid',burst_frames=5,finish_centering=True,scale_search=True)
        else:body.update(same_support=True,reference_target_z=289.129)
        result=call('/seq/'+name,body)
        if not result.get('ok'):raise RuntimeError(str(result))
        deadline=time.monotonic()+100
        while True:
            time.sleep(.6);seq=call('/seq')
            if seq.get('name')!=name:raise RuntimeError('Sequence ownership changed.')
            if not seq['active']:break
            if time.monotonic()>deadline:raise RuntimeError('Pilot still active; no additional commands sent.')
        result=seq.get('result') or {}
        print(json.dumps(dict(step=step+1,phase=args.phase,ok=result.get('ok'),error=result.get('error'),
            pose=result.get('final_pose'),xy_error=result.get('after',{}).get('error_xy_mm'),
            wells=result.get('after',{}).get('tracking',{}).get('supported_wells'),
            centered=result.get('xy_centered'),height_reached=result.get('height_reference_reached'),
            log=result.get('log_file'))),flush=True)
        if not result.get('ok'):raise RuntimeError('Pilot failed; stopped without retry.')
        expected=result['final_pose']
        if result.get('xy_centered') or (result.get('height_reference_reached') and not result.get('motion_requested')):
            return
    raise RuntimeError('Phase has not finished; review before continuing.')

if __name__=='__main__':main()
