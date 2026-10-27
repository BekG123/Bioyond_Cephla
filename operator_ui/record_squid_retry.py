"""Read-only hardware snapshots for the October 27 supervised Squid retry."""
import argparse,json,time
from projected_pickup import ROOT,load
from proof_lift_plate import api

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['proposal','stopped'])
    args=parser.parse_args()
    profile,digest=load()
    record=dict(at=time.time(),phase=args.phase,request='Retry full 48-well calibration and Squid drop-off/pickup trial.',
        operator_confirmation='Repaired Squid holder empty at taught loading position; route clear, hands clear and E-stop supervised. Stop for seating inspection before release.',
        profile_sha256=digest,profile=profile,state=api('state'),sequence=api('seq'),
        lacry=api('researcher/api/lacry/state'),audit=api('audit/status'),
        transit_speed=137,final_descent_speed=10,grip_setting_mm=3.9,
        seating_accepted=False,release_executed=False,pickup_executed=False,
        retention_operator_confirmed=False)
    path=ROOT/f'operator_ui/reports/projected_alignment/squid_retry_20261027T1136_{args.phase}.json'
    with path.open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    print(json.dumps(dict(record=str(path),pose=record['state']['robot'].get('pose_mm'),sequence_state=record['sequence']['state'])))

if __name__=='__main__':main()
