"""Prepare exact forward/reverse speed research trials; no hardware writes."""
import argparse
import hashlib
import json
from pathlib import Path
from trajectory_queue import prepare_points

HERE=Path(__file__).resolve().parent
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--speed',type=int,choices=(47,55,70,80,100,130,137),default=47)
    speed=parser.parse_args().speed;protocol={47:220102,55:220103,70:220104,80:220105,100:220106,130:220107,137:220108}[speed]
    root=HERE/'reports/trajectory_smoothing'
    raw=(root/'entry_forward_3mm/candidate.json').read_bytes();candidate=json.loads(raw)
    ident=hashlib.sha256(raw).hexdigest()
    data=json.loads((HERE/'demonstrations/return_home_20261016_130748/return_path.json').read_text())
    cfg=json.loads((HERE/'robot_params.json').read_text())
    route=candidate['routes']['to_hamilton'];vertices=[route['start']]+route['points']
    for direction in ('toward_home','to_hamilton'):
        reverse=direction=='toward_home';first=data['trajectory'][0 if reverse else -1]
        path=list(reversed(vertices)) if reverse else vertices
        prepare_points(first['pose_mm'],first['joints'],path[1:],cfg,reviewed=True,
                       forward_entry=not reverse,reverse_entry=reverse)
        folder=root/(f'entry_speed{speed}_'+direction)
        if (folder/'candidate.json').exists():raise RuntimeError('Preserve existing trial '+str(folder))
        folder.mkdir(parents=True,exist_ok=True);(folder/'candidate.json').write_bytes(raw)
        permission=dict(path_sha256=ident,source_sha256=candidate['source_sha256'],
                        direction=direction,speed=speed,attempt_available=True,allow_explicit_repeats=False,
                        clearance_approved=True,workspace_box_exception=True,status=f'awaiting_lua_{protocol}',
                        authorization={47:'Run it at speed 47, both ways, for research purposes',55:"Let's attempt 55",70:"Let's attempt 70 since 55 was broken record",80:"Let's attempt 80",100:"Let's attempt 100 as a final experiment. Just trying to see the relationship between speed and time here.",130:"Let's try 130",137:"Let's do final experimetn 137 because achieving 10s would be great in itself"}[speed],
                        baseline_trial=(('trial_65856_65919.json' if reverse else 'trial_66010_66071.json') if speed==137 else ('trial_63245_63321.json' if reverse else 'trial_63408_63484.json') if speed==130 else ('trial_61675_61766.json' if reverse else 'trial_61841_61932.json') if speed==100 else
                                        ('trial_59988_60089.json' if reverse else 'trial_60158_60260.json') if speed==80 else
                                        ('trial_57862_57990.json' if reverse else 'trial_58084_58211.json') if speed==70 else
                                        ('trial_54961_55106.json' if reverse else 'trial_55210_55355.json') if speed==55 else 'trial_50239_50407.json'),required_protocol=protocol,
                        note='Same refined geometry, exact reversal; previous supervised clearance context retained.')
        (folder/'replay_permission.json').write_text(json.dumps(permission,indent=2),encoding='utf-8')
        print(json.dumps(dict(variant=folder.name,path_id=ident,direction=direction,speed=speed)))

if __name__=='__main__':main()
