"""Deliver from calibrated HOME over the taught three-target route; stop held.

Preview is offline. --execute --path-clear confirms unchanged empty Hamilton
site4, access open, clear combined plate/wrist sweep and supervised E-stop.
Requires a fresh HOME release receipt. No calibration, reset, release or return.
"""
import argparse
import json
from pathlib import Path
from run_cellvis24_workflow import api
from run_cellvis24_scanner_hamilton import dispatch, reconnect
from cellvis24_workflow import compile_steps


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path)
    p.add_argument('--execute',action='store_true')
    p.add_argument('--path-clear',action='store_true')
    args=p.parse_args(argv)
    if args.execute and (not args.path_clear or not args.source):
        p.error('Execution requires --source and --path-clear.')
    if not args.execute:
        print(json.dumps(dict(motion_sent=False,steps=compile_steps(['hamilton'],1,taught_hamilton_delivery=True),
                             finish='Hamilton original endpoint, plate held; no release or return'),indent=2))
        return
    reconnect()
    plan=api('developer/api/cellvis24-workflow/preview',dict(stations=['hamilton'],cycles=1,
        source=str(args.source.resolve()),taught_hamilton_delivery=True))['plan']
    result=dispatch('developer/api/cellvis24-workflow/start',dict(plan=plan,ready=True,path_clear=True,
        setup_confirmed=True,taught_clearance_confirmed=True),'cellvis24_workflow')
    print(json.dumps(result),flush=True)
    return result


if __name__=='__main__':main()
