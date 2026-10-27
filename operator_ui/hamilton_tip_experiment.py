"""Exact-count intent preview. Never substitute a multi-pair diagnostic.

The installed Prep diagnostic exposes no pair count. Until an exact-count
method is commissioned this preview cannot dispatch any part of the chain.
"""
from copy import deepcopy
import time
from uuid import uuid4
from researcher_teaching import TeachingError


def propose(agent,pair_count,hamilton_calibration,arm_calibration,
            tip_site=7,tip_labware_id=273):
    if type(pair_count) is not int or not 1<=pair_count<=100:
        raise TeachingError('Choose 1 to 100 two-tip pickup/ejection pairs.')
    if type(hamilton_calibration) is not bool or type(arm_calibration) is not bool:
        raise TeachingError('Specify which calibrations are requested.')
    if type(tip_site) is not int or not 1<=tip_site<=8 or type(tip_labware_id) is not int or tip_labware_id<=0:
        raise TeachingError('Select a tip rack and site from 1 to 8.')
    runner=agent.get_runner()
    if runner.active or runner.reserved:raise TeachingError('Wait for the current workflow to finish.')
    with agent.lock:
        if agent.review:raise TeachingError('Finish the current inspection first.')
    engine=agent.roundtrip_workflow()
    blockers=list(engine.catalog()['blockers'])
    blockers.append(f'Exactly {pair_count} two-tip pickup/ejection pairs needs a commissioned exact-count method. The native pickup diagnostic has no pair-count parameter and can consume multiple pairs; repeating it is not equivalent.')
    parts={}
    for key,fn in (
        ('rack',lambda:engine.hamilton.calibration_setup(tip_site,tip_labware_id)),
        ('imaging',lambda:engine.imaging.prepare(None,allow_loading_return=True))):
        try:parts[key]=fn()
        except Exception as error:blockers.append(str(error))
    steps=[]
    def add(phase,label,**kw):steps.append(dict(kind='tip_experiment_preview',phase=phase,label=label,**kw))
    if hamilton_calibration:
        add('hamilton_calibration','Hamilton full calibration once: self-calibrate, calibrate channel height/squeeze')
    if arm_calibration:
        add('arm_calibration','Arm full calibration once: calibrate, pick up the plate, lift and return Home')
    add('hamilton_dropoff','Deliver the plate from Home to Hamilton; release it and return Home empty')
    for pair in range(1,pair_count+1):
        add('tip_pair',f'Pair {pair}/{pair_count}: pick up two tips at site {tip_site}, eject both to waste, and verify completion',pair=pair)
    add('hamilton_retrieve','Retrieve the plate from Hamilton and return Home')
    add('stage_prepare','Prepare Squid loading position')
    add('squid_dropoff','Deliver and release the plate at Squid; return Home empty')
    add('scan_entry','Move Squid into the imaging area')
    add('image_start','Start one Squid imaging run using current settings')
    add('image_wait','Wait at Home for that imaging run to finish; leave the plate at Squid')
    plan=dict(id=uuid4().hex,at=time.time(),dispatch='experiment_preview',actions=['tip_waste_then_image'],
        executable=False,blockers=list(dict.fromkeys(blockers)),steps=steps,parts=parts,
        labels=[f'{pair_count} two-tip pairs, then one imaging run'],repetitions=1,
        counts=dict(tip_pairs=pair_count,tips=2*pair_count,imaging_runs=1,complete_roundtrips=0),
        final_plate='Squid',final_arm='Home',
        summary=(('Calibrate Hamilton once. ' if hamilton_calibration else '')+
                 ('Calibrate the arm and pick up the plate once. ' if arm_calibration else '')+
                 f'Deliver the plate to Hamilton, perform exactly {pair_count} two-tip pickup/ejection pairs ({2*pair_count} tips), then transfer via Home for one Squid imaging run using current settings. Leave the plate at Squid and the arm at Home.'),
        requirements=['This is a preview only; no partial sequence starts while any blocker remains.',
            'The pair count covers the pickup/waste test only; calibration may consume additional tips.',
            'A ready complete plan uses one confirmation; no confirmation between successful commissioned steps.',
            'Verify tip inventory, waste capacity, plate support and the taught holder positions.'])
    with agent.lock:agent.pending=plan
    agent._announce_plan(plan)
    return deepcopy(plan)
