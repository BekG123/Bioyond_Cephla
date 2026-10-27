"""Select the already successful repeat-1 placement, with fresh vision; no motion."""
import json
import math
import time
import argparse
import projected_pickup as p
from projected_alignment import target_from_mark, perception_at_height
from proof_lift_plate import api, near, write
from autonomy import wrap

FOLDER=p.ROOT/'operator_ui/reports/projected_alignment'
OUT=FOLDER/'squid_retry_reference_20261027T1136.json'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    source=FOLDER/'reseated_repeat1_accepted_profile_20261027.json'
    profile,digest=p.load(source)
    if digest!='9bc3a4319cbb3f8df7804879f9f0ce81a3200c9297d84a85f690b29e7ec5e054':
        raise RuntimeError('Accepted repeat-1 profile changed.')
    p.accepted_grip(profile)
    batch=json.loads((FOLDER/'three_repeat_batch_20261027.json').read_bytes())
    if batch['repetitions'][0]['plate_retained_during_lift_and_home_operator_confirmed'] is not True:
        raise RuntimeError('Successful repeat-1 pickup evidence required.')
    prepared=json.loads((FOLDER/'prepared_squid_retry_20261027T1136.json').read_bytes())
    if time.time()-prepared['timestamp']>600:raise RuntimeError('Preparation expired.')
    prior=json.loads((FOLDER/'prepared_repeat1_reseated_3p9_20261027.json').read_bytes())['route']['target']
    perception,_,_=perception_at_height()
    targets=[target_from_mark(prepared['start'],m,perception.cfg) for m in prepared['measurements']]
    deltas=[dict(xy_mm=math.hypot(t['x']-prior['x'],t['y']-prior['y']),yaw_deg=abs(wrap(t['rz']-prior['rz']))) for t in targets]
    if any(d['xy_mm']>.5 or d['yaw_deg']>.2 for d in deltas):
        raise RuntimeError('New placement outside the existing reuse limits.')
    state=api('state');r=state['robot']
    if (not r.get('ok') or not r.get('connected') or r.get('errors') or state['sequence']['active']
            or r['program_state']['state']!='running' or r['control_mode']['mode']!='auto'):
        raise RuntimeError('Healthy idle Auto required.')
    near(r['pose_mm'],prepared['start'],.1)
    current,old_digest=p.load()
    if old_digest!='b417c0a99452b4cfa721475d9d6d7792f8fbad73dee86f29fce0ea2111a72d8e':
        raise RuntimeError('Active profile unexpectedly changed.')
    record=dict(at=time.time(),operator_request='Try again',hardware_commands_sent=False,
        source=str(source.relative_to(p.ROOT)),source_sha256=digest,previous_profile_sha256=old_digest,
        prepared='operator_ui/reports/projected_alignment/prepared_squid_retry_20261027T1136.json',
        reference_deltas=deltas,limits=dict(xy_mm=.5,yaw_deg=.2),
        endpoint=profile['candidate_endpoint'],basis='Reuse exact operator-accepted successful repeat-1 endpoint; no new offsets or relaxed limits.',applied=args.apply)
    if args.apply:
        if OUT.exists():raise RuntimeError('Selection already attempted.')
        write(OUT,record)
        backup=OUT.with_name(OUT.stem+'_previous_profile.json')
        if backup.exists():raise RuntimeError('Backup already exists.')
        backup.write_bytes(p.PROFILE.read_bytes())
        temp=p.PROFILE.with_suffix('.tmp');temp.write_bytes(source.read_bytes());temp.replace(p.PROFILE)
        p.load();p.accepted_grip(profile)
    print(json.dumps(record))

if __name__=='__main__':main()
