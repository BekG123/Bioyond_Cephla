"""Read Hamilton labware geometry without guessing heights from well count."""
import hashlib
import io
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

NS={'l':'Hamilton.XRP2.Labware','p':'http://schemas.datacontract.org/2004/07/Hamilton.XRP2.Instrument'}
ROOT=Path(__file__).resolve().parent

def read_export(path):
    payload=Path(path).read_bytes()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names=[n for n in archive.namelist() if n.endswith('.hamLabware')]
        if len(names)!=1: raise ValueError('Ambiguous labware export')
        name=names[0];nested=archive.read(name)
    with zipfile.ZipFile(io.BytesIO(nested)) as archive:
        documents=[json.loads(archive.read(n)) for n in archive.namelist() if n.endswith('.json')]
        documents=[d for d in documents if isinstance(d,dict) and isinstance(d.get('Content'),dict)
                   and isinstance(d['Content'].get('Data'),str)]
        if len(documents)!=1: raise ValueError('Ambiguous labware definition')
        document=documents[0]
    outer=ET.fromstring(document['Content']['Data'])
    root=ET.fromstring(next(e for e in outer.iter() if e.tag.endswith('SerializedLabware')).text)
    def number(parent,path): return float(parent.find(path,NS).text)
    segments=[]
    for segment in root.find('l:StackedSegments',NS):
        value=list(segment)[1]
        geometry=value.find('l:GeometricSegment',NS)
        z=number(value,'l:CoordinateTransform/l:Translation/p:_dZ')
        height=number(geometry,'l:Height')
        if geometry.find('l:Width',NS) is not None:
            xb=xt=number(geometry,'l:Width');yb=yt=number(geometry,'l:Length')
        else:
            xb=number(geometry,'l:BottomWidth');xt=number(geometry,'l:TopWidth')
            yb=number(geometry,'l:BottomLength');yt=number(geometry,'l:TopLength')
        segments.append(dict(bottom_z=z-height/2,top_z=z+height/2,
                             bottom_x=xb,top_x=xt,bottom_y=yb,top_y=yt))
    minimum=min(s['bottom_z'] for s in segments);maximum=max(s['top_z'] for s in segments)
    labels={}
    for label in root.find('l:LabeledPoints',NS):
        tag_values=[e.text for e in label.findall('.//l:Value',NS)]
        for tag in tag_values:
            if tag in ('WideGripPoint','NarrowGripPoint'):
                labels[tag]=number(label,'l:Point/p:_dZ')
    if set(labels)!= {'WideGripPoint','NarrowGripPoint'} or abs(labels['WideGripPoint']-labels['NarrowGripPoint'])>.01:
        raise ValueError('Review differing/missing grip labels')
    grip=labels['NarrowGripPoint']
    section=[s for s in segments if s['bottom_z']<=grip<=s['top_z']]
    if len(section)!=1: raise ValueError('Grip is not within one body section')
    section=section[0];t=(grip-section['bottom_z'])/(section['top_z']-section['bottom_z'])
    width=section['bottom_y']+t*(section['top_y']-section['bottom_y'])
    grid=root.find('l:IndexedHoleGrids',NS)
    holes=next(e for e in grid.iter() if e.find('l:XCount',NS) is not None)
    upper=max(segments,key=lambda s:s['top_z'])
    return dict(name=name.removesuffix('.hamLabware'),sha256=hashlib.sha256(payload).hexdigest(),
                height_mm=maximum-minimum,base_length_mm=max(max(s['bottom_x'],s['top_x']) for s in segments),
                base_width_mm=max(max(s['bottom_y'],s['top_y']) for s in segments),
                upper_length_mm=upper['top_x'],upper_width_mm=upper['top_y'],
                grip_above_bottom_mm=grip-minimum,grip_body_width_mm=width,
                columns=int(number(holes,'l:XCount')),rows=int(number(holes,'l:YCount')),
                pitch_mm=abs(number(holes,'l:DeltaX')),segments=segments)

def dcg_profile(plate48_export):
    reference_folder=ROOT/'reports/hamilton_api/native_transfer_evidence_20261108T104324Z'
    old=read_export(reference_folder/'falcon226_export.zip')
    commands=json.loads((reference_folder/'simulation_gripper_commands.json').read_text())
    picks=[v['message'][1] for v in commands if v.get('simulation') and v['message'][0]=='PickUpPlate']
    if len(picks)!=1: raise ValueError('Expected one vendor pickup reference')
    ref=picks[0]
    if abs(old['grip_body_width_mm']-ref['plateDimensions']['Width'])>.01:
        raise ValueError('Geometry section does not reproduce the vendor grip width')
    if abs(old['height_mm']-ref['plateDimensions']['Height'])>.01:
        raise ValueError('Geometry height does not reproduce the vendor command')
    support=ref['plateTopCenter']['ZPosition']-old['height_mm']
    offset=support+old['grip_above_bottom_mm']-ref['gripHeight']
    if abs(offset-2)>.01: raise ValueError('DCG grip-reference offset changed')
    plate=read_export(plate48_export)
    if (plate['name'],plate['rows'],plate['columns'])!=('P48w800kmmtjFAL',6,8):
        raise ValueError('Expected Falcon 48-well export')
    return dict(labware_id=166,plate=plate,tool_reference_offset_mm=offset,
                native_grip_above_support_mm=plate['grip_above_bottom_mm']-offset,
                reference_geometry_reproduces_vendor=True,
                offset_basis='Inferred from same DCG vendor-generated 96-well reference; first 48-well trial required',
                clearance_y_mm=ref['clearanceY'],grip_distance_mm=ref['gripDistance'],
                grip_speed_mm_s=ref['gripSpeedY'],physical_trial_complete=False)

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('export',type=Path)
    print(json.dumps(dcg_profile(p.parse_args().export),indent=2))
