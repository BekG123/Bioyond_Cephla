"""Learned Cellvis calibration, HOME exchange, recorded one-queue Hamilton delivery.

Preview by default. Start full calibration at IDLE (or accepted released HOME
clearance) with empty jaws and healthy running Auto/Lua. --execute --path-clear
confirms the lid-off plate is flat in HOME, Hamilton idle/access open/site4 empty,
the calibration/scanner/HOME/recorded Hamilton sweeps and connectors are clear,
hands clear, and the E-stop supervised. Stops held at Hamilton, without release.
Proceeds without interactive inspections using the accepted setup and runtime
checks. --pause-for-inspection restores visual checks if desired.
Never starts Lua, resets faults, retries failed movement, or changes envelopes.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4
from run_cellvis24_workflow import api
from run_cellvis24_scanner import main as calibrate_to_scanner, confirm
from run_cellvis24_scanner_hamilton import scanner_phase, reconnect, dispatch
from cellvis24_recorded_hamilton_route import reference, PLAN, plan_path
from cellvis24_workflow import compile_steps
from run_record_io import write_run_record

ROOT=Path(__file__).resolve().parents[1]
REPORTS=ROOT/'operator_ui/reports/plate_session/cellvis24_recorded_hamilton'


def parse_args(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--full-calibration',action='store_true',help='Run learned projected calibration/grip/proof lift/scanner, return to HOME, then Hamilton.')
    mode.add_argument('--from-home',action='store_true',help='Reuse a fresh completed HOME release receipt; skip calibration/scanner.')
    p.add_argument('--source',type=Path,help='Fresh HOME release receipt for --from-home.')
    p.add_argument('--execute',action='store_true',help='Execute; omit for offline preview.')
    p.add_argument('--path-clear',action='store_true',help='Confirm clear recorded-height travel and added HOME/final placement connectors.')
    p.add_argument('--pause-for-inspection',action='store_true',help='Opt into alignment, proof-lift and HOME support inspection prompts.')
    p.add_argument('--smooth-transit',action='store_true',help='Select the new three-transit-waypoint candidate (six total queued moves); review its changed sweep before --execute --path-clear.')
    p.add_argument('--blend-transit',action='store_true',help='Use the successful six-point route with 1 mm blending at its two level transit corners; requires published Lua220112. Implies --smooth-transit.')
    p.add_argument('--opposite-wrist',action='store_true',help='Positive wrist route: first two turns at Z118.15, final turn/crossing at Z77, unchanged slow seating. One queue with native upper/final-corner blending; Z82 monitored trial limit; publish updated Lua220114.')
    args=p.parse_args(argv)
    if args.opposite_wrist:
        args.smooth_transit=True
        args.blend_transit=True
    if args.blend_transit:args.smooth_transit=True
    if args.source and not args.from_home:p.error('--source requires --from-home.')
    if args.execute and not args.path_clear:p.error('Execution requires --path-clear.')
    if args.execute and args.from_home and not args.source:p.error('--from-home --execute requires --source.')
    return args


def verify_backend(variant='recorded'):
    try:cap=api('developer/api/cellvis24-workflow/capabilities')
    except Exception as error:
        raise RuntimeError('Recorded-route backend is not available. Reload the console before starting; no calibration/motion was sent.') from error
    actual=cap.get('route_sha256') if variant=='recorded' else cap.get('recorded_route_variants',{}).get(variant)
    if cap.get('recorded_hamilton_delivery') is not True or actual!=hashlib.sha256(plan_path(variant).read_bytes()).hexdigest():
        raise RuntimeError('Backend route differs from this command. No motion sent.')
    if variant in ('blend3','opposite3'):
        reconnect()
        result=api('developer/api/cellvis24-workflow/blend-ready',{'variant':variant} if variant=='opposite3' else {})
        if result.get('blended_transit_capability')!=(220114 if variant=='opposite3' else 220112):raise RuntimeError('Blended transit capability not verified; no calibration started.')


def delivery(source,variant='recorded'):
    reconnect()
    plan=api('developer/api/cellvis24-workflow/preview',dict(stations=['hamilton'],cycles=1,
        source=str(Path(source).resolve()),recorded_hamilton_delivery=True,
        **({'recorded_hamilton_variant':variant} if variant!='recorded' else {})))['plan']
    return dispatch('developer/api/cellvis24-workflow/start',dict(plan=plan,ready=True,path_clear=True,
        setup_confirmed=True,recorded_clearance_confirmed=True),'cellvis24_workflow')


def main(argv=None):
    args=parse_args(argv);variant='opposite3' if args.opposite_wrist else 'blend3' if args.blend_transit else 'smooth3' if args.smooth_transit else 'recorded';route=reference(variant)
    route_sha=hashlib.sha256(plan_path(variant).read_bytes()).hexdigest()
    if not args.execute:
        print(json.dumps(dict(motion_sent=False,full_calibration=args.full_calibration,
            sequence=(['Learned Cellvis projected calibration, grip, 5mm proof lift and scanner',
                       'Return HOME, release28 and lift clear'] if args.full_calibration else [])+
                      ['Rotate released holder to90.716612 degrees','Short-side grip25; 5mm proof lift',
                       f"One {len(route['routes']['forward']['points'])}-target Lua queue; stop at original Hamilton endpoint holding plate"],
            hamilton_steps=compile_steps(['hamilton'],1,recorded_hamilton_delivery=True,recorded_hamilton_variant=variant),
            route_sha256=route_sha,variant=variant,comparison=route.get('comparison'),transit_targets=route.get('transit_targets'),
            queue_targets=len(route['routes']['forward']['points']),transit_speed=137,final_seating_speed=5,
            inspection_pauses=args.pause_for_inspection,
            segment_zones=[-1,1,1,5,-1,-1] if args.opposite_wrist else [ -1,1,1,-1,-1,-1] if args.blend_transit else [-1]*len(route['routes']['forward']['points']),
            publish_required=220114 if args.opposite_wrist else 220112 if args.blend_transit else None,
            live_acceptance='Z77 route unchanged; first level turn junction blends. Exact lowering/seating boundaries remain. Physical blending/clearance untested.' if args.opposite_wrist else 'Blended corners are untested; successful waypoint run does not verify blending' if args.blend_transit else 'Operator reported this waypoint route worked; corner stops reported'),indent=2))
        return
    verify_backend(variant)  # Detect stale loaded code before calibration or motion.
    REPORTS.mkdir(parents=True,exist_ok=True);path=REPORTS/(uuid4().hex+'.json')
    record=dict(status='starting',at=time.time(),full_calibration=args.full_calibration,
                inspection_mode='interactive' if args.pause_for_inspection else 'accepted_setup_no_fresh_inspection',
                route_sha256=route_sha,variant=variant,steps=[],automatic_retries=False)
    def save():write_run_record(path,record)
    def add(phase,receipt):
        receipt=Path(receipt)
        record['steps'].append(dict(phase=phase,record=str(receipt),sha256=hashlib.sha256(receipt.read_bytes()).hexdigest()));save()
    save()
    try:
        source=args.source
        if args.full_calibration:
            calibration=calibrate_to_scanner(['--full-calibration','--execute']+
                ([] if args.pause_for_inspection else ['--continuous']))
            ident=calibration['trial_id'];record['trial_id']=ident
            add('calibration_scanner',calibration['final']['record'])
            result=scanner_phase(ident,'return_home');add('return_home',result['record'])
            if args.pause_for_inspection:
                confirm('Is the plate flat and fully supported in HOME with both jaws clear to open28, hands clear and E-stop supervised?')
                record['home_support_confirmed_at']=time.time()
            record['home_release_basis']='fresh_operator_inspection' if args.pause_for_inspection else 'accepted_seating_pose_and_runtime_checks'
            save()
            result=scanner_phase(ident,'release_home',True);source=Path(result['record']);add('release_home',source)
        result=delivery(source,variant) if args.smooth_transit else delivery(source)
        add('recorded_hamilton_delivery',result['record'])
        record.update(status='arrived_hamilton_held_operator_observation_pending',final=result)
        print('Stopped at Hamilton with plate held. No release or return was commanded.',flush=True)
    except BaseException as error:
        record.update(status='stopped_or_uncertain',error=str(error));raise
    finally:
        record['finished_at']=time.time();save()
        print(json.dumps(dict(status=record['status'],record=str(path))),flush=True)
    return record


if __name__=='__main__':main()
