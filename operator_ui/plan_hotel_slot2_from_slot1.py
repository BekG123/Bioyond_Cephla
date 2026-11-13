"""Offline slot2 candidate from the stopped taught endpoint and accepted slot1.

No robot connection, motion dispatch or global envelope changes.
"""
import hashlib
import argparse
import json
import time
from copy import deepcopy
from pathlib import Path
from autonomy import check_path,TransferError
from plan_short_side_hamilton import validate
from hotel_slot_trial import reference
from run_hotel_slot1_workflow import load_workflow,digest

ROOT=Path(__file__).resolve().parents[1]
CAPTURE=ROOT/'operator_ui/reports/plate_session/hotel_slot2_loaded_teaching_20261111_234954/endpoint_capture.json'
OUTPUT=CAPTURE.parent/'slot2_candidate_v1.json'
SLOT3_CORRECTION=CAPTURE.parent/'slot3_height_correction_v2.json'
KEYS=('X','Y','Z','Rz')

def build(slot=2):
    if slot not in (2,3,4):raise TransferError('Only taught slot2 and derived slots3/4 are supported.')
    raw=CAPTURE.read_bytes();capture=json.loads(raw);samples=capture['samples']
    if len(samples)<3 or any(s['native']['moving'] or s['state']['sequence']['active'] for s in samples):
        raise TransferError('Stopped endpoint samples required.')
    end={k:samples[-1]['state']['robot']['pose_mm'][k] for k in KEYS}
    if any(max(s['state']['robot']['pose_mm'][k] for s in samples)-min(s['state']['robot']['pose_mm'][k] for s in samples)>.05 for k in KEYS):
        raise TransferError('Endpoint moved during capture.')
    workflow,plans=load_workflow();d=deepcopy(plans['deliver']);r=deepcopy(plans['retrieve'])
    old=plans['deliver']['routes']['deliver']['points'][-1]
    taught_end=dict(end)
    pitch=round(taught_end['Z']-old['Z'],3)
    end=dict(end,Z=round(taught_end['Z']+(slot-2)*pitch,3))
    if slot==3 and SLOT3_CORRECTION.exists():
        correction=json.loads(SLOT3_CORRECTION.read_bytes())
        original=CAPTURE.parent/'slot3_candidate_v1.json'
        if (correction.get('slot')!=3 or correction.get('endpoint_z_offset_mm')!=1.0
                or correction.get('source_sha256')!=hashlib.sha256(original.read_bytes()).hexdigest()):
            raise TransferError('Slot3 height correction changed or lost its original candidate binding.')
        end=dict(end,Z=round(end['Z']+correction['endpoint_z_offset_mm'],3))
    low_z=d['routes']['deliver']['points'][4]['Z']
    outside_x=d['routes']['deliver']['points'][4]['X']
    low=dict(end,X=outside_x,Z=low_z);high=dict(low,Z=end['Z'])
    forward=d['routes']['deliver']['points']
    # Keep the tested lower turn/exit corridor exactly; adjust pose only at
    # the outside low waypoint before the vertical rise and horizontal entry.
    forward[-3:]=[low,high,end]
    back=d['routes']['return'];back['start']=end;back['points'][:2]=[high,low]
    r['routes']['approach']['points']=deepcopy(forward[1:])
    lift=dict(end,Z=round(end['Z']+5,3))
    r['routes']['lift'].update(start=end,points=[lift])
    r['routes']['return'].update(start=lift,points=[dict(high,Z=lift['Z'])]+deepcopy(back['points'][1:]))
    base,_=reference();validation={};blockers=[]
    for label,g in [('delivery',d),('retrieval',r)]:
        q=deepcopy(base['start_joints'])
        for name,route in g['routes'].items():
            previous=route['start'];offset=q['J1']-previous['Z'];initial=deepcopy(q)
            # Validate the rounded points that the Lua serializer would use.
            points=[{k:round(p[k],2) for k in KEYS} for p in route['points']]
            for p in points:
                q=check_path(previous,p,q,g['cfg'],None);q['J1']=p['Z']+offset;previous=p
            v=validate(route['start'],points,initial,g['cfg'],g['envelope'],q)
            for issue in v['workspace_violations']:
                p=issue['pose']
                if (set(issue['outside'])!={'X'} or not outside_x-.01<=p['X']<200 or
                    not -139.43<=p['Y']<=-114.98 or not low_z-.01<=p['Z']<=lift['Z']+.01 or
                    not min(old['Rz'],end['Rz'])-.01<=p['Rz']<=max(old['Rz'],end['Rz'])+.01):
                    reason='Candidate leaves the proposed bounded outside corridor: '+','.join(sorted(issue['outside']))
                    if reason not in blockers:blockers.append(reason)
            route['expected']=q;validation[label+'_'+name]=v
            if (label,name)==('delivery','deliver'):
                measured=dict(samples[-1]['state']['robot']['joints'])
                measured['J1']+=end['Z']-taught_end['Z']
                if max(abs(q[k]-measured[k]) for k in q)>.5:raise TransferError('Taught endpoint winding mismatch.')
    # Emit phases, not executable slot1 identities or stale nested geometry.
    return dict(schema='cephla.hotel-slot-candidate.v1',at=time.time(),slot=slot,
        status=('blocked_workspace_limit' if blockers else 'offline_ik_validated_pending_physical_trial'),execution_enabled=False,
        blockers=blockers,slot_pitch_mm=pitch,endpoint_source=('directly_taught' if slot==2 else 'operator_confirmed_vertical_spacing_from_slot2'),
        taught_slot2_endpoint=taught_end,delta_from_slot2={k:round(end[k]-taught_end[k],3) for k in KEYS},
        endpoint=end,delta_from_slot1={k:round(end[k]-old[k],3) for k in KEYS},
        capture=str(CAPTURE.relative_to(ROOT)),capture_sha256=hashlib.sha256(raw).hexdigest(),
        source_workflow=workflow['id'],source_geometry_sha256={k:digest(v) for k,v in plans.items()},
        station_coordinate_plate_independent=True,grip_profile_scope='48-well accepted long-side profile; other plates require their accepted grip/clearance profile',
        delivery_routes=d['routes'],retrieval_routes=r['routes'],validation=validation,
        original_global_envelope=d['envelope'],global_limits_changed=False,
        notes=['Exact taught XY/yaw retained, not a pure Z translation.',
               'HOME pickup/seating and lower turning corridor unchanged.',
               'Higher outside rise, horizontal entry/exit20, other travel137; proof lift5mm at5.',
               'Physical loaded sweep/slot overhead clearance and bound runtime adapter remain to be validated.'])

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--slot',type=int,choices=[2,3,4],default=2)
    args=parser.parse_args();p=build(args.slot)
    output=CAPTURE.parent/f'slot{args.slot}_candidate_v1.json'
    with output.open('x',encoding='utf8') as f:json.dump(p,f,indent=2);f.write('\n')
    print(json.dumps(dict(saved=str(output),endpoint=p['endpoint'],status=p['status'],blockers=p['blockers'],motion_sent=False)))
