"""Supervised stages of the recorded 48-well open-claw repeat; no grip/reset/retry."""
import argparse
import json
import math
import time
from urllib.request import Request, urlopen
import projected_pickup as p
from autonomy import check_path, ensure_arrival, wrap

DIGEST='cc8114594945f0a0a94753a62f704fee402a8d30beb6d5331152438736c5c695'
EVEN_DIGEST='206046760fcd8d1a8a42a951e7fb198e1e3572a761a228a5c7f8c3b2c8d0748f'
ACCEPTED_3P9_DIGEST='07e3b67d814a325a4c80f3512b0a1bcb037b53ac53fc4463abec24a6b2ba3cb2'
RESEATED_3P9_DIGEST='9bc3a4319cbb3f8df7804879f9f0ce81a3200c9297d84a85f690b29e7ec5e054'
RESTORED_3P9_DIGEST='b417c0a99452b4cfa721475d9d6d7792f8fbad73dee86f29fce0ea2111a72d8e'
FOLDER=p.ROOT/'operator_ui/reports/projected_alignment'


def call(path, body=None):
    request=Request('http://127.0.0.1:5002'+path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=60) as response:
        result=json.load(response)
    if result.get('ok') is False:raise p.TransferError(str(result))
    return result


def healthy():
    s=call('/state');r=s['robot']
    if (not r.get('connected') or not r.get('ok') or r.get('errors') or s['sequence']['active']
            or not r.get('enabled') or r['program_state']['state']!='running' or not s['envelope']['enabled']):
        raise p.TransferError('Healthy idle enabled running controller required; no automatic recovery.')
    return s


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['observation','alignment','correction','descent'])
    parser.add_argument('--prepared')
    parser.add_argument('--reference',choices=['manual','even-spacing','accepted-3p9','accepted-reseated','accepted-restored'],default='manual')
    parser.add_argument('--execute-confirmed',action='store_true')
    args=parser.parse_args()
    if not args.execute_confirmed:raise p.TransferError('Supervised execution must be explicitly requested.')
    profile,digest=p.load()
    expected_digest=EVEN_DIGEST if args.reference=='even-spacing' else DIGEST
    if args.reference in ('accepted-3p9','accepted-reseated','accepted-restored'):
        expected_digest=RESEATED_3P9_DIGEST if args.reference=='accepted-reseated' else ACCEPTED_3P9_DIGEST
        if args.reference=='accepted-restored':expected_digest=RESTORED_3P9_DIGEST
        if not p.accepted_grip(profile):raise p.TransferError('Accepted 3.9 mm grip evidence required.')
    if digest!=expected_digest:raise p.TransferError('Taught profile changed.')
    s=healthy();r=s['robot'];cfg=json.loads((p.ROOT/'operator_ui/robot_params.json').read_bytes())
    env={k:(s['envelope'][k]['min'],s['envelope'][k]['max']) for k in ('X','Y','Z')}
    events=[]
    out=FOLDER/('manual_repeat_'+args.phase+'_'+str(time.time_ns())+'.json')
    def record(event,**data):
        events.append(dict(at=time.time(),event=event,**data))
        out.write_text(json.dumps(dict(profile_sha256=digest,events=events),indent=2),encoding='utf-8')
    record('start',state=s)
    try:
        points=[];endpoint=None;body=None
        if args.phase=='observation':
            ensure_arrival(r['pose_mm'],dict(X=289.97,Y=62.63,Z=248.02,Rz=-3.88))
            points=[dict(X=289.97,Y=62.63,Z=289.129,Rz=-3.88),
                    dict(X=279.303,Y=26.358,Z=289.129,Rz=-3.88)]
        elif args.phase=='alignment':
            prepared=json.loads((p.ROOT/args.prepared).read_bytes())
            ensure_arrival(r['pose_mm'],prepared['start'])
            endpoint='/seq/projected_alignment'
            body=dict(confirm=True,cell_clear=True,empty_gripper=True,
                      expected_start=prepared['start'],expected_target=prepared['route']['target'])
        elif args.phase=='correction':
            seq=call('/seq')
            if seq['name']!='projected_alignment' or seq['state']!='done' or not seq['result']['ok']:
                raise p.TransferError('Fresh successful projected alignment required.')
            target=seq['result']['route']['target']
            ensure_arrival(r['pose_mm'],dict(X=target['x'],Y=target['y'],Z=300.,Rz=target['rz']))
            # Same plate placement as the camera estimate preceding manual teaching.
            if args.reference=='accepted-reseated':
                prior=json.loads((FOLDER/'prepared_repeat1_reseated_3p9_20261027.json').read_bytes())['route']['target']
            elif args.reference in ('even-spacing','accepted-3p9','accepted-restored'):
                source=json.loads((FOLDER/'alignment_outward_trial_20261027.json').read_bytes())['source_alignment_pose']
                prior=dict(x=source['X'],y=source['Y'],rz=source['Rz'])
            else:
                prior=json.loads((FOLDER/'prepared_forward_lower_alignment_20261027.json').read_bytes())['route']['target']
            if (math.hypot(target['x']-prior['x'],target['y']-prior['y'])>.5
                    or abs(wrap(target['rz']-prior['rz']))>.2):
                raise p.TransferError('Plate placement changed; do not reuse absolute taught alignment.')
            record('fresh_alignment',result=seq['result'])
            points=[profile['alignment_pose_mm']]
        else:
            ensure_arrival(r['pose_mm'],profile['alignment_pose_mm'])
            endpoint='/seq/projected_descent_trial'
            body=dict(ready=True,empty_gripper=True,cell_clear=True,plate_unchanged=True,
                      expected_profile_sha256=digest)
            if args.reference in ('accepted-3p9','accepted-reseated','accepted-restored'):
                # Normal accepted descent issues a fresh plate-specific Grip
                # receipt; it does not fabricate a new visual acceptance.
                endpoint='/researcher/api/descent/start'
                body=dict(ready=True)
        pose,joints=r['pose_mm'],r['joints']
        for point in points:
            joints=check_path(pose,point,joints,cfg,env);pose=point
        for point in points:
            healthy()
            record('move_requested',target=point,speed=5)
            response=call('/move',dict(x=point['X'],y=point['Y'],z=point['Z'],rz=point['Rz'],speed=5,interpolation='linear'))
            after=healthy();ensure_arrival(after['robot']['pose_mm'],point)
            record('move_arrived',response=response,state=after)
        if endpoint:
            record('sequence_requested',endpoint=endpoint,body=body)
            response=call(endpoint,body);record('sequence_started',response=response)
            deadline=time.monotonic()+180
            expected='projected_alignment' if args.phase=='alignment' else 'researcher_descend'
            while True:
                time.sleep(.5);seq=call('/seq')
                if seq['name']!=expected:raise p.TransferError('Sequence owner changed.')
                if not seq['active']:break
                if time.monotonic()>deadline:raise p.TransferError('Sequence still active; no further commands sent.')
            record('sequence_finished',sequence=seq)
            if not (seq.get('result') or {}).get('ok'):raise p.TransferError(str(seq.get('result')))
        final=healthy();record('completed',state=final)
        print(json.dumps(dict(ok=True,phase=args.phase,pose=final['robot']['pose_mm'],
                              e1=final['robot']['external_axes']['E1'],report=str(out))))
    except Exception as error:
        record('stopped',error=str(error));raise


if __name__=='__main__':main()
