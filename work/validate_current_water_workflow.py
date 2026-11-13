"""Read-only native catalog validation of the user's supplied 24-transfer setup.

Saves a local draft/preview only. No robot client, native writes, simulation,
approval or execution endpoints are exposed by this helper.
"""
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

from lacry_protocol_authoring import ProtocolAuthoring
from workflow_capabilities import compose_hotel


class CatalogOnly:
    def call(self,method,path):
        if method!='GET' or path not in ('labware/219','labware/128','labware/8'):
            raise RuntimeError('Only the three requested native catalog reads are permitted.')
        with urlopen('http://192.168.100.101/NimbusLite/api/v1/'+path,timeout=15) as response:
            return json.load(response)


sources=[row+str(col) for row in 'AB' for col in range(1,13)]
destinations=[row+str(col) for row in 'ABCD' for col in range(1,7)]
spec=dict(name='Water 30uL Cellvis96 to Cellvis24',plate_profile='Cellvis P24-1.5H-N',transported_plate_site=4,
    deck=[dict(site=3,labware_id=219),dict(site=4,labware_id=128),dict(site=6,labware_id=8)],
    tip_site=6,tip_wells=sources,
    initial_volumes=[dict(site=3,well=w,contents='water',volume_ul=350,minimum_remaining_ul=150) for w in sources]+
                    [dict(site=4,well=w,contents='empty',volume_ul=0,minimum_remaining_ul=0) for w in destinations],
    additions=[dict(source=dict(site=3,well=s),destination=dict(site=4,well=d),volume_ul=30,mix_after=False)
               for s,d in zip(sources,destinations)],pipetting=dict(aspirate_height_mm=2,dispense_height_mm=2))
author=ProtocolAuthoring(SimpleNamespace(backend=SimpleNamespace(instrument=CatalogOnly())))
draft=author.draft(spec)
ops=['retrieve_hotel','register_plate','deliver_hamilton','hamilton_protocol']
preview=dict(draft=draft,composition=compose_hotel(ops,spec['plate_profile'],1),
    plan_arguments=dict(operations=ops,plate_profile=spec['plate_profile'],source_slot=1,draft_id=draft['draft_id']),
    validation='Local compilation against native catalog only. Live readiness and approval still required.',
    height_reference='Internal well bottom, mm',liquid_class='Aqueous native speeds',total_ul=720,hardware_started=False)
path=Path(__file__).with_name('current_water_workflow_preview.json')
path.write_text(json.dumps(preview,indent=2),encoding='utf-8')
print(json.dumps(dict(draft_id=draft['draft_id'],transfers=len(draft['summary']),tips=draft['tips_required'],
    source_remaining_ul=sorted({x['volume_ul'] for x in draft['remaining_volumes'] if x['site']==3}),
    destination_final_ul=sorted({x['volume_ul'] for x in draft['remaining_volumes'] if x['site']==4}),
    final_location=preview['composition']['final']['plate_location'],hardware_started=False,preview=str(path))))
