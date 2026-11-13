"""Create/inspect a native transport protocol. Never starts a protocol run."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from hamilton_prep import HamiltonPrep, digest

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare',action='store_true',required=True)
    parser.add_argument('--resume',type=Path)
    parser.add_argument('--declare-destination',action='store_true')
    parser.add_argument('--reference-only',action='store_true',help='Prepare a simulator reference returning the plate to its original site 4')
    args=parser.parse_args()
    if args.reference_only and (args.resume or args.declare_destination):
        raise RuntimeError('Reference preparation must use a new draft')
    h=HamiltonPrep();state=h.preflight(initialized=True)
    if state['serial']!='PRPGJ2494':raise RuntimeError('Wrong Hamilton')
    if args.declare_destination:
        if not args.resume:raise RuntimeError('Existing draft folder required')
        folder=args.resume
        identity=json.loads((folder/'identity.json').read_text())
        pid=identity['id'];protocol=h.call('GET',f'protocols/{pid}')
        if protocol['name']!=identity['name']:raise RuntimeError('Draft changed')
        body=json.loads((folder/'preparation.json').read_text())['protocol_request']['deck']
        body['id']=protocol['deck']['id']
        source=protocol['deck']['positions'][3]
        body['positions'][3]['id']=source['id']
        body['positions'][3]['labwareGroup']['id']=source['labwareGroup']['id']
        body['positions'][2]['labwareGroup']=dict(body['positions'][3]['labwareGroup'])
        body['positions'][2]['positionName']='Receiving site 3'
        output=folder/'destination_layout_request.json'
        if output.exists():raise RuntimeError('Destination layout edit already attempted')
        output.write_text(json.dumps(body,indent=2),encoding='utf-8')
        response=h.call('PUT',f'deck/{pid}',body)
        (folder/'destination_layout_response.json').write_text(json.dumps(response,indent=2),encoding='utf-8')
        updated=h.call('GET',f'protocols/{pid}')
        (folder/'protocol_destination.json').write_text(json.dumps(updated,indent=2),encoding='utf-8')
        valid=h.call('GET',f'protocols/validate/{pid}')
        (folder/'validation_destination.json').write_text(json.dumps(valid,indent=2),encoding='utf-8')
        print(json.dumps(dict(protocol_id=pid,steps=updated['steps'],validation=valid)))
        return
    plate=h.call('GET','labware/226')
    if plate['name']!='P96w370fn1rjFAL' or plate['classification']!='plate':
        raise RuntimeError('Confirmed Falcon plate definition changed')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder=args.resume or h.folder/('plate_transfer_'+stamp)
    if args.resume:
        if not (folder/'created.json').is_file() or (folder/'step_response.json').exists():
            raise RuntimeError('Resume only a created protocol before its step was added')
    else:folder.mkdir()
    def save(name,value):
        (folder/name).write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')
    deck=[]
    for site in range(1,9):
        group=(dict(labwareId=226,groupName='Falcon 96-well lid-off plate',
            reuseTipsBetweenSteps=False,liquidName='Not used in transport',
            liquidType='Water',liquidVolumeOptions='SamePerContainer') if site==4 else None)
        deck.append(dict(position=site,positionName='Site '+str(site),
            labwarePositions=[],labwareGroup=group,liquidVolume=0))
    name=('SIMULATION ONLY gripper reference 4 to 4 ' if args.reference_only else 'Lacry plate transfer 4 to 3 ')+stamp
    body=dict(name=name,makeNameUnique=False,
        skipValidation=False,deck=dict(positions=deck))
    if args.resume:
        body=json.loads((folder/'preparation.json').read_text())['protocol_request']
    else:
        save('preparation.json',dict(operator_confirmed='Falcon 96-well plate, lid off at site 4',
            initial_state=state,plate=plate,plate_sha256=digest(plate),protocol_request=body,
            hardware_motion_authorized=False))
        created=h.call('POST','protocols',body);save('created.json',created)
    matches=[p for p in h.call('GET','protocols') if p['name']==body['name']]
    if len(matches)!=1:raise RuntimeError('Created protocol identity not unique')
    pid=matches[0]['id'];save('identity.json',matches[0])
    end=4 if args.reference_only else 3
    step=dict(stepType='TransportStep',name=f'Move plate from site 4 to site {end}',
        stepOrder=1,makeNameUnique=False,disabled=False,startPosition=4,endPosition=end)
    save('step_request.json',step)
    result=h.call('POST',f'protocols/{pid}/step',step);save('step_response.json',result)
    protocol=h.call('GET',f'protocols/{pid}');save('protocol.json',protocol)
    valid=h.call('GET',f'protocols/validate/{pid}');save('validation.json',valid)
    print(json.dumps(dict(folder=str(folder),protocol_id=pid,name=protocol.get('name'),
        steps=protocol.get('steps'),validation=valid,hardware_motion_sent=False)),flush=True)

if __name__=='__main__':main()
