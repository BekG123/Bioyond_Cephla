"""Deterministic independent-dilution compiler. No network, model or hardware writes."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re

from researcher_teaching import TeachingError


def obj(properties, required=None):
    return dict(type='object',properties=properties,required=list(properties) if required is None else required,
                additionalProperties=False)

NUMBER=dict(type='number')
ADDRESS=obj(dict(site=dict(type='integer',minimum=1,maximum=8),well=dict(type='string',pattern='^[A-H][1-9][0-9]?$')))
SPEC_SCHEMA=obj(dict(
    name=dict(type='string',minLength=1,maxLength=80),
    plate_profile=dict(type='string',enum=['Cellvis P24-1.5H-N']),
    transported_plate_site=dict(type='integer',enum=[4]),
    deck=dict(type='array',minItems=2,maxItems=8,items=obj(dict(site=dict(type='integer',minimum=1,maximum=8),labware_id=dict(type='integer',minimum=1)))),
    tip_site=dict(type='integer',minimum=1,maximum=8),
    tip_wells=dict(type='array',minItems=2,maxItems=96,items=dict(type='string'),uniqueItems=True),
    initial_volumes=dict(type='array',minItems=3,maxItems=96,items=obj(dict(site=dict(type='integer'),well=dict(type='string'),contents=dict(type='string',minLength=1,maxLength=200),volume_ul=NUMBER,minimum_remaining_ul=NUMBER))),
    dilutions=dict(type='array',minItems=1,maxItems=24,items=obj(dict(source=ADDRESS,diluent=ADDRESS,destination=ADDRESS,dilution_factor=NUMBER,final_volume_ul=NUMBER))),
    pipetting=obj(dict(aspirate_height_mm=NUMBER,dispense_height_mm=NUMBER,
        mix_volume_ul=NUMBER,mix_cycles=dict(type='integer',minimum=1,maximum=20),
        mix_speed=dict(type='integer',minimum=1),mix_height_mm=NUMBER)),
))

ADDITION_SCHEMA=deepcopy(SPEC_SCHEMA)
ADDITION_SCHEMA['properties'].pop('dilutions')
ADDITION_SCHEMA['required'].remove('dilutions')
ADDITION_SCHEMA['required'].append('additions')
ADDITION_SCHEMA['properties']['additions']=dict(type='array',minItems=1,maxItems=24,
    items=obj(dict(source=ADDRESS,destination=ADDRESS,volume_ul=NUMBER,mix_after=dict(type='boolean'))))
ADDITION_SCHEMA['properties']['tip_wells']['minItems']=1
ADDITION_SCHEMA['properties']['initial_volumes']['minItems']=2
ADDITION_SCHEMA['properties']['pipetting']['required']=['aspirate_height_mm','dispense_height_mm']
AUTHORING_SCHEMA=dict(oneOf=[SPEC_SCHEMA,ADDITION_SCHEMA])


def fail(message):
    raise TeachingError(message,400)


def number(value,label,minimum=0,maximum=None):
    if type(value) not in (int,float):fail(label+' must be a finite number.')
    try:result=Decimal(str(value))
    except InvalidOperation:fail(label+' must be finite.')
    if not result.is_finite() or result<minimum or (maximum is not None and result>maximum):
        fail(label+' is outside the supported range.')
    return result


def fields(value,keys,label):
    if not isinstance(value,dict) or set(value)!=set(keys):
        fail(label+' requires exactly: '+', '.join(keys)+'. Ask for missing details; do not guess.')


def address(well,labware):
    if not isinstance(well,str) or not re.fullmatch(r'[A-H][1-9][0-9]?',well):fail('Use a well label such as A5.')
    row,column=ord(well[0])-64,int(well[1:])
    if row>labware['rows'] or column>labware['columns']:fail('Well '+well+' does not exist on '+labware['displayName']+'.')
    if labware.get('disabledWells'):fail('Labware has disabled wells; this authoring version does not support it.')
    return dict(row=row,column=column)


def normalized(value):
    """Compare native readback while ignoring only server-generated IDs/metadata."""
    if isinstance(value,dict):return {k:normalized(v) for k,v in value.items() if k not in ('id','makeNameUnique')}
    if isinstance(value,list):return [normalized(x) for x in value]
    return value


def compile_spec(spec,labware):
    addition=isinstance(spec,dict) and 'additions' in spec
    fields(spec,(ADDITION_SCHEMA if addition else SPEC_SCHEMA)['properties'],'Liquid transfer specification')
    if not isinstance(spec['name'],str) or not 1<=len(spec['name'].strip())<=80:fail('Supply a short protocol name.')
    if spec['plate_profile']!='Cellvis P24-1.5H-N' or type(spec['transported_plate_site']) is not int or spec['transported_plate_site']!=4:
        fail('This first dilution workflow supports the Cellvis P24-1.5H-N at site 4 only.')
    if not isinstance(spec['deck'],list) or not 2<=len(spec['deck'])<=8:fail('Supply the deck labware.')
    deck={}
    for entry in spec['deck']:
        fields(entry,('site','labware_id'),'Deck entry')
        site,lid=entry['site'],entry['labware_id']
        if type(site) is not int or not 1<=site<=8 or site in deck or type(lid) is not int or lid<1:fail('Invalid or duplicate deck site.')
        native=labware.get(lid)
        if not native or native.get('id')!=lid:fail('Labware ID not in the inspected Hamilton catalog.')
        if native.get('classification') not in ('plate','tiprack'):fail('Only catalog plates and tip racks are supported.')
        deck[site]=native
    if 4 not in deck or deck[4].get('partNumbers')!='P24-1.5H-N' or (deck[4].get('rows'),deck[4].get('columns'))!=(4,6):
        fail('Site 4 must use the exact catalog Cellvis P24-1.5H-N definition.')
    tip_site=spec['tip_site']
    if type(tip_site) is not int or tip_site not in deck or deck[tip_site].get('partNumbers')!='235903' or deck[tip_site]['classification']!='tiprack':
        fail('Select the catalog 300 uL Framed Conductive Filtered tips (235903).')
    if any(w['classification']=='tiprack' and site!=tip_site for site,w in deck.items()):fail('Use one tip rack in this version.')
    capacity=number(deck[tip_site]['volume'],'Tip capacity',1)
    tips=spec['tip_wells']
    if not isinstance(tips,list) or not (1 if addition else 2)<=len(tips)<=96 or any(not isinstance(x,str) for x in tips) or len(set(tips))!=len(tips):fail('Supply distinct fresh tip wells.')
    tip_addresses=[address(w,deck[tip_site]) for w in tips]

    def location(value):
        fields(value,('site','well'),'Well address')
        site=value['site']
        if type(site) is not int or site not in deck or deck[site]['classification']!='plate':fail('Liquid address must name a plate on the deck.')
        address(value['well'],deck[site])
        return site,value['well']

    volumes={};reserve={}
    if not isinstance(spec['initial_volumes'],list) or not (2 if addition else 3)<=len(spec['initial_volumes'])<=96:fail('Supply initial liquid volumes, including zero for empty destinations.')
    for item in spec['initial_volumes']:
        fields(item,('site','well','contents','volume_ul','minimum_remaining_ul'),'Initial volume')
        if not isinstance(item['contents'],str) or not 1<=len(item['contents'].strip())<=200:fail('Name the contents of every liquid well; use empty for destination wells.')
        key=location({k:item[k] for k in ('site','well')})
        if key in volumes:fail('Duplicate initial well volume.')
        volumes[key]=number(item['volume_ul'],'Initial volume',0,deck[key[0]]['volume'])
        reserve[key]=number(item['minimum_remaining_ul'],'Minimum remaining volume',0,volumes[key])
    original=deepcopy(volumes)
    operations=spec['additions' if addition else 'dilutions']
    if not isinstance(operations,list) or not 1<=len(operations)<=24:fail('Supply 1–24 liquid transfers or independent dilutions.')
    pip=spec['pipetting'];all_fields=SPEC_SCHEMA['properties']['pipetting']['properties']
    mixing=not addition or any(not isinstance(x,dict) or x.get('mix_after') is not False for x in operations)
    if mixing:fields(pip,all_fields,'Pipetting settings')
    elif (not isinstance(pip,dict) or not {'aspirate_height_mm','dispense_height_mm'}<=set(pip) or set(pip)-set(all_fields)):
        fail('No-mix additions require aspiration and dispense heights; mixing settings may be omitted.')
    for k in ('aspirate_height_mm','dispense_height_mm'):number(pip[k],k,0,20)
    mix=0
    if mixing:
        number(pip['mix_height_mm'],'mix_height_mm',0,20)
        mix=number(pip['mix_volume_ul'],'Mix volume',1,capacity)
        if type(pip['mix_cycles']) is not int or not 1<=pip['mix_cycles']<=20:fail('Choose 1–20 mix cycles.')
        if type(pip['mix_speed']) is not int or not 1<=pip['mix_speed']<=1000:fail('Supply the native mixing speed (1–1000); native simulation must validate it.')
    rows=[];destinations=set();sources=set();transfers=[]
    for dilution in operations:
        if addition:
            fields(dilution,('source','destination','volume_ul','mix_after'),'Liquid addition')
            source,dest=(location(dilution[k]) for k in ('source','destination'))
            if source==dest or dest in destinations:fail('Additions require distinct source/destination and one addition per destination.')
            if dest[0]!=4:fail('Addition destinations must be in the transported plate at site 4.')
            if any(k not in volumes for k in (source,dest)):fail('Supply initial volume and minimum remainder for every addressed well.')
            if type(dilution['mix_after']) is not bool:fail('Specify whether to mix after adding liquid.')
            amount=number(dilution['volume_ul'],'Addition volume',1,capacity)
            if amount!=amount.quantize(Decimal('.1')):fail('Addition volume must use exact 0.1 uL increments.')
            total=volumes[dest]+amount
            if total>number(deck[dest[0]]['volume'],'Well capacity',1):fail('Addition exceeds destination well capacity.')
            if dilution['mix_after'] and mix>total:fail('Mix volume exceeds final well volume.')
            volumes[source]-=amount
            if volumes[source]<reserve[source]:fail('Insufficient source liquid after preserving its minimum remainder.')
            volumes[dest]=total;sources.add(source);destinations.add(dest)
            transfers.append(dict(source=deepcopy(dilution['source']),destination=deepcopy(dilution['destination']),volume_ul=float(amount),mix_after=dilution['mix_after']))
            rows.append(dict(kind='addition',source=deepcopy(dilution['source']),destination=deepcopy(dilution['destination']),
                initial_volume_ul=float(original[dest]),added_volume_ul=float(amount),final_volume_ul=float(total),mix_after=dilution['mix_after']))
            continue
        fields(dilution,('source','diluent','destination','dilution_factor','final_volume_ul'),'Dilution')
        source,diluent,dest=(location(dilution[k]) for k in ('source','diluent','destination'))
        if len({source,diluent,dest})!=3 or dest in destinations:fail('Each dilution needs distinct source, diluent and empty destination; no repeated destination.')
        if dest[0]!=4:fail('Dilution destinations must be in the transported plate at site 4.')
        if any(k not in volumes for k in (source,diluent,dest)):fail('Supply initial volume and minimum remainder for every addressed well.')
        if original[dest]!=0:fail('Destinations must be explicitly empty; existing culture wells are not overwritten.')
        factor=number(dilution['dilution_factor'],'Dilution factor',1)
        if factor<=1:fail('Independent dilution factor must be greater than 1.')
        total=number(dilution['final_volume_ul'],'Final volume',1,deck[dest[0]]['volume'])
        sample=total/factor;medium=total-sample
        for amount in (sample,medium):
            if amount!=amount.quantize(Decimal('.1')) or not 1<=amount<=capacity:
                fail('Each transfer must be 1–300 uL in exact 0.1 uL increments; change the volumes or factor. No implicit rounding or splitting.')
        if mix>total:fail('Mix volume exceeds the final well volume.')
        destinations.add(dest);sources.update((source,diluent))
        for src,amount,do_mix in ((diluent,medium,False),(source,sample,True)):
            volumes[src]-=amount
            if volumes[src]<reserve[src]:fail(f'Insufficient liquid at site {src[0]} {src[1]} after preserving its minimum remainder.')
            volumes[dest]+=amount
            transfers.append(dict(source=dict(site=src[0],well=src[1]),destination=dict(site=dest[0],well=dest[1]),volume_ul=float(amount),mix_after=do_mix))
        rows.append(dict(source=dilution['source'],diluent=dilution['diluent'],destination=dilution['destination'],
            dilution_factor=float(factor),sample_ul=float(sample),diluent_ul=float(medium),final_volume_ul=float(total)))
    if sources & destinations:fail('Serial/cascaded dilutions are not supported in this version; use independent stock wells.')
    if len(tips)!=len(transfers):fail(f'Provide exactly {len(transfers)} fresh tip wells, one for each transfer.')
    positions=[]
    for site in range(1,9):
        group=None
        if site in deck:
            group=dict(labwareId=deck[site]['id'],groupName=f'Site {site}: '+deck[site]['displayName'],
                reuseTipsBetweenSteps=False,liquidName='',liquidType='Water',liquidVolumeOptions='CalculateForMe')
        positions.append(dict(position=site,positionName=f'Site {site}',labwarePositions=[],labwareGroup=group,liquidVolume=0))
    def settings(height,volume,do_mix=False):
        return dict(transferVolume=volume,pipettingHeight=height,retractToWellTop=True,retractDistance=0,
            pipettingHeightStartPoint='FromContainerBottom',mixVolume=float(mix) if do_mix else 0,
            mixCycles=pip['mix_cycles'] if do_mix else 0,mixSpeed=pip['mix_speed'] if do_mix else 0,
            mixHeight=pip['mix_height_mm'] if do_mix else 0,enableMad=False,followLiquid=False,
            mixHeightStartPoint='FromContainerBottom',offset=dict(x=0,y=0),useOffset=False)
    steps=[]
    for index,t in enumerate(transfers,1):
        def target(which):
            a=t[which];return [dict(position=a['site'],addresses=[address(a['well'],deck[a['site']])])]
        steps.append(dict(channelSelection='TwoChannel',tipLabwareGroupId=0,liquidType='Aqueous',
            newTipsEachTransfer=True,mixBeforeAspirate=False,mixAfterDispense=t['mix_after'],
            tipReuseOption='PerTransfer',tipDiscardLocation='DiscardToWaste',dispenseToWaste=False,
            aspirateSettings=settings(pip['aspirate_height_mm'],t['volume_ul']),
            dispenseSettings=settings(pip['dispense_height_mm'],t['volume_ul'],t['mix_after']),
            sources=target('source'),destinations=target('destination'),customizeLiquid=False,customLiquidSettings=None,
            stepType='TransferSamplesStep',name=f"Transfer {index}: {t['volume_ul']:g} uL to {t['destination']['well']}",
            stepOrder=index,disabled=False,makeNameUnique=False))
    load=dict(residualTips=[dict(deckPosition=tip_site,residualTipData=dict(useAllAddresses=False,addresses=tip_addresses))],barcodes=[],
        liquidVolumes=[dict(deckPosition=site,positionOnSite=0,**address(well,deck[site]),volume=float(v)) for (site,well),v in original.items()])
    return dict(protocol=dict(name=spec['name'],makeNameUnique=False,skipValidation=False,deck=dict(positions=positions)),
        steps=steps,transfers=transfers,summary=rows,load_complete=load,tips_required=len(tips),
        remaining_volumes=[dict(site=k[0],well=k[1],volume_ul=float(v)) for k,v in volumes.items()])


def verify_protocol(protocol,compiled,spec):
    if protocol.get('isValid') is not True or protocol.get('validationErrors'):fail('Native Hamilton protocol is not valid.')
    if protocol.get('name')!=compiled['protocol']['name']:fail('Native protocol name changed.')
    actual={x['position']:x for x in protocol['deck']['positions']}
    for expected in compiled['protocol']['deck']['positions']:
        group=actual.get(expected['position'],{}).get('labwareGroup')
        wanted=expected['labwareGroup']
        if (wanted is None and group is not None) or (wanted and (not group or group['labware']['id']!=wanted['labwareId'])):
            fail('Native protocol deck changed.')
    tip_group=actual[spec['tip_site']]['labwareGroup']['id']
    expected_steps=deepcopy(compiled['steps'])
    for s in expected_steps:s['tipLabwareGroupId']=tip_group
    if normalized(protocol.get('steps'))!=normalized(expected_steps):fail('Native protocol steps differ from the reviewed dilution specification.')


def verify_simulation(result,job,protocol,compiled):
    if (result.get('id')!=job or result.get('protocolName')!=protocol['name'] or result.get('deviceSerialNumber')!='Simulation'
            or result.get('runResult')!='Completed' or result.get('errorMessages')):
        fail('Simulation did not report a successful exact-job result.')
    steps=result.get('runtimeSteps',[])
    if len(steps)!=len(compiled['transfers']):fail('Simulation transfer count differs from the draft.')
    for i,(step,transfer) in enumerate(zip(steps,compiled['transfers']),1):
        activities=step.get('pipetteActivities',[])
        if step.get('stepNumber')!=i or len(activities)!=1:fail('Unexpected simulated pipetting activity.')
        for native,key in (('source','source'),('target','destination')):
            endpoints=activities[0].get(native,[]);expected=transfer[key]
            if (len(endpoints)!=1 or endpoints[0].get('deckPosition')!=expected['site'] or endpoints[0].get('well')!=expected['well']
                    or Decimal(str(endpoints[0].get('volume')))!=Decimal(str(transfer['volume_ul']))):
                fail('Simulation wells or volumes differ from the draft.')
    overviews=result.get('stepOverviews',[])
    if len(overviews)!=len(steps) or any(not any(x.get('label')=='New Tips Each Transfer' and str(x.get('value')).lower()=='true'
            for x in overview.get('stepOverviewItems',[])) for overview in overviews):
        fail('Simulation did not confirm fresh tips for every transfer.')
