"""Offline alternatives for the operator's Z77 rack-clearance correction."""
import sys,json,hashlib
from pathlib import Path
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'operator_ui'))
from hamilton_opposite_wrist_route import PLAN
from plan_short_side_hamilton import validate
from autonomy import check_path
p=json.loads(PLAN.read_bytes());r=p['routes']['forward'];old=r['points']
choices={
 'all_turns_z77':[dict(v,Z=77.) for v in old[:4]]+[deepcopy(old[-1])],
 'final_turn_z77':deepcopy(old[:3])+[dict(old[2],Z=77.),dict(old[3],Z=77.),deepcopy(old[-1])],
}
out=dict(motion_sent=False,parent=str(PLAN),parent_sha256=hashlib.sha256(PLAN.read_bytes()).hexdigest(),candidates={})
for name,points in choices.items():
    c=dict(points=points,segment_speeds=[137]*(len(points)-1)+[5],hardware_tested=False)
    try:
        q=deepcopy(r['start_joints']);previous=r['start']
        for end in points:q=check_path(previous,end,q,p['config'],p['station_envelope']);previous=end
        c['forward']=validate(r['start'],points,r['start_joints'],p['config'],p['station_envelope'],r['validation']['endpoint_joints'])
        c['reverse']=validate(points[-1],list(reversed([r['start']]+points))[1:],c['forward']['endpoint_joints'],p['config'],p['station_envelope'],r['start_joints'])
        c['valid']=c['forward']['workspace_valid'] and c['reverse']['workspace_valid']
    except Exception as e:c.update(valid=False,error=str(e))
    out['candidates'][name]=c
    print(json.dumps(dict(name=name,valid=c['valid'],error=c.get('error'),points=points,length_mm=c.get('forward',{}).get('length_mm'))))
output=ROOT/'work/hamilton_z77_alternatives.json';output.write_text(json.dumps(out,indent=2));print(output)
